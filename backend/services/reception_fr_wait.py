"""Observed FR waiting intervals in the existing audit log; reads never write."""
from datetime import datetime, timedelta, timezone

EVENT = 'DOCUMENTACION'
FIELD = 'fr_wait'
MISSING = {'PENDIENTE CONTABILIDAD', 'PENDIENTE FR'}
WORK_STAGES = {'EM', 'UBICACION', 'VALIDACION', 'SOLICITUD TRANSFERENCIA'}


def observe(connection, shipment_id, username, *, status=None, allow_start=None):
    from backend.services import reception
    shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?', (shipment_id,)).fetchone()
    if not shipment:
        return
    if allow_start is None:
        allow_start = shipment['app_status'] in WORK_STAGES
    last = connection.execute('''SELECT new_value FROM reception_history
        WHERE shipment_id=? AND event_type=? AND field_name=? ORDER BY id DESC LIMIT 1''',
        (shipment_id, EVENT, FIELD)).fetchone()
    opened = bool(last and last['new_value'] == '1')
    if not opened and not allow_start:
        return
    status = status or reception._accounting_status_for_shipment(connection, shipment_id, shipment)
    if status == 'CONFLICTO IP':
        # A conflict is a separate debt. Its presence does not prove FR is absent.
        clean = {**dict(shipment), 'accounting_conflict_count': 0}
        status = reception._accounting_status_for_shipment(connection, shipment_id, clean)
    missing = status in MISSING
    if missing and not opened and allow_start:
        reception._write_history(connection, shipment_id, EVENT, FIELD, 0, 1, username,
            'Primera deteccion de FR pendiente durante trabajo fisico; sin retroceder fechas')
    elif not missing and opened:
        reception._write_history(connection, shipment_id, EVENT, FIELD, 1, 0, username,
            'FR disponible para las IP recibidas; espera documental regularizada')


def _date(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo:
            result = result.astimezone(timezone(timedelta(hours=-5))).replace(tzinfo=None)
        return result
    except (TypeError, ValueError):
        return None


def summaries(connection, shipment_id=None, *, now=None):
    from backend.services import reception
    current = _date(now or reception.reception_now())
    sql = '''SELECT shipment_id,new_value,created_at FROM reception_history
        WHERE event_type=? AND field_name=?'''
    params = [EVENT, FIELD]
    if shipment_id is not None:
        sql += ' AND shipment_id=?'
        params.append(shipment_id)
    sql += ' ORDER BY id'
    states = {}
    for row in connection.execute(sql, params):
        stamp = _date(row['created_at'])
        if stamp is None:
            continue
        state = states.setdefault(int(row['shipment_id']), {'since': None, 'seconds': 0.0})
        if row['new_value'] == '1' and state['since'] is None:
            state['since'] = stamp
        elif row['new_value'] == '0' and state['since'] is not None:
            state['seconds'] += max(0, (stamp-state['since']).total_seconds())
            state['since'] = None
    result = {}
    for sid, state in states.items():
        since = state['since']
        seconds = state['seconds'] + (max(0, (current-since).total_seconds()) if since and current else 0)
        hours = round(seconds/3600, 2)
        note = (f'Pendiente de FR desde {since.isoformat(timespec="seconds")}; ' if since else 'FR regularizada; ')
        note += f'espera documental registrada: {hours:.2f} h.'
        result[sid] = {'pending': since is not None, 'since': since.isoformat(timespec='seconds') if since else None,
                       'hours': hours, 'note': note}
    return result
