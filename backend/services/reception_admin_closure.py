"""Explicit administrative closure without inventing physical or SAP evidence."""
import hashlib
import hmac
import json
import re

from backend.services import reception, reception_transfer
from backend.services.reception_closure import closure_check, reconcile_closure
from backend.services.reception_historical_cutoff import _snapshot, _line_has_work


CONDITION = 'CIERRE ADMINISTRATIVO'
RETIRED = 'REGISTRO DE PRUEBA RETIRADO'
EVENT = 'REGULARIZACION ADMINISTRATIVA'
REQUEST_FIELD = 'admin_closure_request'
ACTIONS = {'reconcile', 'retire_test', 'close_bl', 'close_attention'}


def _require_admin(role):
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede revisar y regularizar el cierre')


def _attention_id(value):
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if type(value) is not int or value <= 0:
        raise ValueError('Selecciona una atencion valida de esta BL')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def _digest(value):
    return hashlib.sha256(_json(value).encode('ascii')).hexdigest()


def _load(connection, shipment_id, attention_id):
    shipment = reception._get_reception_shipment(connection, shipment_id, '', 'ADMINISTRADOR')
    has_inventory = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory_lots'").fetchone() is not None
    state = _snapshot(connection, dict(shipment), has_inventory)
    selected = next((row for row in state['reception_attentions'] if row['id'] == attention_id), None)
    if attention_id is not None and selected is None:
        raise ValueError('La atencion no pertenece a esta BL; recarga el expediente')
    return state, selected


def _token(state, attention_id):
    # The durable request receipt contains this post-state digest. Exclude only
    # those receipts to avoid a circular hash; all operational audit stays bound.
    evidence = {**state, 'reception_history': [row for row in state['reception_history']
        if not (row['event_type'] == EVENT and row['field_name'] == REQUEST_FIELD)]}
    return _digest({'version': 1, 'attention_id': attention_id, 'evidence': evidence})


def _annulled(attention):
    return str(attention['condition_status'] or '').startswith('ANULADA')


def _intake_blocker(state):
    relevant = {str(state['shipment']['truck_guide'] or '').strip().casefold()}
    relevant.update(str(row['truck_guide'] or '').strip().casefold()
                    for row in state['reception_truck_bl_manifest'] if row['operational_active'])
    relevant.update(str(row['truck_guide'] or '').strip().casefold()
                    for row in state['reception_truck_package_scans'] if row['scan_status'] == 'ACTIVO')
    # Legacy links without a canonical replacement still represent intake.
    canonical = {str(row['truck_guide'] or '').strip().casefold()
                 for row in state['reception_truck_bl_manifest']}
    relevant.update(str(row['truck_guide'] or '').strip().casefold()
                    for row in state['reception_truck_manifest']
                    if str(row['truck_guide'] or '').strip().casefold() not in canonical)
    for truck in state['trucks']:
        if truck['guide'] not in relevant:
            continue
        headers = truck['headers']
        if len(headers) != 1 or headers[0]['guide_status'] in ('PENDIENTE', 'EN_CURSO', 'ZONA_RECEPCION'):
            return 'CAMION CON INGRESO SIN FINALIZAR'
        saved = any(str(row['truck_guide'] or '').strip().casefold() == truck['guide']
                    and float(row['received_packages'] or 0) > 0
                    for row in state['reception_truck_bl_arrivals'])
        if saved:
            continue
        if headers[0]['guide_status'] != 'CANCELADA' and any(
                row['scan_status'] == 'ACTIVO'
                and str(row['truck_guide'] or '').strip().casefold() == truck['guide']
                for row in state['reception_truck_package_scans']):
            return 'CAMION CON LECTURAS SIN LLEGADA GUARDADA'
    return None


def _retire_blocker(state):
    shipment = state['shipment']
    if state['reception_lines']:
        return 'LINEAS DOCUMENTALES EXISTENTES'
    if state['reception_accounting_refs'] or any(str(shipment[field] or '').strip()
                                               for field in ('ip_reference', 'fr_number', 'em_number')):
        return 'REFERENCIAS DOCUMENTALES O CONTABLES EXISTENTES'
    if state['inventory_lots']:
        return 'LOTES OPERATIVOS EXISTENTES'
    if float(shipment['received_packages'] or 0) != 0 or any(
            float(row['received_packages'] or 0) != 0
            for table in ('reception_receipts', 'reception_truck_bl_arrivals') for row in state[table]):
        return 'RECEPCION FISICA REGISTRADA'
    if any(row['scan_status'] != 'ANULADO' or not row['voided_at'] or not row['void_reason']
           for row in state['reception_truck_package_scans']):
        return 'LECTURAS OPERATIVAS EXISTENTES'
    if any(not _annulled(row) or row['app_status'] != 'CERRADO'
           for row in state['reception_attentions']):
        return 'ATENCIONES SIN ANULACION DE PRUEBA'
    if any(_line_has_work(row) or float(row['planned_qty'] or 0) != 0
           for row in state['reception_attention_lines']):
        return 'CONTEO OPERATIVO EXISTENTE'
    for truck in state['trucks']:
        if len(truck['headers']) != 1:
            return 'CAMION SIN PROCEDENCIA DE PRUEBA'
        header = truck['headers'][0]
        if (header['guide_status'] != 'CANCELADA' or not header['archived_at']
                or 'prueba' not in str(header['archive_reason'] or '').casefold()):
            return 'CAMION SIN PROCEDENCIA DE PRUEBA RETIRADA'
    # Temporary text can survive an annulled zero pilot. Only identified,
    # archived test trucks supply that provenance; quantities/checks still block.
    proven_pilot = bool(state['trucks'] and state['reception_attentions'])
    if (shipment['bultos_closed'] or shipment['transfer_assistant_checked']
            or (str(shipment['location_text'] or '').strip() and not proven_pilot)
            or state['reception_truck_bl_locations']
            or any(row['status'] == 'CONFIRMED' for row in state['reception_transfer_requests'])
            or any(row['transfer_assistant_checked'] or (str(row['location_text'] or '').strip() and not proven_pilot)
                   for row in state['reception_attentions'])
            or any(row['event_type'] == 'VALIDACION' for row in state['reception_history'])):
        return 'EVIDENCIA DE TRABAJO OPERATIVO'
    origin = next((row for row in reversed(state['reception_history'])
                   if row['field_name'] == 'app_status' and row['new_value'] == 'ARRIBADO'), None)
    if (not state['trucks'] and (shipment['completed_arrival_at']
            or (shipment['first_arrival_at'] and not (origin and origin['event_type'] == 'IMPORTACION EXCEL')))):
        return 'FECHAS DE RECEPCION FISICA SIN PROCEDENCIA DE PRUEBA'
    receipts = {row['id']: row for row in state['reception_receipts']}
    if any(not str(row['truck_guide'] or '').strip() for row in receipts.values()) or any(
            row['receipt_id'] not in receipts for row in state['reception_attentions']):
        return 'ANULACION SIN LLEGADA DE PRUEBA IDENTIFICADA'
    if shipment['app_status'] not in ('PROGRAMADO', 'ARRIBADO'):
        return 'ETAPA OPERATIVA POR REVISAR'
    return None


def _preview(connection, state, selected, attention_id):
    shipment = state['shipment']
    closed = 'LA BL YA ESTA CERRADA' if shipment['app_status'] == 'CERRADO' else None
    intake = _intake_blocker(state)
    eligible, ordinary_reason = closure_check(connection, shipment['id'], allow_documentary=True)
    reconcile_blocker = closed or intake or (None if eligible else ordinary_reason)
    retire_blocker = closed or intake or _retire_blocker(state)
    attention_blocker = closed or intake
    if not attention_blocker:
        if not selected:
            attention_blocker = 'SELECCIONA UNA ATENCION DE ESTA BL'
        elif _annulled(selected):
            attention_blocker = 'LA ATENCION ESTA ANULADA'
        elif selected['app_status'] == 'CERRADO':
            attention_blocker = 'LA ATENCION YA ESTA CERRADA'
        elif not any(row['id'] == selected['receipt_id'] and float(row['received_packages'] or 0) > 0
                     for row in state['reception_receipts']):
            attention_blocker = 'LA ATENCION NO TIENE UNA RECEPCION FISICA POSITIVA'
    open_attentions = [row for row in state['reception_attentions']
                       if not _annulled(row) and row['app_status'] != 'CERRADO']
    if selected:
        lines = [row for row in state['reception_attention_lines'] if row['attention_id'] == selected['id']]
    elif open_attentions:
        ids = {row['id'] for row in open_attentions}
        lines = [row for row in state['reception_attention_lines'] if row['attention_id'] in ids]
    else:
        lines = state['reception_lines']
    unread, pending = 0, 0
    for line in lines:
        expected = float(line['planned_qty'] if 'planned_qty' in line else line['expected_qty'] or 0)
        received = float(line['verified_qty'] if 'verified_qty' in line else line['received_qty'] or 0)
        unread += int((expected > 0 or received > 0) and not str(line['np_scanned_at'] or '').strip())
        pending += int(expected > received + 0.000000001)
    return {'id': shipment['id'], 'bl_awb': shipment['bl_awb'], 'attention_id': attention_id,
            'app_status': shipment['app_status'], 'condition_status': shipment['condition_status'],
            'token': _token(state, attention_id),
            'can_reconcile': reconcile_blocker is None, 'reconcile_blocker': reconcile_blocker,
            'reconcile_basis': ordinary_reason if reconcile_blocker is None else None,
            'can_retire_test': retire_blocker is None, 'retire_blocker': retire_blocker,
            'can_close_bl': not (closed or intake), 'close_bl_blocker': closed or intake,
            'can_close_attention': attention_blocker is None, 'attention_blocker': attention_blocker,
            'open_attention_count': len(open_attentions), 'unread_np_count': unread,
            'pending_np_count': pending, 'accounting_status': reception._accounting_status_for_shipment(
                connection, shipment['id'], shipment, include_unreceived_ips=True)}


def preview_closure(connection, shipment_id, username, role, attention_id=None):
    """Consistent admin-only read; never initialize samples or reception work."""
    _require_admin(role)
    attention_id = _attention_id(attention_id)
    connection.execute('SAVEPOINT reception_admin_preview')
    try:
        state, selected = _load(connection, shipment_id, attention_id)
        result = _preview(connection, state, selected, attention_id)
        connection.execute('RELEASE reception_admin_preview')
        return result
    except Exception:
        connection.execute('ROLLBACK TO reception_admin_preview')
        connection.execute('RELEASE reception_admin_preview')
        raise


def _validated_request(data, username):
    if not isinstance(data, dict):
        raise ValueError('Indica la regularizacion y su confirmacion')
    action = data.get('action')
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError('Selecciona una regularizacion valida')
    reason = data.get('reason')
    if (data.get('confirmed') is not True or not isinstance(reason, str)
            or not 8 <= len(reason.strip()) <= 500 or not isinstance(username, str) or not username.strip()):
        raise ValueError('Confirma e indica un motivo de 8 a 500 caracteres y un usuario')
    if action in ('close_bl', 'close_attention') and data.get('acknowledge_unverified') is not True:
        raise ValueError('Reconoce que el cierre administrativo no verifica FR/EM/SAP')
    token = data.get('token')
    if not isinstance(token, str) or re.fullmatch(r'[0-9a-f]{64}', token) is None:
        raise ValueError('Se requiere el token vigente de la vista previa')
    return {'action': action, 'attention_id': _attention_id(data.get('attention_id')),
            'reason': reason.strip(), 'username': username.strip(), 'confirmed': True,
            'bl_confirmation': data.get('bl_confirmation'), 'token': token,
            'acknowledge_unverified': data.get('acknowledge_unverified') is True}


def _change_status(connection, shipment_id, row, table, status, condition, username, reason):
    if row['app_status'] == status and row['condition_status'] == condition:
        return
    stamp = reception.reception_now()
    if table == 'reception_attentions':
        connection.execute('''UPDATE reception_attentions SET app_status=?,condition_status=?,
            completed_at=?,updated_at=? WHERE id=?''', (status, condition, stamp, stamp, row['id']))
        prefix = 'atencion:' + str(row['id']) + ':'
    else:
        # These migration flags prevent startup from filling zero NP quantities
        # on a closed legacy BL. They assert no scan, check or SAP completion.
        if status == 'CERRADO':
            connection.execute('''UPDATE reception_shipments SET physical_initialized=1,
                system_quantities_initialized=1 WHERE id=?''', (row['id'],))
        connection.execute('''UPDATE reception_shipments SET app_status=?,condition_status=?,
            updated_at=? WHERE id=?''', (status, condition, stamp, row['id']))
        prefix = ''
    for field, value in (('app_status', status), ('condition_status', condition)):
        reception._write_history(connection, shipment_id, EVENT, prefix + field,
                                 row[field], value, username, reason)


def _revoke(connection, state, attention_id, username, reason):
    requests = [row for row in state['reception_transfer_requests']
                if row['status'] not in ('REVOKED', 'CONFIRMED')
                and (attention_id is None or row['attention_id'] == attention_id)]
    for scope in sorted({row['attention_id'] for row in requests}):
        reception_transfer.revoke(connection, state['shipment']['id'], scope)
    for row in requests:
        reception._write_history(connection, state['shipment']['id'], EVENT,
            'transfer_request:' + str(row['id']), row['status'], 'REVOKED', username,
            reason + '; enlace revocado sin envio ni confirmacion SAP')


def _apply(connection, shipment_id, request):
    aid = request['attention_id']
    state, selected = _load(connection, shipment_id, aid)
    shipment = state['shipment']
    if request['bl_confirmation'] != shipment['bl_awb']:
        raise ValueError('Escribe la BL completa exacta para confirmar la regularizacion')
    current_token = _token(state, aid)
    request_hash = _digest(request)
    if not hmac.compare_digest(request['token'], current_token):
        for row in reversed(state['reception_history']):
            if row['event_type'] != EVENT or row['field_name'] != REQUEST_FIELD:
                continue
            receipt = json.loads(row['new_value'])
            if receipt['request_hash'] == request_hash and hmac.compare_digest(receipt['post_token'], current_token):
                return {**receipt['result'], 'unchanged': True}
        raise ValueError('La BL cambio; revisa la vista previa y confirma con el token vigente')
    preview = _preview(connection, state, selected, aid)
    action = request['action']
    blocker_key = {'reconcile': 'reconcile_blocker', 'retire_test': 'retire_blocker',
                   'close_bl': 'close_bl_blocker', 'close_attention': 'attention_blocker'}[action]
    if preview[blocker_key]:
        raise ValueError('No se puede regularizar: ' + preview[blocker_key])
    username = request['username']
    reason = request['reason'] + '; FR/EM/SAP no verificados por esta regularizacion'
    if action == 'reconcile':
        reconcile_closure(connection, shipment_id, {**request, 'historical': True},
                          username, 'ADMINISTRADOR', return_detail=False)
        connection.execute('''UPDATE reception_shipments SET physical_initialized=1,
            system_quantities_initialized=1 WHERE id=?''', (shipment_id,))
    elif action == 'close_attention':
        _change_status(connection, shipment_id, selected, 'reception_attentions',
                       'CERRADO', CONDITION, username, reason)
        pending = [row for row in state['reception_attentions'] if row['id'] != aid
                   and not _annulled(row) and row['app_status'] != 'CERRADO']
        status, condition = ((pending[0]['app_status'], pending[0]['condition_status'])
                             if pending else ('PROGRAMADO', 'POR ARRIBAR'))
        _change_status(connection, shipment_id, shipment, 'reception_shipments',
                       status, condition, username, reason)
    else:
        if action == 'close_bl':
            for row in state['reception_attentions']:
                if not _annulled(row) and row['app_status'] != 'CERRADO':
                    _change_status(connection, shipment_id, row, 'reception_attentions',
                                   'CERRADO', CONDITION, username, reason)
        _change_status(connection, shipment_id, shipment, 'reception_shipments',
                       'CERRADO', RETIRED if action == 'retire_test' else CONDITION, username, reason)
    _revoke(connection, state, aid if action == 'close_attention' else None, username, reason)
    after, after_selected = _load(connection, shipment_id, aid)
    current = after_selected if action == 'close_attention' else after['shipment']
    result = {'id': shipment_id, 'attention_id': aid, 'app_status': current['app_status'],
              'condition_status': current['condition_status'], 'action': action, 'unchanged': False}
    audit = {'request_hash': request_hash, 'preview_token': request['token'],
             'post_token': _token(after, aid), 'fr_em_sap_verified': False, 'result': result}
    reception._write_history(connection, shipment_id, EVENT, REQUEST_FIELD,
                             _json({'shipment': shipment, 'attention': selected}),
                             _json(audit), username, reason)
    return result


def apply_closure(connection, shipment_id, data, username, role):
    """Reserve the writer before reading; caller commits the successful operation.

    An existing transaction is upgraded before our first read. The savepoint
    rolls back only this operation on failure, preserving the caller's work.
    """
    _require_admin(role)
    request = _validated_request(data, username)
    own_transaction = not connection.in_transaction
    if own_transaction:
        connection.execute('BEGIN IMMEDIATE')
    else:
        connection.execute('UPDATE reception_shipments SET id=id WHERE 0')
    connection.execute('SAVEPOINT reception_admin_closure')
    try:
        result = _apply(connection, shipment_id, request)
        connection.execute('RELEASE reception_admin_closure')
        return result
    except Exception:
        connection.execute('ROLLBACK TO reception_admin_closure')
        connection.execute('RELEASE reception_admin_closure')
        if own_transaction:
            connection.rollback()
        raise
