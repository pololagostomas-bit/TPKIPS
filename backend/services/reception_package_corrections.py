"""Audited physical-package regularization, separate from NP count work."""
import hashlib
import json
import math

from backend.services import dhl_tracking as dhl, reception


def _context(connection, shipment_id, attention_id=None, truck_guide=None):
    shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?', (shipment_id,)).fetchone()
    if not shipment:
        raise ValueError('No existe la BL seleccionada')
    attention = None
    receipt = None
    guide = str(truck_guide or '').strip()
    if attention_id is not None:
        attention = reception._active_reception_attention(connection, shipment_id, attention_id)
        receipt = connection.execute('SELECT * FROM reception_receipts WHERE id=? AND shipment_id=?',
                                     (attention['receipt_id'], shipment_id)).fetchone()
        if not receipt:
            raise ValueError('Esta atencion no tiene una llegada fisica que regularizar')
        own_guide = str(receipt['truck_guide'] or '').strip()
        if guide and guide.casefold() != own_guide.casefold():
            raise ValueError('La atencion no corresponde al camion seleccionado')
        guide = own_guide
    elif guide:
        receipt = connection.execute('''SELECT * FROM reception_receipts WHERE shipment_id=?
            AND lower(COALESCE(truck_guide,''))=lower(?) ORDER BY sequence_no DESC LIMIT 1''',
            (shipment_id, guide)).fetchone()
        if receipt:
            attention = connection.execute('SELECT * FROM reception_attentions WHERE receipt_id=?',
                                            (receipt['id'],)).fetchone()
        elif not connection.execute('''SELECT 1 FROM reception_truck_bl_manifest
            WHERE shipment_id=? AND lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1''',
            (shipment_id, guide)).fetchone():
            raise ValueError('La BL no pertenece a este camion')
    else:
        raise ValueError('Selecciona una llegada o un camion de esta BL')
    header = reception._truck_guide_header(connection, guide, create_if_missing=False) if guide else None
    scans = connection.execute('''SELECT * FROM reception_truck_package_scans WHERE shipment_id=?
        AND lower(truck_guide)=lower(?) ORDER BY id''', (shipment_id, guide)).fetchall() if guide else []
    arrival = connection.execute('''SELECT * FROM reception_truck_bl_arrivals WHERE shipment_id=?
        AND lower(truck_guide)=lower(?)''', (shipment_id, guide)).fetchone() if guide else None
    lines = connection.execute('SELECT * FROM reception_attention_lines WHERE attention_id=? ORDER BY id',
                                (attention['id'],)).fetchall() if attention else []
    revision = connection.execute('SELECT COALESCE(MAX(id),0) FROM reception_history WHERE shipment_id=?',
                                   (shipment_id,)).fetchone()[0]
    state = {'shipment': dict(shipment), 'attention': dict(attention) if attention else None,
             'receipt': dict(receipt) if receipt else None, 'arrival': dict(arrival) if arrival else None,
             'header': dict(header) if header else None, 'scans': [dict(row) for row in scans],
             'lines': [dict(row) for row in lines], 'revision': revision}
    state['locations'] = [dict(row) for row in connection.execute(
        'SELECT * FROM reception_truck_bl_locations WHERE arrival_id=? ORDER BY id',
        (arrival['id'],))] if arrival else []
    token = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return shipment, attention, receipt, guide, header, scans, arrival, lines, state, token


def review_packages(connection, shipment_id, role, attention_id=None, truck_guide=None):
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede revisar los codigos de los bultos')
    shipment, attention, receipt, guide, header, scans, arrival, lines, state, token = _context(
        connection, shipment_id, attention_id, truck_guide)
    active = [row for row in scans if row['scan_status'] == 'ACTIVO']
    tracking = dhl.shipment_status(connection, shipment_id, role=role)
    return {'shipment_id': shipment_id, 'bl_awb': shipment['bl_awb'], 'truck_guide': guide,
            'attention_id': attention['id'] if attention else None, 'token': token,
            'received_this_arrival': float(receipt['received_packages'] or 0) if receipt else len(active),
            'received_confirmed': float(shipment['received_packages'] or 0),
            'expected_total': tracking.get('total_pieces'), 'pending_count': tracking.get('pending_arrival_pieces'),
            'pending_codes': tracking.get('pending_piece_ids', []),
            'items': [{'id': row['id'], 'code': row['package_code'], 'scanned_by': row['scanned_by'],
                       'scanned_at': row['scanned_at']} for row in active],
            'can_adjust_receipt': bool(receipt and not active),
            'attention_status': attention['app_status'] if attention else None,
            'guide_status': header['guide_status'] if header else None}


def correct_package(connection, shipment_id, data, username, role):
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede regularizar bultos')
    reason = str(data.get('reason') or '').strip()
    if data.get('confirmed') is not True or not 8 <= len(reason) <= 500:
        raise ValueError('Confirma la correccion e indica un motivo de 8 a 500 caracteres')
    action = data.get('action')
    if action not in {'remove', 'replace', 'receipt_quantity'}:
        raise ValueError('Selecciona una correccion de bulto valida')
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    shipment, attention, receipt, guide, header, scans, arrival, lines, state, token = _context(
        connection, shipment_id, data.get('attention_id'), data.get('truck_guide'))
    if data.get('token') != token:
        raise ValueError('La recepcion cambio; recarga los bultos antes de corregir')
    if (attention and attention['app_status'] != 'ARRIBADO') or any(
            float(line['verified_qty'] or 0) > 0 or line['np_scanned_at'] for line in lines):
        raise PermissionError('Reabre esta atencion a Zona de recepcion antes de regularizar sus bultos')
    if not receipt and (not header or header['guide_status'] not in {'PENDIENTE', 'EN_CURSO'}):
        raise PermissionError('Reabre la llegada del camion antes de regularizar sus bultos')
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='inventory_lots'").fetchone() and connection.execute(
            'SELECT 1 FROM inventory_lots WHERE reception_shipment_id=? LIMIT 1', (shipment_id,)).fetchone():
        raise PermissionError('Esta BL tiene lotes; regulariza su trazabilidad antes de cambiar sus bultos')
    active = [row for row in scans if row['scan_status'] == 'ACTIVO']
    selected = next((row for row in active if type(data.get('scan_id')) is int and row['id'] == data['scan_id']), None)
    replacement = None
    if action == 'receipt_quantity':
        if not receipt or active:
            raise ValueError('Con lecturas unicas, corrige cada bulto; no su cantidad agregada')
        value = data.get('received_packages')
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError('Ingresa una cantidad entera de bultos') from None
        if isinstance(value, bool) or not math.isfinite(amount) or not amount.is_integer() or not 0 <= amount <= 100000:
            raise ValueError('Ingresa una cantidad entera de bultos')
    else:
        if not selected:
            raise ValueError('El bulto no pertenece a las lecturas activas de esta llegada')
        if receipt and float(receipt['received_packages'] or 0) != len(active):
            raise ValueError('El recibo y las lecturas no coinciden; revisa primero su historial')
        amount = len(active) - int(action == 'remove')
        if action == 'replace':
            raw, normalized = reception._normalize_scan_code(data.get('package_code'), 'codigo unico de bulto')
            normalized = dhl.piece_code(normalized)
            if reception._package_scan_for_code(connection, normalized):
                raise ValueError('Este codigo ya esta registrado; no se puede duplicar un bulto')
            dhl.verify_piece(connection, shipment_id, normalized)
            replacement = raw, normalized
    old_amount = float(receipt['received_packages'] or 0) if receipt else len(active)
    if receipt and amount != old_amount:
        backed_total = connection.execute('SELECT COALESCE(SUM(received_packages),0) FROM reception_receipts WHERE shipment_id=?',
                                          (shipment_id,)).fetchone()[0]
        if abs(float(shipment['received_packages'] or 0) - backed_total) > 1e-9:
            raise ValueError('La BL conserva cantidades sin recibo; revisa su historial antes de regularizar')
    connection.execute('SAVEPOINT package_correction')
    try:
        timestamp = reception.reception_now()
        if selected:
            connection.execute('''UPDATE reception_truck_package_scans SET scan_status='ANULADO',
                voided_by=?,voided_at=?,void_reason=? WHERE id=?''',
                (username, timestamp, 'CORRECCION ADMIN BULTO: ' + reason, selected['id']))
        if replacement:
            connection.execute('''INSERT INTO reception_truck_package_scans
                (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
                VALUES (?,?,?,?,?,?)''', (guide, shipment_id, *replacement, username, timestamp))
        if receipt and amount != old_amount:
            connection.execute('UPDATE reception_receipts SET received_packages=?,location_text=?,username=? WHERE id=?',
                               (amount, '', username, receipt['id']))
            if arrival:
                connection.execute('UPDATE reception_truck_bl_arrivals SET received_packages=? WHERE id=?', (amount, arrival['id']))
                connection.execute('DELETE FROM reception_truck_bl_locations WHERE arrival_id=?', (arrival['id'],))
            if attention:
                connection.execute('UPDATE reception_attentions SET location_text=NULL,updated_at=? WHERE id=?',
                                   (timestamp, attention['id']))
                if amount == 0:
                    connection.execute('''UPDATE reception_attentions SET app_status='CERRADO',
                        condition_status='ANULADA POR CORRECCION BULTO',completed_at=? WHERE id=?''',
                        (timestamp, attention['id']))
                    connection.execute('UPDATE reception_attention_lines SET planned_qty=0,verified_qty=0 WHERE attention_id=?',
                                       (attention['id'],))
            total = connection.execute('SELECT COALESCE(SUM(received_packages),0) FROM reception_receipts WHERE shipment_id=?',
                                       (shipment_id,)).fetchone()[0]
            first_physical = connection.execute('SELECT MIN(received_at) FROM reception_receipts WHERE shipment_id=? AND received_packages>0',
                                                 (shipment_id,)).fetchone()[0]
            primary = reception._active_reception_attention(connection, shipment_id)
            connection.execute('''UPDATE reception_shipments SET received_packages=?,app_status=?,
                condition_status=?,first_arrival_at=?,
                completed_arrival_at=CASE WHEN expected_packages>0 AND ?>=expected_packages THEN completed_arrival_at ELSE NULL END,
                bultos_closed=CASE WHEN ?=0 THEN 0 ELSE bultos_closed END,updated_at=? WHERE id=?''',
                (total, primary['app_status'] if primary else 'PROGRAMADO',
                 primary['condition_status'] if primary else 'POR ARRIBAR', first_physical, total, total, timestamp, shipment_id))
        if guide and header and not header['archived_at']:
            connection.execute('''UPDATE reception_truck_bl_manifest SET planned_packages=?,updated_at=?
                WHERE shipment_id=? AND lower(truck_guide)=lower(?)''', (amount, timestamp, shipment_id, guide))
            connection.execute('''UPDATE reception_truck_guides SET planned_packages=(SELECT COALESCE(SUM(planned_packages),0)
                FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND COALESCE(operational_active,1)=1),
                updated_at=? WHERE lower(guide_code)=lower(?)''', (guide, timestamp, guide))
            if receipt and amount != old_amount:
                total = connection.execute('SELECT COALESCE(SUM(received_packages),0) FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?)', (guide,)).fetchone()[0]
                connection.execute('''UPDATE reception_truck_guides SET guide_status=?,count_enabled_at=NULL,
                    count_enabled_by=NULL WHERE lower(guide_code)=lower(?)''',
                    ('ZONA_RECEPCION' if total > 0 else 'CERRADA_SIN_BULTOS', guide))
                connection.execute('UPDATE reception_truck_arrivals SET received_packages=?,updated_at=? WHERE lower(truck_guide)=lower(?)',
                                   (total, timestamp, guide))
        after = _context(connection, shipment_id, attention['id'] if attention else None, guide)[8]
        reception._write_history(connection, shipment_id, 'CORRECCION BULTO ADMIN',
            'paquete:' + str(selected['id']) if selected else 'recibo:' + str(receipt['id']),
            json.dumps(state, sort_keys=True, default=str), json.dumps(after, sort_keys=True, default=str), username, reason)
        result = review_packages(connection, shipment_id, role, attention['id'] if attention else None, guide)
        connection.execute('RELEASE package_correction')
        return result
    except Exception:
        connection.execute('ROLLBACK TO package_correction')
        connection.execute('RELEASE package_correction')
        raise
