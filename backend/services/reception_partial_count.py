"""Explicit partial count; unread orders remain available for a later arrival."""
from backend.services import reception
from backend.services.reception_np_progress import covered_orders, reconcile_covered_orders, prior_read_review

DEFERRED_REASON = 'No recibido en esta llegada; pendiente para otra llegada'


def continue_partial_count(connection, shipment_id, data, username, role):
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    shipment = reception._get_reception_shipment(connection, shipment_id, username, role)
    if data.get('confirmed') is not True:
        raise ValueError('Confirma que los NP pendientes no llegaron en esta atencion')
    ids = data.get('line_ids')
    if (not isinstance(ids,list) or len(ids)>10000
            or any(type(value) is not int or value<=0 for value in ids)
            or len(set(ids))!=len(ids)):
        raise ValueError('Selecciona nuevamente los NP pendientes de esta atencion')
    requested = set(ids)
    attention_id = data.get('attention_id')
    if type(attention_id) is not int or attention_id<=0:
        raise ValueError('Selecciona la atencion de llegada antes de continuar')
    attention = reception._location_context(connection,shipment,attention_id)
    if prior_read_review(connection,shipment_id,attention)['line_ids']:
        raise PermissionError('El administrador debe regularizar las cantidades antiguas de otra llegada')
    rows = connection.execute('''SELECT al.*, l.np_code
        FROM reception_attention_lines al JOIN reception_lines l ON l.id=al.reception_line_id
        WHERE al.attention_id=? AND (al.planned_qty>0 OR al.verified_qty>0)''',
        (attention_id,)).fetchall()
    covered = covered_orders(connection,shipment_id,attention)
    rows = [row for row in rows if row['reception_line_id'] not in covered]
    selected = [row for row in rows if row['reception_line_id'] in requested]
    deferred = [row for row in rows if row['np_unreceived_reason'] and float(row['verified_qty'] or 0)==0]
    unresolved = {row['reception_line_id'] for row in rows
                  if not row['np_scanned_at'] and not row['np_unreceived_reason'] and row['np_quantity_saved']!=2}
    positive_read = any((row['np_scanned_at'] or row['np_quantity_saved']==2) and float(row['verified_qty'] or 0)>0 for row in rows)
    existing_partial = not ids and deferred and not unresolved and positive_read
    if attention['app_status']=='EM' and (existing_partial or (ids and len(selected)==len(ids) and all(
            row['np_unreceived_reason']==DEFERRED_REASON and not row['np_scanned_at']
            and float(row['verified_qty'] or 0)==0 for row in selected))):
        return reception.reception_detail(connection,shipment_id,role,username,attention_id)
    if attention['app_status']!='REVISION SISTEMA':
        raise PermissionError('El conteo parcial solo se confirma en Inicio de conteo')
    if requested!=unresolved:
        raise ValueError('Las lecturas cambiaron; reabre el conteo y revisa los NP pendientes')
    if not ids and not deferred:
        raise ValueError('No hay NP pendientes para un conteo parcial')
    if not positive_read:
        if covered:
            raise ValueError('Esta llegada no tiene NP recibidos; el administrador puede cerrarla conservando el saldo pendiente')
        raise ValueError('Escanea al menos un NP recibido antes de continuar')
    # Roll back both the deferred rows and the stage if any FR/location check fails.
    connection.execute('SAVEPOINT reception_partial_count')
    try:
        reconcile_covered_orders(connection,shipment_id,attention,username)
        for row in selected:
            connection.execute('''UPDATE reception_attention_lines SET verified_qty=0,
                np_unreceived_reason=? WHERE id=?''',(DEFERRED_REASON,row['id']))
            connection.execute('UPDATE reception_lines SET blocked_reason=? WHERE id=?',
                               (DEFERRED_REASON,row['reception_line_id']))
            reception._write_history(connection,shipment_id,'CONTEO PARCIAL',
                f"linea:{row['reception_line_id']}:received_qty",row['verified_qty'],0,
                username,f'Atencion {attention_id}; '+DEFERRED_REASON)
        reception._sync_reception_line_totals(connection,shipment_id)
        result = reception.change_reception_status(connection,shipment_id,
            {'status':'EM','attention_id':attention_id},username,role)
        connection.execute('RELEASE SAVEPOINT reception_partial_count')
        return result
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT reception_partial_count')
        connection.execute('RELEASE SAVEPOINT reception_partial_count')
        raise
