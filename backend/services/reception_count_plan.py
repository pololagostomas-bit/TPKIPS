"""Explicit inclusion of documentary orders imported after an arrival plan."""
import hashlib
import hmac
import json
import math

EDITABLE = {'ARRIBADO', 'REVISION SISTEMA', 'EM', 'UBICACION'}


def _state(connection, shipment_id, attention_id):
    attention = connection.execute('SELECT * FROM reception_attentions WHERE id=? AND shipment_id=?',
                                   (attention_id, shipment_id)).fetchone()
    rows = connection.execute('''SELECT l.id,l.np_code,l.description,l.expected_qty,l.received_qty,
        l.source_key,l.source_sheet,l.source_row,l.ip_reference,l.oc_number,l.ov_number
        FROM reception_lines l WHERE l.shipment_id=? AND l.expected_qty>0 AND l.received_qty=0
          AND COALESCE(l.np_scanned_at,'')='' AND COALESCE(l.np_unreceived_reason,'')=''
          AND COALESCE(l.count_location_saved,0)=0 AND COALESCE(l.final_location_confirmed,0)=0
          AND NOT EXISTS(SELECT 1 FROM reception_attention_lines al WHERE al.reception_line_id=l.id)
        ORDER BY l.id''', (shipment_id,)).fetchall()
    assigned = connection.execute('SELECT * FROM reception_attention_lines WHERE attention_id=? ORDER BY id',
                                  (attention_id,)).fetchall()
    shipment = connection.execute('SELECT app_status FROM reception_shipments WHERE id=?', (shipment_id,)).fetchone()
    state = {'shipment_id': shipment_id, 'attention': dict(attention) if attention else None,
             'shipment_status': shipment['app_status'] if shipment else None,
             'lines': [dict(row) for row in rows], 'assigned': [dict(row) for row in assigned]}
    token = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return state, token


def _editable(attention):
    return bool(attention and attention['app_status'] in EDITABLE
                and not str(attention['condition_status'] or '').startswith('ANULADA')
                and not attention['transfer_assistant_checked'])


def preview(connection, shipment_id, attention_id, role):
    if attention_id is None:
        return {'lines': [], 'can_include': False}
    state, token = _state(connection, shipment_id, attention_id)
    attention = state['attention']
    fields = ('id', 'np_code', 'description', 'expected_qty')
    result = {'lines': [{key: row[key] for key in fields} for row in state['lines']],
              'can_include': role == 'ADMINISTRADOR' and _editable(attention) and state['shipment_status'] != 'CERRADO',
              'reopens_count': bool(attention and attention['app_status'] in {'EM', 'UBICACION'})}
    if role == 'ADMINISTRADOR':
        result['state_token'] = token
    return result


def _reopen_count(connection, shipment_id, attention, username, reason):
    from backend.services import reception, reception_transfer
    stamp = reception.reception_now()
    reception_transfer.revoke(connection, shipment_id, attention['id'])
    connection.execute('''UPDATE reception_attentions SET app_status='REVISION SISTEMA',
        condition_status='EN PROCESO',system_quantities_initialized=1,
        transfer_assistant_checked=0,completed_at=NULL,updated_at=? WHERE id=?''', (stamp, attention['id']))
    connection.execute('''UPDATE reception_shipments SET app_status='REVISION SISTEMA',
        condition_status='EN PROCESO',updated_at=? WHERE id=?''', (stamp, shipment_id))
    # Only the selected arrival reopens. Other arrivals' validation/read evidence survives.
    reception._write_history(connection, shipment_id, 'RETROCESO_ADMIN', 'app_status',
        attention['app_status'], 'REVISION SISTEMA', username, reason)


def include_lines(connection, shipment_id, data, username, role):
    from backend.services import reception
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede incorporar NP a una entrega.')
    attention_id, ids = data.get('attention_id'), data.get('line_ids')
    reason = str(data.get('reason') or '').strip()
    if (type(attention_id) is not int or attention_id <= 0 or not isinstance(ids, list)
            or not 1 <= len(ids) <= 200 or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != len(ids) or data.get('confirmed') is not True
            or not 8 <= len(reason) <= 500 or not isinstance(data.get('state_token'), str)
            or len(data['state_token']) != 64 or any(c not in '0123456789abcdef' for c in data['state_token'])):
        raise ValueError('Selecciona los NP, confirma la entrega e indica un motivo de al menos 8 caracteres.')
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    shipment = reception._get_reception_shipment(connection, shipment_id, username, role)
    state, token = _state(connection, shipment_id, attention_id)
    attention = state['attention']
    if not _editable(attention):
        raise PermissionError('Reabre Inicio de conteo para incorporar NP; no se modifica una entrega cerrada, anulada o validada.')
    if shipment['app_status'] == 'CERRADO':
        raise PermissionError('Reabre la BL antes de modificar su plan de conteo.')
    if not hmac.compare_digest(data['state_token'], token):
        raise ValueError('El corte o la entrega cambiaron. Actualiza la BL y revisa los NP pendientes.')
    available = {row['id']: row for row in state['lines']}
    if not set(ids) <= available.keys():
        raise ValueError('Un NP ya fue asignado o no pertenece al plan pendiente de esta BL.')
    for line_id in ids:
        quantity = float(available[line_id]['expected_qty'])
        if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
            raise ValueError('La cantidad del NP debe ser un entero positivo en el corte de Importaciones.')
    connection.execute('SAVEPOINT include_count_lines')
    try:
        for line_id in ids:
            line = available[line_id]
            connection.execute('''INSERT INTO reception_attention_lines
                (attention_id,reception_line_id,planned_qty,verified_qty,np_quantity_saved)
                VALUES(?,?,?,0,0)''', (attention_id, line_id, line['expected_qty']))
            reception._write_history(connection, shipment_id, 'PLAN CONTEO',
                f'atencion:{attention_id}:linea:{line_id}', 'Sin asignar',
                json.dumps({'line_id': line_id, 'planned_qty': line['expected_qty'],
                            'verified_qty': 0, 'source_key': line['source_key']}, ensure_ascii=True),
                username, reason)
        if attention['app_status'] in {'EM', 'UBICACION'}:
            _reopen_count(connection, shipment_id, attention, username, reason)
        result = reception.reception_detail(connection, shipment_id, role, username, attention_id)
        connection.execute('RELEASE SAVEPOINT include_count_lines')
        return result
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT include_count_lines')
        connection.execute('RELEASE SAVEPOINT include_count_lines')
        raise
