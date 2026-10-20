"""Explicit owner-directed historical closure, independent of FR/EM verification."""
import hashlib
import hmac
import json
from collections import Counter

from backend.services import reception
from backend.services.reception_closure import closure_check
from backend.services.workload import _date, _timestamp


DEFAULT_CUTOFF = '2026-07-31'
CONDITION = 'HISTORICO POR CORTE'
EVENT = 'CIERRE HISTORICO POR CORTE'
BASIS = 'OWNER_INSTRUCTION_ASSUMPTION'


def _require_admin(role):
    reception.require_reception_access(role)
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede revisar y aplicar el corte historico')


def _cutoff(value):
    day = _date(value, 'Corte historico')
    if day.isoformat() > DEFAULT_CUTOFF:
        raise ValueError('El corte historico no puede ser posterior a ' + DEFAULT_CUTOFF)
    return day


def _rows(connection, table, where, params):
    # Identifiers and predicates are internal literals, never request values.
    return [dict(row) for row in connection.execute(
        f'SELECT * FROM {table} WHERE {where} ORDER BY rowid', params)]


def _snapshot(connection, shipment, has_inventory):
    sid = shipment['id']
    result = {'shipment': shipment}
    for table in ('reception_lines', 'reception_receipts', 'reception_attentions',
                  'reception_truck_bl_arrivals', 'reception_truck_package_scans',
                  'reception_truck_bl_manifest', 'reception_truck_manifest',
                  'reception_accounting_refs', 'reception_history',
                  'reception_transfer_requests'):
        result[table] = _rows(connection, table, 'shipment_id=?', (sid,))
    result['reception_attention_lines'] = _rows(connection, 'reception_attention_lines',
        'attention_id IN (SELECT id FROM reception_attentions WHERE shipment_id=?)', (sid,))
    result['reception_accounting_ems'] = _rows(connection, 'reception_accounting_ems',
        'accounting_ref_id IN (SELECT id FROM reception_accounting_refs WHERE shipment_id=?)', (sid,))
    result['reception_truck_bl_locations'] = _rows(connection, 'reception_truck_bl_locations',
        'arrival_id IN (SELECT id FROM reception_truck_bl_arrivals WHERE shipment_id=?)', (sid,))
    result['inventory_lots'] = (_rows(connection, 'inventory_lots',
        '''reception_shipment_id=? OR reception_line_id IN
           (SELECT id FROM reception_lines WHERE shipment_id=?) OR lower(trim(bl_awb))=lower(?)''',
        (sid, sid, shipment['bl_awb'])) if has_inventory else [])
    guides = {str(shipment['truck_guide'] or '').strip().casefold()}
    for table in ('reception_receipts', 'reception_truck_bl_arrivals',
                  'reception_truck_package_scans', 'reception_truck_bl_manifest',
                  'reception_truck_manifest'):
        guides.update(str(row['truck_guide'] or '').strip().casefold() for row in result[table])
    guides.discard('')
    result['trucks'] = []
    for guide in sorted(guides):
        result['trucks'].append({
            'guide': guide,
            'headers': _rows(connection, 'reception_truck_guides', 'lower(guide_code)=?', (guide,)),
            'arrivals': _rows(connection, 'reception_truck_arrivals', 'lower(truck_guide)=?', (guide,)),
            'locations': _rows(connection, 'reception_truck_locations', 'lower(truck_guide)=?', (guide,)),
        })
    return result


def _nonzero(value):
    try:
        return float(value or 0) != 0
    except (TypeError, ValueError, OverflowError):
        return True


def _line_has_work(line):
    return any(_nonzero(line.get(field)) for field in (
        'received_qty', 'verified_qty', 'count_location_saved', 'count_location_manual',
        'final_location_confirmed', 'validation_sap_checked',
        'validation_comment_checked')) or any(str(line.get(field) or '').strip() for field in (
            'np_scanned_at', 'np_scanned_by', 'np_unreceived_reason', 'final_location',
            'validation_comment'))


def _work_exclusion(connection, snapshot):
    shipment = snapshot['shipment']
    attentions = snapshot['reception_attentions']
    if any(row['app_status'] != 'CERRADO' for row in attentions):
        return 'PHYSICAL_WORK'
    if shipment['app_status'] not in ('PROGRAMADO', 'ARRIBADO'):
        return 'PHYSICAL_WORK'
    if snapshot['inventory_lots']:
        return 'INVENTORY'
    if any(row['status'] not in ('REVOKED', 'CONFIRMED')
           for row in snapshot['reception_transfer_requests']):
        return 'TRANSFER_WORK'
    for truck in snapshot['trucks']:
        if len(truck['headers']) != 1:
            return 'TRUCK_WORK'
        header = truck['headers'][0]
        if header['guide_status'] != 'CANCELADA' or not header['archived_at']:
            return 'TRUCK_WORK'
    # An inactive manifest without an identified, archived truck is unproven too.
    if any(not str(row['truck_guide'] or '').strip() for table in (
            'reception_truck_bl_manifest', 'reception_truck_manifest') for row in snapshot[table]):
        return 'TRUCK_WORK'
    if any(row['scan_status'] != 'ANULADO' or not row['voided_at'] or not row['void_reason']
           for row in snapshot['reception_truck_package_scans']):
        return 'PHYSICAL_WORK'
    origins = [row for row in snapshot['reception_history']
               if row['field_name'] == 'app_status' and row['new_value'] == 'ARRIBADO']
    excel_arrival = bool(origins and origins[-1]['event_type'] == 'IMPORTACION EXCEL')
    # Viewing a detail initializes the sample and location checkbox. Only its
    # explicit saved audit proves an operator validated that automatic sample.
    saved_validation = any(row['event_type'] == 'VALIDACION'
        and str(row['field_name']).startswith('linea:')
        and str(row['field_name']).endswith(':muestra') for row in snapshot['reception_history'])
    has_work = (
        bool(attentions or snapshot['reception_receipts'])
        or saved_validation
        or any(_nonzero(row['received_packages']) for row in snapshot['reception_truck_bl_arrivals'])
        or any(_line_has_work(row) for table in ('reception_lines', 'reception_attention_lines')
               for row in snapshot[table])
        or any(_nonzero(shipment[field]) for field in (
            'received_packages', 'bultos_closed', 'transfer_assistant_checked'))
        or any(str(shipment[field] or '').strip() for field in (
            'location_text', 'completed_arrival_at'))
        or (bool(str(shipment['first_arrival_at'] or '').strip()) and not excel_arrival)
    )
    if has_work:
        # Existing closure proves all partials and documents complete. A date,
        # a zero receipt or an annulment by itself never supplies this proof.
        if not attentions or any(not row['completed_at'] for row in attentions):
            return 'PHYSICAL_WORK'
        if not closure_check(connection, shipment['id'], allow_documentary=True)[0]:
            return 'PHYSICAL_WORK'
    return None


def _preview(connection, cutoff):
    eligible, excluded, snapshots = [], [], []
    has_inventory = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory_lots'").fetchone() is not None
    for row in connection.execute('SELECT * FROM reception_shipments ORDER BY id').fetchall():
        shipment = dict(row)
        raw_date = shipment['scheduled_date']
        parsed = _timestamp(raw_date)
        item = {'id': shipment['id'], 'bl_awb': shipment['bl_awb'],
                'scheduled_date': raw_date, 'scheduled_day': parsed.date().isoformat() if parsed else None,
                'accounting_status': shipment['accounting_status']}
        reason = None
        if shipment['app_status'] == 'CERRADO':
            reason = 'ALREADY_CLOSED'
        elif not str(raw_date or '').strip():
            reason = 'UNKNOWN_DATE'
        elif parsed is None:
            reason = 'INVALID_DATE'
        elif parsed.date() > cutoff:
            reason = 'AFTER_CUTOFF'
        else:
            snapshot = _snapshot(connection, shipment, has_inventory)
            reason = _work_exclusion(connection, snapshot)
        if reason:
            excluded.append({**item, 'reason': reason})
        else:
            eligible.append(item)
            snapshots.append(snapshot)
    token = hashlib.sha256(json.dumps({
        'version': 1, 'basis': BASIS, 'cutoff': cutoff.isoformat(), 'eligible': snapshots,
    }, sort_keys=True, ensure_ascii=True).encode('ascii')).hexdigest()
    return {
        'cutoff': cutoff.isoformat(), 'date_field': 'scheduled_date',
        'basis': BASIS, 'fr_em_sap_verified': False,
        'counts': {'total': len(eligible) + len(excluded), 'eligible': len(eligible),
                   'excluded': len(excluded), 'by_reason': dict(Counter(row['reason'] for row in excluded))},
        'eligible': eligible, 'eligible_ids': [row['id'] for row in eligible],
        'excluded': excluded, 'excluded_ids': [row['id'] for row in excluded], 'token': token,
    }


def preview_historical_cutoff(connection, cutoff=DEFAULT_CUTOFF, *, role=None):
    """Read-only, consistent preview of the full eligible set; requires admin."""
    _require_admin(role)
    day = _cutoff(cutoff)
    connection.execute('SAVEPOINT reception_historical_preview')
    try:
        result = _preview(connection, day)
        connection.execute('RELEASE reception_historical_preview')
        return result
    except Exception:
        connection.execute('ROLLBACK TO reception_historical_preview')
        connection.execute('RELEASE reception_historical_preview')
        raise


def apply_historical_cutoff(connection, data, username, role):
    """Apply exactly the current preview atomically, preserving an outer transaction."""
    _require_admin(role)
    if not isinstance(data, dict):
        raise ValueError('Indica la confirmacion del corte historico')
    day = _cutoff(data.get('cutoff', DEFAULT_CUTOFF))
    reason = str(data.get('reason') or '').strip()
    username = str(username or '').strip()
    if data.get('confirmed') is not True or not 8 <= len(reason) <= 500 or not username:
        raise ValueError('Confirma el corte, indica un motivo de 8 a 500 caracteres y un usuario')
    token = data.get('token')
    if not isinstance(token, str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Se requiere el token vigente de la vista previa')
    connection.execute('SAVEPOINT reception_historical_cutoff')
    try:
        # Take SQLite's writer reservation before re-reading. No rows change;
        # concurrent writers cannot slip work between validation and closure.
        connection.execute('UPDATE reception_shipments SET id=id WHERE 0')
        preview = _preview(connection, day)
        if not hmac.compare_digest(token, preview['token']):
            raise ValueError('La vista previa cambio; revisa el corte y confirma con el token vigente')
        timestamp = reception.reception_now()
        audit_reason = ('Suposicion historica por instruccion del propietario; corte ' + day.isoformat()
                        + '; FR/EM/SAP no verificados por este corte. ' + reason)
        for item in preview['eligible']:
            sid = item['id']
            shipment = dict(connection.execute(
                'SELECT * FROM reception_shipments WHERE id=?', (sid,)).fetchone())
            previous = {field: shipment[field] for field in (
                'app_status', 'condition_status', 'physical_initialized', 'system_quantities_initialized')}
            # Preserve zero quantities on the existing startup migration path.
            connection.execute('''UPDATE reception_shipments SET app_status='CERRADO',
                condition_status=?,physical_initialized=1,system_quantities_initialized=1,
                updated_at=? WHERE id=?''', (CONDITION, timestamp, sid))
            audit = {'basis': BASIS, 'fr_em_sap_verified': False, 'cutoff': day.isoformat(),
                     'scheduled_date': item['scheduled_date'], 'scheduled_day': item['scheduled_day'],
                     'accounting_status': item['accounting_status'], 'preview_token': token}
            reception._write_history(connection, sid, EVENT, 'historical_cutoff',
                json.dumps(previous, sort_keys=True), json.dumps(audit, sort_keys=True), username, audit_reason)
            reception._write_history(connection, sid, EVENT, 'app_status',
                                     shipment['app_status'], 'CERRADO', username, audit_reason)
            reception._write_history(connection, sid, EVENT, 'condition_status',
                                     shipment['condition_status'], CONDITION, username, audit_reason)
        connection.execute('RELEASE reception_historical_cutoff')
        return {'cutoff': day.isoformat(), 'token': token, 'applied_ids': preview['eligible_ids'],
                'applied_count': len(preview['eligible_ids']), 'counts': preview['counts']}
    except Exception:
        connection.execute('ROLLBACK TO reception_historical_cutoff')
        connection.execute('RELEASE reception_historical_cutoff')
        raise
