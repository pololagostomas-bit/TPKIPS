"""Read-only stage-1 workload reporting; deliberately independent of app.py.

Productivity is net valid work, not an as-of reconstruction: a later reset or
rollback into picking invalidates the earlier completion even in an old range.
Night cohorts use original SAP order timestamps, but their status is CURRENT:
stage 1 does not retain historical order/line snapshots at every import cutoff.
"""

import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone


LIMA = timezone(timedelta(hours=-5))
PRE_PICK = {"PENDIENTE", "ASIGNADO", "EN PICKING"}
POST_PICK = {"PICKING FINALIZADO", "POR GUIAR", "EN GUIADO",
             "GUIADO FINALIZADO", "ENTREGADO", "CERRADO SAP"}


def _now():
    return datetime.now(LIMA)


def _timestamp(value):
    """Excel datetime cells are imported with str(): YYYY-MM-DD HH:MM:SS.

    Also accept ISO offsets and day-first textual SAP exports. Date-only values
    mean midnight, as do date-only Excel cells; no import/load time is inferred.
    """
    value = str(value or "").strip()
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        result = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                result = datetime.strptime(value, fmt)
                break
            except ValueError:
                pass
        if result is None:
            return None
    try:
        return result.astimezone(LIMA).replace(tzinfo=None) if result.tzinfo else result
    except (OverflowError, ValueError):
        return None


def _date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{name} debe tener formato YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} no es una fecha válida") from error


def _username(value):
    return str(value or "").strip().casefold()


def _qty(value):
    try:
        result = float(value or 0)
        return max(0.0, result) if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


def _rows(connection, table):
    # All callers supply literal table names, never request parameters. Avoid
    # changing the caller's row_factory, transaction or connection ownership.
    cursor = connection.execute(f"SELECT * FROM {table}")
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _internal_client(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c)).upper()
    # Punctuation/spacing variants only; no prefix or substring matching.
    return re.sub(r"[\W_]+", "", value) == "TRITONTRADINGSA"


def _range(period, start, end, reference, timestamps):
    if period not in {"day", "week", "weekdays", "all"}:
        raise ValueError("period debe ser day, week, weekdays o all")
    if reference is None:
        ref = _now().astimezone(LIMA).date()
    elif isinstance(reference, datetime):
        ref = (reference.astimezone(LIMA) if reference.tzinfo else reference).date()
    elif isinstance(reference, date):
        ref = reference
    else:
        ref = _date(reference, "reference")
    if start is not None or end is not None:
        first = _date(start if start is not None else end, "start")
        last = _date(end if end is not None else start, "end")
    elif period == "day":
        first = last = ref
    elif period == "week":
        first = ref - timedelta(days=ref.weekday())
        last = min(date.max, first + timedelta(days=min(6, (date.max - first).days)))
    else:
        # Legacy all/weekdays remain accepted, bounded to the last 366 calendar
        # days. Report the effective range instead of silently returning totals
        # for an unbounded lifetime with a one-day target.
        floor = ref - timedelta(days=min(365, (ref - date.min).days))
        first = max(floor, min([ref] + [t.date() for t in timestamps if t and t.date() <= ref]))
        last = ref
    if first > last:
        raise ValueError("start no puede ser posterior a end")
    if (last - first).days >= 366:
        raise ValueError("El rango inclusivo no puede superar 366 días")
    # Night windows need the previous calendar day.
    if first == date.min:
        raise ValueError("start debe ser posterior a 0001-01-01")
    return first, last, ref


def _evidence(connection, tables, users):
    attentions = _rows(connection, "attentions")
    by_order = defaultdict(list)
    for attention in attentions:
        by_order[attention["sap_ov"]].append(attention)
    histories = defaultdict(list)
    assignments = defaultdict(list)
    lines = defaultdict(list)
    movements = defaultdict(list)
    for row in _rows(connection, "attention_history"):
        row["evidence_table"] = "attention_history"
        histories[row["attention_id"]].append(row)
    for row in _rows(connection, "attention_assignments"):
        assignments[row["attention_id"]].append(row)
    # Old order-level audit is attributable to an attention only when unique,
    # and never duplicates native attention status history.
    legacy = defaultdict(list)
    if "history" in tables:
        for row in _rows(connection, "history"):
            row["evidence_table"] = "history"
            legacy[row["sap_ov"]].append(row)
    legacy_assignments = defaultdict(list)
    if "assignments" in tables:
        for row in _rows(connection, "assignments"):
            legacy_assignments[row["sap_ov"]].append(row)
    for ov, group in by_order.items():
        if len(group) == 1:
            aid = group[0]["id"]
            if not any(h["field_name"] == "app_status" or h["event_type"] == "REINICIO_ADMIN"
                       for h in histories[aid]):
                histories[aid].extend(legacy[ov])
                assignments[aid].extend(legacy_assignments[ov])
    for row in _rows(connection, "attention_lines"):
        lines[row["attention_id"]].append(row)
    if "stock_movements" in tables:
        for row in _rows(connection, "stock_movements"):
            if row["movement_type"] in {"CONSUMO", "REVERSA_CONSUMO", "REVERSA_REINICIO"}:
                movements[row["attention_id"]].append(row)

    completions, assigned, audit, timestamps = [], [], [], []
    for attention in attentions:
        aid = attention["id"]
        attention_audit = []
        events = histories[aid]
        # In native data ASIGNACION and attention_assignments are written in
        # pairs. Prefer history IDs to order operations within the same second.
        pairs = {(h["created_at"], _username(h["new_value"])) for h in events
                 if h["field_name"] == "current_picker"}
        events = list(events)
        for assignment in assignments[aid]:
            if assignment["role"] != "PICKER":
                continue
            if (assignment["created_at"], _username(assignment["new_user"])) in pairs:
                continue
            events.append({**assignment, "event_type": "ASIGNACION",
                           "field_name": "current_picker", "new_value": assignment["new_user"],
                           "evidence_table": "assignments", "sort_priority": -1})
        parsed = []
        for event in events:
            stamp = _timestamp(event["created_at"])
            if stamp:
                timestamps.append(stamp)
                parsed.append((stamp, event.get("sort_priority", 0), event["id"], event))
        parsed.sort(key=lambda item: item[:3])
        picker, picker_source, current, cycle_start = "", None, None, datetime.min
        for stamp, _, _, event in parsed:
            kind, field, new = event["event_type"], event["field_name"], event["new_value"]
            if field == "current_picker":
                picker = _username(new)
                picker_source = event["evidence_table"]
                if picker:
                    assigned.append({"username": picker, "sap_ov": attention["sap_ov"], "at": stamp})
            invalidates = kind == "REINICIO_ADMIN" or (field == "app_status" and new in PRE_PICK)
            if invalidates:
                if current is not None:
                    current["valid"] = False
                    current["invalidated_by"] = {"id": event["id"], "event_type": kind,
                                                  "created_at": event["created_at"]}
                    current = None
                cycle_start = stamp
                if kind == "REINICIO_ADMIN" or new == "PENDIENTE":
                    picker, picker_source = "", None
            if not (kind == "ESTADO" and field == "app_status" and new == "PICKING FINALIZADO"):
                continue
            actor = _username(event["username"])
            actor_user = users.get(actor)
            actor_is_picker = (actor_user and actor_user["role"] == "PICKER") or (
                actor and actor_user is None and not actor.startswith(("sistema", "system", "admin", "demo.admin")))
            owner = picker or (actor if actor_is_picker else "")
            record = {"attention_id": aid, "sap_ov": attention["sap_ov"],
                      "event_id": event["id"], "evidence_table": event["evidence_table"],
                      "completed_at": stamp.isoformat(timespec="seconds"), "at": stamp,
                      "username": owner or None, "actor": actor,
                      "attribution_source": picker_source if picker else "history_username" if owner else None,
                      "valid": True, "cycle_start": cycle_start}
            if current is not None or event.get("old_value") == new:
                record.update(valid=False, exclusion_reason="duplicate_completion")
            else:
                current = record
            audit.append(record)
            attention_audit.append(record)

        for record in [r for r in attention_audit if r["valid"]]:
            # A consumed movement is the immutable quantity snapshot made by
            # the completion operation. Ignore reservations/planned quantities.
            ledger = [(t, m) for m in movements[aid] if (t := _timestamp(m["created_at"]))
                      and t <= record["at"]]
            reversed_lines = {}
            for stamp, movement in ledger:
                if movement["movement_type"] != "CONSUMO":
                    line = movement["attention_line_id"]
                    reversed_lines[line] = max(reversed_lines.get(line, (datetime.min, -1)),
                                               (stamp, movement["id"]))
            consumed = [m for stamp, m in ledger if m["movement_type"] == "CONSUMO"
                        and stamp >= record["cycle_start"]
                        and (stamp, m["id"]) > reversed_lines.get(m["attention_line_id"], (datetime.min, -1))]
            if consumed:
                units = sum(_qty(m["quantity"]) for m in consumed)
                source = "stock_movements.CONSUMO"
            else:
                # For older data without stock movements, reverse audited
                # post-completion quantity edits to recover completion quantity.
                units = sum(_qty(line["picked_qty"]) for line in lines[aid])
                for stamp, _, event_id, event in parsed:
                    if (stamp, event_id) > (record["at"], record["event_id"]) and event["field_name"] == "picked_qty":
                        units -= _qty(event["new_value"]) - _qty(event.get("old_value"))
                units = max(0.0, units)
                source = "attention_lines.picked_qty_with_audit"
            record.update(picked_units=units, quantity_source=source)
            if attention["app_status"] not in POST_PICK:
                record.update(valid=False, exclusion_reason="current_state_before_completion")
            elif not record["username"]:
                record["exclusion_reason"] = "missing_picker_evidence"
            if record["valid"]:
                completions.append(record)
    return completions, assigned, audit, timestamps


def _metrics(completions, assignments, users, first, last):
    workdays = sum((first + timedelta(days=i)).weekday() < 5 for i in range((last - first).days + 1))
    def included(stamp):
        return first <= stamp.date() <= last and stamp.weekday() < 5
    completed = [r for r in completions if r["username"] and included(r["at"])]
    assigned = [r for r in assignments if included(r["at"])]
    names = {name for name, user in users.items() if user["role"] == "PICKER" and user["active"]}
    names.update(r["username"] for r in completed + assigned)
    result = []
    for name in sorted(names):
        user = users.get(name, {})
        work = [r for r in completed if r["username"] == name]
        allocations = [r for r in assigned if r["username"] == name]
        ovs = {r["sap_ov"] for r in work}
        units = sum(r["picked_units"] for r in work)
        target_ovs, target_units = 20 * workdays, 200 * workdays
        score = round(min(1.0, len(ovs) / target_ovs, units / target_units) * 100, 1) if workdays else None
        result.append({"username": name, "display_name": user.get("display_name", name),
                       "shift": user.get("shift", "SIN REGISTRO"), "active": user.get("active", 0),
                       "registered": bool(user), "workdays": workdays,
                       "assigned_ovs": len({r["sap_ov"] for r in allocations} | ovs),
                       "completed_ovs": len(ovs), "completed_attentions": len(work),
                       "picked_units": units, "target_ovs": target_ovs, "target_units": target_units,
                       "first_assigned_at": min((r["at"].isoformat() for r in allocations), default=None),
                       "compliance_pct": score,
                       "traffic_light": "SIN META" if score is None else "VERDE" if score >= 100 else "AMARILLO" if score >= 70 else "ROJO"})
    return result, workdays


def _night(orders, completions, first, last):
    local = {r["sap_ov"] for r in completions}
    source = []
    for order in orders:
        if not _internal_client(order.get("customer_name")):
            continue
        stamp = _timestamp(order.get("source_order_date"))
        sap_closed = order.get("app_status") == "CERRADO SAP" or str(order.get("document_status") or "").strip().upper() in {"CERRADO", "CERRADA", "CLOSED", "C"}
        complete = order["sap_ov"] in local
        source.append((stamp, {"sap_ov": order["sap_ov"], "source_order_date": order.get("source_order_date"),
                               "app_status": order.get("app_status"), "closed_sap": sap_closed,
                               "local_complete": complete,
                               "pending": not sap_closed and order.get("app_status") != "ENTREGADO",
                               "source_present": order.get("source_present", 1)}))
    cohorts = []
    for i in range((last - first).days + 1):
        day = first + timedelta(days=i)
        upper = datetime.combine(day, time(16))
        lower = upper - timedelta(days=1)
        buckets = {key: [] for key in ("window", "carryover", "date_missing", "after_window")}
        for stamp, order in source:
            bucket = "date_missing" if stamp is None else "carryover" if stamp <= lower else "window" if stamp <= upper else "after_window"
            buckets[bucket].append(order)
        window = buckets["window"]
        closed = sum(r["closed_sap"] for r in window)
        locally_done = sum(r["local_complete"] for r in window)
        cohorts.append({"cutoff_at": upper.isoformat(timespec="seconds"),
                        "window_start": lower.isoformat(timespec="seconds"), "window_end": upper.isoformat(timespec="seconds"),
                        "work_day": day.isoformat(),
                        "ready_day": (day + timedelta(days=1)).isoformat() if day < date.max else None,
                        "weekday_included": day.weekday() < 5, "status_basis": "current_not_historical_snapshot",
                        "total_ovs": len(window), "closed_sap_ovs": closed,
                        "local_completed_ovs": locally_done,
                        "picking_pending_ovs": sum(not r["closed_sap"] and not r["local_complete"] for r in window),
                        "closed_ovs": sum(r["closed_sap"] or r["app_status"] == "ENTREGADO" for r in window),
                        "pending_ovs": sum(r["pending"] for r in window),
                        "unstarted_ovs": sum(r["pending"] and r["app_status"] in {"PENDIENTE", "ASIGNADO"} for r in window),
                        "carryover_ovs": len(buckets["carryover"]),
                        "carryover_pending_ovs": sum(r["pending"] for r in buckets["carryover"]),
                        "date_missing_ovs": len(buckets["date_missing"]),
                        # Window details occur once per order. Repeating all
                        # carryover/missing/future details for 366 days would
                        # grow the response into hundreds of megabytes.
                        "after_window_ovs": len(buckets["after_window"]), "orders": {"window": window}})
    return cohorts


def workload_report(connection, period="day", start=None, end=None, reference=None):
    """Return JSON-ready daily/weekly metrics and 16:00 internal-client cohorts.

    start/end: inclusive strict YYYY-MM-DD; a single bound selects that day.
    Explicit bounds override period presets. week is Monday-Sunday containing
    reference (default Lima today). all/weekdays default to available evidence
    within the last 366 days ending at reference. Every productivity view counts
    Monday-Friday only; night cohorts retain calendar windows, flagged by weekday.
    Daily/weekly rows are NOT additive for distinct OVs across multiple periods.
    The caller owns the connection; this function never imports app or writes SQL.
    """
    # Validate explicit input before querying (also works with a read-only DB).
    first, last, ref = _range(period, start, end, reference, [])
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    users = {_username(row["username"]): row for row in _rows(connection, "users")}
    orders = _rows(connection, "orders")
    completions, assignments, audit, timestamps = _evidence(connection, tables, users)
    timestamps.extend(_timestamp(order.get("source_order_date")) for order in orders)
    first, last, _ = _range(period, start, end, ref, timestamps)
    metrics, workdays = _metrics(completions, assignments, users, first, last)
    daily, weekly = [], []
    for i in range((last - first).days + 1):
        day = first + timedelta(days=i)
        if day.weekday() < 5:
            rows, count = _metrics(completions, assignments, users, day, day)
            daily.append({"work_day": day.isoformat(), "workdays": count, "picker_metrics": rows})
    cursor = first
    while cursor <= last:
        week_end = min(last, cursor + timedelta(days=min(6 - cursor.weekday(), (date.max - cursor).days)))
        rows, count = _metrics(completions, assignments, users, cursor, week_end)
        weekly.append({"week_start": (cursor - timedelta(days=cursor.weekday())).isoformat(),
                       "start": cursor.isoformat(), "end": week_end.isoformat(),
                       "workdays": count, "picker_metrics": rows})
        if week_end == last:
            break
        cursor = week_end + timedelta(days=1)
    scoped_audit = []
    for record in audit:
        if first <= record["at"].date() <= last:
            item = {key: value for key, value in record.items() if key not in {"at", "cycle_start"}}
            if not item["valid"]:
                item.setdefault("exclusion_reason", "invalidated_by_audit")
            elif record["at"].weekday() >= 5:
                item["exclusion_reason"] = "weekend"
            item["included"] = item["valid"] and not item.get("exclusion_reason")
            scoped_audit.append(item)
    return {"period": period, "start": first.isoformat(), "end": last.isoformat(),
            "reference": ref.isoformat(), "timezone": "America/Lima", "workdays": workdays,
            "picker_metrics": metrics, "daily_metrics": daily, "weekly_metrics": weekly,
            "cutoffs": _night(orders, completions, first, last), "completion_audit": scoped_audit,
            "targets": {"ovs": 20, "units": 200, "green_min": 100, "yellow_min": 70,
                        "workdays": workdays, "period_ovs": 20 * workdays, "period_units": 200 * workdays},
            "notes": ["Productividad neta: reinicios y retrocesos posteriores pueden invalidar trabajo anterior.",
                      "Las OVs distintas del período no se obtienen sumando los subtotales diarios/semanales.",
                      "Cohortes nocturnas por fecha SAP original; estados actuales, no fotos históricas del corte.",
                      "all/weekdays sin fechas se limitan a los últimos 366 días hasta reference."]}
