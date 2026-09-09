"""Synthetic, isolated stage-1 reporting tests; never import app or open triton.db.

Run from the project root: py -B -m unittest tests.test_workload -v
The production CREATE TABLE script is read via AST, NOT executed through init_db.
Each test database has a unique temporary filename inside project qa/.
"""

import ast
import json
import sqlite3
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.services.workload import workload_report


ROOT = Path(__file__).resolve().parents[1]


def _schema():
    source = ast.parse((ROOT / "backend" / "app.py").read_text(encoding="utf-8-sig"))
    init = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "init_db")
    call = next(node for node in ast.walk(init) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "executescript")
    return ast.literal_eval(call.args[0])


class WorkloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _schema()

    def setUp(self):
        # Python 3.14's private-directory ACLs conflict with the Windows runner
        # sandbox. Unique files under the existing QA directory retain its ACL.
        test_db = ROOT / "qa" / ("workload-" + uuid.uuid4().hex + ".db")
        self.addCleanup(test_db.unlink, missing_ok=True)
        self.db = sqlite3.connect(test_db)
        self.addCleanup(self.db.close)
        self.db.executescript(self.schema)
        for name, spec in (("source_cutoff_at", "TEXT"), ("source_present", "INTEGER DEFAULT 1")):
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(orders)")}
            if name not in columns:
                self.db.execute(f"ALTER TABLE orders ADD COLUMN {name} {spec}")
        self.user("alice", shift="NOCHE")
        self.user("bob")
        self.user("idle")
        self.user("admin", role="ADMINISTRADOR")

    def insert(self, table, **values):
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        return self.db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())).lastrowid

    def user(self, name, shift="DÍA", role="PICKER", active=1):
        self.insert("users", username=name, display_name=name.title(), role=role,
                    shift=shift, active=active, created_at="2020-01-01T20:00:00", updated_at="2020-01-01T20:00:00")

    def order(self, ov, source="2026-09-01 15:00:00", customer="Triton Trading S.A.", status="PENDIENTE", **extra):
        self.insert("orders", sap_ov=ov, customer_name=customer, source_order_date=source,
                    app_status=status, source_cutoff_at="2026-09-05T16:00:00",
                    created_at="2020-01-01T20:00:00", updated_at="2026-09-05T20:00:00", **extra)

    def attention(self, ov, units=10, picker="alice", status="POR GUIAR"):
        if not self.db.execute("SELECT 1 FROM orders WHERE sap_ov=?", (ov,)).fetchone():
            self.order(ov)
        seq = self.db.execute("SELECT COUNT(*) FROM attentions WHERE sap_ov=?", (ov,)).fetchone()[0] + 1
        aid = self.insert("attentions", sap_ov=ov, sequence_no=seq, attention_type="PARCIAL",
                          current_picker=picker, app_status=status, created_at="2020-01-01T20:00:00",
                          updated_at="2026-09-05T20:00:00")
        line = self.insert("order_lines", sap_ov=ov, source_row=seq, item_code=f"SKU-{seq}", required_qty=999, pending_qty=999)
        self.insert("attention_lines", attention_id=aid, order_line_id=line, planned_qty=999, picked_qty=units, delivered_qty=0)
        return aid

    def event(self, aid, at="2026-09-01T10:00:00", new="PICKING FINALIZADO", old="EN PICKING", actor="alice", kind="ESTADO", field="app_status"):
        return self.insert("attention_history", attention_id=aid, event_type=kind, field_name=field,
                           old_value=old, new_value=new, username=actor, created_at=at)

    def assign(self, aid, name="alice", at="2026-09-01T08:00:00", history=True):
        self.insert("attention_assignments", attention_id=aid, role="PICKER", old_user="", new_user=name,
                    username="admin", created_at=at)
        if history:
            self.event(aid, at, new=name, old="", actor="admin", kind="ASIGNACION", field="current_picker")

    def movement(self, aid, at, quantity, kind="CONSUMO"):
        line = self.db.execute("SELECT id FROM attention_lines WHERE attention_id=?", (aid,)).fetchone()[0]
        ov = self.db.execute("SELECT sap_ov FROM attentions WHERE id=?", (aid,)).fetchone()[0]
        return self.insert("stock_movements", attention_id=aid, attention_line_id=line, sap_ov=ov,
                           item_key="SKU", item_code="SKU", warehouse_key="1", warehouse="1", pool_type="STOCK",
                           movement_type=kind, quantity=quantity, username="alice", created_at=at)

    def report(self, **kwargs):
        return workload_report(self.db, **{"reference": "2026-09-01", **kwargs})

    def metric(self, report, name="alice"):
        return next(row for row in report["picker_metrics"] if row["username"] == name)

    def test_zero_activity_registry_shift_and_week_targets(self):
        report = self.report(period="week")
        self.assertEqual((report["start"], report["end"], report["workdays"]), ("2026-08-31", "2026-09-06", 5))
        self.assertEqual(len(report["picker_metrics"]), 3)
        self.assertEqual((self.metric(report)["target_ovs"], self.metric(report)["target_units"]), (100, 1000))
        self.assertEqual(self.metric(report)["shift"], "NOCHE")
        self.assertEqual(self.metric(report, "bob")["shift"], "DÍA")
        self.assertEqual(self.metric(report, "idle")["compliance_pct"], 0)

    def test_event_date_filter_precedes_aggregation_and_old_creation_is_irrelevant(self):
        old = self.attention("old", units=700)
        self.event(old, "2026-08-31T10:00:00")
        today = self.attention("today", units=13)
        self.event(today)
        future = self.attention("future", units=500)
        self.event(future, "2026-09-02T00:00:00")
        report = self.report()
        self.assertEqual((self.metric(report)["completed_ovs"], self.metric(report)["picked_units"]), (1, 13))

    def test_actual_work_only_not_imported_closed_or_prefilled_or_status_only(self):
        sap = self.attention("sap", 300, status="CERRADO SAP")
        self.event(sap, kind="CIERRE_SAP", new="CERRADO SAP", actor="sistema-sap")
        self.attention("prefilled", 100, status="EN PICKING")
        self.attention("status-without-event", 900, status="ENTREGADO")
        done = self.attention("done-then-sap", 7, status="CERRADO SAP")
        self.event(done)
        self.event(done, "2026-09-02T12:00:00", kind="CIERRE_SAP", new="CERRADO SAP", old="POR GUIAR", actor="sistema-sap")
        self.assertEqual(self.metric(self.report())["picked_units"], 7)
        self.assertEqual(self.metric(self.report())["completed_ovs"], 1)

    def test_distinct_ovs_per_picker_period_units_per_attention(self):
        for units, actor, at in ((4, "alice", "2026-09-01T10:00:00"), (6, "alice", "2026-09-02T10:00:00"), (9, "bob", "2026-09-02T11:00:00")):
            aid = self.attention("shared", units, picker=actor)
            self.event(aid, at, actor=actor)
        report = self.report(start="2026-09-01", end="2026-09-02")
        self.assertEqual((self.metric(report)["completed_ovs"], self.metric(report)["completed_attentions"], self.metric(report)["picked_units"]), (1, 2, 10))
        self.assertEqual(self.metric(report, "bob")["completed_ovs"], 1)
        self.assertEqual(sum(self.metric(row)["completed_ovs"] for row in report["daily_metrics"]), 2)

    def test_immutable_assignment_and_admin_completion(self):
        aid = self.attention("assigned", 8, picker="bob")
        self.assign(aid, " ALICE ")
        self.event(aid, actor="admin")
        self.assign(aid, "bob", "2026-09-02T08:00:00")
        report = self.report()
        self.assertEqual(self.metric(report)["picked_units"], 8)
        self.assertEqual(self.metric(report, "bob")["picked_units"], 0)
        self.assertEqual(report["completion_audit"][0]["attribution_source"], "attention_history")

    def test_actor_fallback_and_no_mutable_picker_fallback(self):
        aid = self.attention("actor", 8, picker="bob")
        self.event(aid, actor=" Alice ")
        unattributed = self.attention("unknown", 50, picker="bob")
        self.event(unattributed, actor="admin")
        report = self.report()
        self.assertEqual(self.metric(report)["picked_units"], 8)
        self.assertEqual(self.metric(report, "bob")["picked_units"], 0)
        self.assertEqual(report["completion_audit"][1]["exclusion_reason"], "missing_picker_evidence")

    def test_assignment_table_fallback_and_same_second_history_order(self):
        aid = self.attention("table", 5)
        self.assign(aid, history=False)
        self.event(aid, actor="admin")
        other = self.attention("ties", 7)
        self.assign(other, "alice", "2026-09-01T10:00:00")
        self.event(other)
        self.assign(other, "bob", "2026-09-01T10:00:00")
        self.assertEqual(self.metric(self.report())["picked_units"], 12)

    def test_reset_invalidates_old_period_and_recompletion_belongs_to_new_picker(self):
        aid = self.attention("redo", 3, picker="bob")
        self.assign(aid)
        self.event(aid)
        self.event(aid, "2026-09-02T08:00:00", new="PENDIENTE", old="POR GUIAR", actor="admin", kind="REINICIO_ADMIN", field="attention")
        self.assign(aid, "bob", "2026-09-02T09:00:00")
        self.event(aid, "2026-09-02T10:00:00", actor="bob")
        report = self.report(start="2026-09-01", end="2026-09-02")
        self.assertEqual(self.metric(report)["completed_ovs"], 0)
        self.assertEqual(self.metric(report, "bob")["picked_units"], 3)
        self.assertFalse(report["completion_audit"][0]["valid"])
        self.assertEqual(self.metric(self.report())["completed_ovs"], 0)

    def test_rollback_to_picking_invalidates_but_guide_rollback_does_not(self):
        for ov, status in (("invalid", "EN PICKING"), ("valid", "POR GUIAR")):
            aid = self.attention(ov, 5, status=status)
            self.event(aid)
            self.event(aid, "2026-09-02T12:00:00", new=status, old="EN GUIADO", kind="RETROCESO_ADMIN", actor="admin")
        self.assertEqual(self.metric(self.report())["picked_units"], 5)

    def test_duplicate_completion_is_not_double_counted(self):
        aid = self.attention("dup", 5)
        self.event(aid)
        self.event(aid, "2026-09-02T12:00:00")
        report = self.report(start="2026-09-01", end="2026-09-02")
        self.assertEqual(self.metric(report)["completed_attentions"], 1)
        self.assertEqual(report["completion_audit"][1]["exclusion_reason"], "duplicate_completion")

    def test_consumption_snapshot_not_mutable_or_planned_units(self):
        aid = self.attention("immutable-units", 999)
        self.movement(aid, "2026-09-01T09:59:59", 4)
        self.movement(aid, "2026-09-01T09:59:59", 2.5)
        self.movement(aid, "2026-09-01T09:59:59", 500, kind="RESERVA")
        self.event(aid)
        report = self.report()
        self.assertEqual(self.metric(report)["picked_units"], 6.5)
        self.assertEqual(report["completion_audit"][0]["quantity_source"], "stock_movements.CONSUMO")

    def test_old_consumption_excluded_after_revert_and_recompletion(self):
        aid = self.attention("reconsume", 3)
        self.movement(aid, "2026-09-01T10:00:00", 8)
        self.event(aid)
        self.event(aid, "2026-09-02T08:00:00", new="EN PICKING", old="POR GUIAR", kind="RETROCESO_ADMIN", actor="admin")
        self.movement(aid, "2026-09-02T10:00:00", 3)
        self.event(aid, "2026-09-02T10:00:00")
        self.assertEqual(self.metric(self.report(period="week"))["picked_units"], 3)

    def test_post_completion_audited_quantity_edit_reconstructed_without_movements(self):
        aid = self.attention("edited", 2)
        self.event(aid)
        self.event(aid, "2026-09-02T10:00:00", new="2", old="8", kind="CANTIDAD", field="picked_qty", actor="admin")
        self.assertEqual(self.metric(self.report())["picked_units"], 8)

    def test_same_second_consumption_reversal_and_recompletion(self):
        aid = self.attention("rapid-redo", 999)
        at = "2026-09-01T10:00:00"
        self.movement(aid, at, 8)
        self.event(aid, at)
        self.movement(aid, at, 8, kind="REVERSA_CONSUMO")
        self.event(aid, at, new="EN PICKING", old="POR GUIAR", kind="RETROCESO_ADMIN", actor="admin")
        self.movement(aid, at, 3)
        self.event(aid, at)
        self.assertEqual(self.metric(self.report())["picked_units"], 3)

    def test_compliance_thresholds_and_cap_use_both_indicators(self):
        for index in range(20):
            self.event(self.attention(f"target-{index}", 10))
        report = self.report()
        self.assertEqual((self.metric(report)["compliance_pct"], self.metric(report)["traffic_light"]), (100, "VERDE"))
        report = self.report(start="2026-09-01", end="2026-09-02")
        self.assertEqual((self.metric(report)["compliance_pct"], self.metric(report)["traffic_light"]), (50, "ROJO"))
        self.db.execute("UPDATE attention_lines SET picked_qty=7")
        self.assertEqual(self.metric(self.report())["traffic_light"], "AMARILLO")
        self.db.execute("UPDATE attention_lines SET picked_qty=9")
        self.assertEqual(self.metric(self.report())["traffic_light"], "AMARILLO")

    def test_adjacent_night_windows_do_not_double_count_boundary(self):
        self.order("boundary", "2026-09-01T16:00:00")
        report = self.report(start="2026-09-01", end="2026-09-02")
        self.assertEqual([row["total_ovs"] for row in report["cutoffs"]], [1, 0])
        self.assertEqual(report["cutoffs"][1]["carryover_ovs"], 1)

    def test_weekends_and_partial_weeks_and_inclusive_bounds(self):
        for ov, at in (("fri", "2026-09-04T23:59:59"), ("sat", "2026-09-05T10:00:00"), ("sun", "2026-09-06T10:00:00"), ("mon", "2026-09-07T00:00:00")):
            self.event(self.attention(ov), at)
        report = self.report(start="2026-09-04", end="2026-09-07")
        self.assertEqual((report["workdays"], self.metric(report)["completed_ovs"], self.metric(report)["target_ovs"]), (2, 2, 40))
        self.assertEqual([row["workdays"] for row in report["weekly_metrics"]], [1, 1])
        weekend = self.report(start="2026-09-05", end="2026-09-06")
        self.assertEqual(self.metric(weekend)["target_units"], 0)
        self.assertIsNone(self.metric(weekend)["compliance_pct"])
        self.assertEqual(weekend["completion_audit"][0]["exclusion_reason"], "weekend")

    def test_strict_validation_and_366_inclusive_limit(self):
        invalid = [dict(start="2026-2-01"), dict(end="2026-02-30"), dict(reference="invalid"),
                   dict(start="2026-01-01T00:00:00"), dict(start=""), dict(start=123), dict(period="month"),
                   dict(start="2026-09-02", end="2026-09-01"), dict(start="2024-01-01", end="2025-01-01"),
                   dict(start="0001-01-01")]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.report(**kwargs)
        report = self.report(start="2024-01-01", end="2024-12-31")
        self.assertEqual(len(report["cutoffs"]), 366)
        self.assertEqual(self.report(end="2026-09-02")["start"], "2026-09-02")

    def test_lima_default_today_not_latest_cutoff_and_utc_events(self):
        aid = self.attention("utc", 6)
        self.event(aid, "2026-09-02T04:59:59+00:00")
        with patch("backend.services.workload._now", return_value=datetime(2026, 9, 2, 3, tzinfo=timezone.utc)):
            report = workload_report(self.db)
        self.assertEqual(report["start"], "2026-09-01")
        self.assertEqual(self.metric(report)["picked_units"], 6)

    def test_night_exact_customer_variants_and_open_closed_boundaries(self):
        for ov, stamp, customer in (
            ("lower", "2026-08-31 16:00:00", "Triton Trading S.A."),
            ("inside", "2026-08-31 16:00:01", " TRITÓN  TRADING S. A. "),
            ("upper", "2026-09-01 16:00:00", "TRITON TRADING SA"),
            ("outside", "2026-09-01 16:00:01", "Triton Trading S.A."),
            ("oriente", "2026-09-01 10:00:00", "Triton Trading Oriente S.A."),
            ("soluciones", "2026-09-01 10:00:00", "Triton Soluciones S.A."),
            ("suffix", "2026-09-01 10:00:00", "Triton Trading S.A. Oriente"),
            ("missing", None, "Triton Trading S.A."),
            ("bad", "not a date", "Triton Trading S.A.")):
            self.order(ov, stamp, customer)
        cutoff = self.report()["cutoffs"][0]
        self.assertEqual({row["sap_ov"] for row in cutoff["orders"]["window"]}, {"inside", "upper"})
        self.assertEqual((cutoff["carryover_ovs"], cutoff["date_missing_ovs"], cutoff["after_window_ovs"]), (1, 2, 1))
        self.assertEqual(cutoff["cutoff_at"], "2026-09-01T16:00:00")

    def test_night_source_formats_and_offset_and_overwritten_cutoff(self):
        for ov, value in (("excel", str(datetime(2026, 9, 1, 15, 30))), ("text", "01/09/2026 15:30:00"),
                          ("date", "2026-09-01"), ("offset", "2026-09-01T21:00:00Z")):
            self.order(ov, value)
        before = self.report()["cutoffs"]
        self.db.execute("UPDATE orders SET source_cutoff_at='2026-09-10T16:00:00'")
        self.assertEqual(self.report()["cutoffs"], before)
        self.assertEqual(before[0]["total_ovs"], 4)

    def test_night_closed_sap_local_complete_and_carryover_distinct(self):
        self.order("sap", status="CERRADO SAP")
        self.order("local", status="POR GUIAR")
        aid = self.attention("local", 5)
        self.event(aid)
        self.order("old-pending", "2026-08-01T10:00:00")
        self.order("old-sap", "2026-08-01T10:00:00", status="CERRADO SAP")
        cutoff = self.report()["cutoffs"][0]
        self.assertEqual((cutoff["closed_sap_ovs"], cutoff["local_completed_ovs"], cutoff["pending_ovs"]), (1, 1, 1))
        self.assertEqual((cutoff["carryover_ovs"], cutoff["carryover_pending_ovs"]), (2, 1))

    def test_inactive_historical_and_unregistered_actor_not_lost(self):
        self.user("former", active=0, shift="NOCHE")
        self.user("inactive-idle", active=0)
        self.event(self.attention("former"), actor="former")
        self.event(self.attention("legacy-picker"), actor="legacy-picker")
        report = self.report()
        self.assertEqual(self.metric(report, "former")["shift"], "NOCHE")
        self.assertEqual(self.metric(report, "legacy-picker")["shift"], "SIN REGISTRO")
        self.assertNotIn("inactive-idle", {row["username"] for row in report["picker_metrics"]})

    def test_legacy_order_history_only_when_attention_unambiguous(self):
        aid = self.attention("legacy", 12)
        self.insert("history", sap_ov="legacy", event_type="ESTADO", field_name="app_status", old_value="EN PICKING",
                    new_value="PICKING FINALIZADO", username="admin", created_at="2026-09-01T10:00:00")
        self.insert("assignments", sap_ov="legacy", role="PICKER", new_user="alice", username="admin", created_at="2026-09-01T09:00:00")
        self.assertEqual(self.metric(self.report())["picked_units"], 12)
        self.event(aid, actor="bob")  # Native audit takes precedence; no duplicate.
        self.assertEqual(self.metric(self.report(), "bob")["picked_units"], 12)
        self.assertEqual(self.metric(self.report())["picked_units"], 0)
        self.attention("ambiguous", 9)
        self.attention("ambiguous", 9)
        self.insert("history", sap_ov="ambiguous", event_type="ESTADO", field_name="app_status", old_value="EN PICKING",
                    new_value="PICKING FINALIZADO", username="alice", created_at="2026-09-01T10:00:00")
        self.assertEqual(self.metric(self.report())["picked_units"], 0)

    def test_compatibility_presets_bounded_and_read_only_json_serializable(self):
        self.event(self.attention("very-old"), "2020-01-01T10:00:00")
        self.event(self.attention("recent"))
        self.db.commit()
        self.db.execute("PRAGMA query_only=ON")
        changes = self.db.total_changes
        factory = self.db.row_factory
        for period in ("day", "week", "weekdays", "all"):
            report = self.report(period=period)
            json.dumps(report, allow_nan=False)
            self.assertLessEqual(len(report["cutoffs"]), 366)
            self.assertEqual(self.metric(report)["completed_ovs"], 1)
        self.assertEqual(self.db.total_changes, changes)
        self.assertIs(self.db.row_factory, factory)
        self.assertFalse(self.db.in_transaction)
        self.db.row_factory = sqlite3.Row
        self.assertEqual(self.metric(self.report())["completed_ovs"], 1)


if __name__ == "__main__":
    unittest.main()
