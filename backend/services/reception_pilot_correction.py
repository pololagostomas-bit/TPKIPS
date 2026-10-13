"""Explicit correction of retired pilot receipts, never current truck work."""
import hashlib
import json

from backend.services import reception


def _rows(connection, table, clause, shipment_id):
    return [dict(row) for row in connection.execute(
        f"SELECT * FROM {table} WHERE {clause} ORDER BY id", (shipment_id,))]


def _snapshot(connection, shipment_id):
    shipment = connection.execute(
        'SELECT * FROM reception_shipments WHERE id=?', (shipment_id,)).fetchone()
    if not shipment:
        raise ValueError('No existe la BL seleccionada')
    result = {'shipment': dict(shipment)}
    for table in ('reception_receipts', 'reception_attentions', 'reception_lines',
                  'reception_truck_bl_arrivals', 'reception_truck_package_scans',
                  'reception_accounting_refs'):
        result[table] = _rows(connection, table, 'shipment_id=?', shipment_id)
    result['reception_attention_lines'] = _rows(connection, 'reception_attention_lines',
        'attention_id IN (SELECT id FROM reception_attentions WHERE shipment_id=?)', shipment_id)
    result['reception_truck_bl_locations'] = _rows(connection, 'reception_truck_bl_locations',
        'arrival_id IN (SELECT id FROM reception_truck_bl_arrivals WHERE shipment_id=?)', shipment_id)
    result['reception_accounting_ems'] = _rows(connection, 'reception_accounting_ems',
        'accounting_ref_id IN (SELECT id FROM reception_accounting_refs WHERE shipment_id=?)', shipment_id)
    return result


def _token(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def correction_check(connection, shipment_id):
    """Eligibility is evidence-based; a SCAN prefix alone is never a test."""
    shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?',
                                  (shipment_id,)).fetchone()
    if not shipment:
        raise ValueError('No existe la BL seleccionada')
    receipts = connection.execute('SELECT * FROM reception_receipts WHERE shipment_id=?',
                                  (shipment_id,)).fetchall()
    blocked = {'eligible': False}
    if not receipts or connection.execute('''SELECT 1 FROM reception_truck_bl_manifest
        WHERE shipment_id=? AND COALESCE(operational_active,1)=1 LIMIT 1''',
                                         (shipment_id,)).fetchone():
        return blocked
    guides = {str(r['truck_guide'] or '').strip() for r in receipts}
    if shipment['truck_guide']:
        guides.add(shipment['truck_guide'])
    for table in ('reception_truck_bl_arrivals', 'reception_truck_package_scans'):
        guides.update(r[0] for r in connection.execute(
            f'SELECT DISTINCT truck_guide FROM {table} WHERE shipment_id=?', (shipment_id,)))
    for guide in guides:
        row = reception._truck_guide_header(connection, guide, create_if_missing=False) if guide else None
        if not row or row['guide_status'] != 'CANCELADA' or not row['archived_at'] or (
                'prueba' not in str(row['archive_reason'] or '').casefold()):
            return blocked
    # Receipts without identified pilot provenance and downstream inventory
    # need separate investigation, not a shortcut around operational controls.
    if connection.execute('''SELECT 1 FROM reception_attentions a
        WHERE a.shipment_id=? AND a.receipt_id IS NULL LIMIT 1''', (shipment_id,)).fetchone():
        return blocked
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='inventory_lots'").fetchone():
        if connection.execute('SELECT 1 FROM inventory_lots WHERE reception_shipment_id=? LIMIT 1',
                              (shipment_id,)).fetchone():
            return blocked
    if not connection.execute('''SELECT 1 FROM reception_attentions WHERE shipment_id=?
        AND condition_status NOT LIKE 'ANULADA%' LIMIT 1''', (shipment_id,)).fetchone() and not (
            float(shipment['received_packages'] or 0) or any(float(r['received_packages'] or 0) for r in receipts)):
        return blocked
    complete = reception._accounting_status_for_shipment(
        connection, shipment_id, shipment, include_unreceived_ips=True) == 'EM REGISTRADA'
    return {'eligible': True, 'can_close_history': complete,
            'receipt_count': len(receipts), 'token': _token(_snapshot(connection, shipment_id))}


def correct_pilot_reception(connection, shipment_id, data, username, role):
    reception.require_reception_access(role)
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede corregir recepciones de prueba')
    action = data.get('action')
    reason = str(data.get('reason') or '').strip()
    if action not in {'pending_arrival', 'historical_closed'}:
        raise ValueError('Selecciona el resultado de la correccion')
    if data.get('confirmed') is not True or len(reason) < 8:
        raise ValueError('Confirma la correccion e indica un motivo de al menos 8 caracteres')
    connection.execute('SAVEPOINT pilot_correction')
    try:
        check = correction_check(connection, shipment_id)
        if not check['eligible']:
            raise ValueError('La BL no contiene solo recepciones de camiones de prueba retirados')
        snapshot = _snapshot(connection, shipment_id)
        shipment = snapshot['shipment']
        if str(data.get('bl_confirmation') or '').strip() != shipment['bl_awb']:
            raise ValueError('Escribe la BL completa para confirmar la correccion')
        if data.get('token') != check['token']:
            raise ValueError('La BL cambio desde que la abriste. Recarga y revisa antes de confirmar')
        if action == 'historical_closed' and not check['can_close_history']:
            raise ValueError('El cierre historico necesita FR y EM completas para todas las IP')
        timestamp = reception.reception_now()
        connection.execute('''UPDATE reception_receipts SET received_packages=0,location_text=''
            WHERE shipment_id=?''', (shipment_id,))
        connection.execute('''UPDATE reception_attentions SET app_status='CERRADO',
            condition_status='ANULADA PRUEBA RETIRADA',location_text='',
            system_quantities_initialized=0,transfer_assistant_checked=0,completed_at=?,updated_at=?
            WHERE shipment_id=?''', (timestamp, timestamp, shipment_id))
        connection.execute('''UPDATE reception_attention_lines SET planned_qty=0,verified_qty=0,
            final_location='',final_location_confirmed=0,count_location_saved=0,count_location_manual=0
            WHERE attention_id IN (SELECT id FROM reception_attentions WHERE shipment_id=?)''', (shipment_id,))
        connection.execute('''DELETE FROM reception_truck_bl_locations WHERE arrival_id IN
            (SELECT id FROM reception_truck_bl_arrivals WHERE shipment_id=?)''', (shipment_id,))
        connection.execute('DELETE FROM reception_truck_bl_arrivals WHERE shipment_id=?', (shipment_id,))
        connection.execute('''UPDATE reception_truck_package_scans SET scan_status='ANULADO',
            voided_by=?,voided_at=?,void_reason=? WHERE shipment_id=? AND scan_status='ACTIVO' ''',
                           (username, timestamp, reason, shipment_id))
        connection.execute('''UPDATE reception_lines SET received_qty=0,
            final_location='',final_location_confirmed=0,count_location_saved=0,count_location_manual=0,
            validation_sap_checked=0,validation_location_checked=0,validation_comment_checked=0
            WHERE shipment_id=?''', (shipment_id,))
        status = 'CERRADO' if action == 'historical_closed' else 'PROGRAMADO'
        condition = 'COMPLETADO' if status == 'CERRADO' else 'POR ARRIBAR'
        connection.execute('''UPDATE reception_shipments SET app_status=?,condition_status=?,
            received_packages=0,truck_guide=NULL,first_arrival_at=NULL,completed_arrival_at=NULL,
            physical_initialized=1,system_quantities_initialized=?,bultos_closed=0,location_text='',
            validation_sample_json=NULL,transfer_assistant_checked=0,updated_at=? WHERE id=?''',
                           (status, condition, int(status == 'CERRADO'), timestamp, shipment_id))
        reception._write_history(connection, shipment_id, 'CORRECCION PRUEBA', 'pilot_snapshot',
            json.dumps(snapshot, ensure_ascii=True, default=str), action, username, reason)
        reception._write_history(connection, shipment_id, 'CORRECCION PRUEBA', 'app_status',
            shipment['app_status'], status, username, reason)
        payload = reception.reception_detail(connection, shipment_id, role, username)
        connection.execute('RELEASE pilot_correction')
        return payload
    except Exception:
        connection.execute('ROLLBACK TO pilot_correction')
        connection.execute('RELEASE pilot_correction')
        raise
