"""Read evidence and deferred balances, independent of default quantities."""
import hashlib
import json


def deferred_balances(connection):
    from backend.services import reception_source_bl
    groups={}
    for row in connection.execute('''
        SELECT l.*
        FROM reception_lines l JOIN reception_shipments s ON s.id=l.shipment_id
        WHERE s.app_status<>'CERRADO' AND l.expected_qty>l.received_qty+0.000000001
          AND EXISTS (SELECT 1 FROM reception_attention_lines al
            JOIN reception_attentions a ON a.id=al.attention_id
            WHERE al.reception_line_id=l.id AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
              AND COALESCE(al.np_unreceived_reason,'')<>'' AND al.verified_qty=0)
          AND NOT EXISTS (SELECT 1 FROM reception_attention_lines al
            JOIN reception_attentions a ON a.id=al.attention_id
            WHERE al.reception_line_id=l.id AND a.app_status<>'CERRADO'
              AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
              AND COALESCE(al.np_unreceived_reason,'')='' AND al.planned_qty>al.verified_qty)
          AND NOT EXISTS (SELECT 1 FROM reception_receipts r
            WHERE r.shipment_id=l.shipment_id AND r.received_packages>0 AND NOT EXISTS
              (SELECT 1 FROM reception_attentions a WHERE a.receipt_id=r.id))
        '''):
        groups.setdefault(row['shipment_id'],[]).append(dict(row))
    result={}
    for shipment_id,lines in groups.items():
        shipment=connection.execute('SELECT bl_awb FROM reception_shipments WHERE id=?',(shipment_id,)).fetchone()
        states=reception_source_bl.flags(connection,dict(shipment),lines)
        codes={''.join(str(line['np_code']).upper().split()) for line in lines if line['np_code'] and states[line['id']]['source_bl_eligible']}
        if codes:result[shipment_id]=len(codes)
    return result


def add_progress(connection, payload, selected_attention):
    attention = connection.execute('SELECT * FROM reception_attentions WHERE id=? AND shipment_id=?',
        (selected_attention, payload['id'])).fetchone()
    covered = covered_orders(connection, payload['id'], attention)
    review = prior_read_review(connection, payload['id'], attention)
    source_excluded={line['id'] for line in payload['lines'] if line.get('source_bl_eligible') is False}
    review={**review,'line_ids':[line_id for line_id in review['line_ids'] if line_id not in source_excluded]}
    payload['np_prior_read_review'] = review
    rows = connection.execute('''SELECT al.reception_line_id, al.attention_id
        FROM reception_attention_lines al JOIN reception_attentions a ON a.id=al.attention_id
        WHERE a.shipment_id=? AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
          AND COALESCE(al.np_scanned_at,'')<>'' AND al.verified_qty>0
          AND COALESCE(al.np_unreceived_reason,'')='' ''', (payload['id'],)).fetchall()
    read = {row['reception_line_id'] for row in rows}
    previous = {row['reception_line_id'] for row in rows if row['attention_id'] != selected_attention}
    groups = {}
    for line in payload['lines']:
        line['np_total_expected_qty'] = line['expected_qty']
        line['np_previous_scanned'] = line['id'] in previous
        line['np_count_covered_elsewhere'] = line['id'] in covered
        line['np_count_prior_review'] = line['id'] in review['line_ids']
        if line.get('source_bl_eligible') is False or float(line['expected_qty'] or 0) <= 0:
            continue
        code = ''.join(str(line['np_code'] or '').upper().split())
        groups.setdefault(code, []).append(line['id'] in read)
    payload['np_progress'] = {'read': sum(all(group) for group in groups.values()), 'total': len(groups)}


def covered_orders(connection, shipment_id, attention, *, include_unknown=False):
    """Full source-order coverage, never merely the same NP or a default amount."""
    if (not attention or attention['legacy_count_snapshot']
            or str(attention['condition_status'] or '').startswith('ANULADA')):
        return {}
    rows = connection.execute('''WITH other_reads AS (
        SELECT al.reception_line_id, SUM(al.verified_qty) AS quantity
        FROM reception_attention_lines al JOIN reception_attentions a ON a.id=al.attention_id
        WHERE a.shipment_id=? AND al.attention_id<>?
          AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
          AND COALESCE(al.np_scanned_at,'')<>'' AND al.verified_qty>0
          AND COALESCE(al.np_unreceived_reason,'')=''
        GROUP BY al.reception_line_id)
        SELECT al.* FROM reception_attention_lines al
        JOIN reception_lines l ON l.id=al.reception_line_id
        LEFT JOIN other_reads r ON r.reception_line_id=l.id
        WHERE al.attention_id=? AND l.shipment_id=?
          AND COALESCE(al.np_scanned_at,'')='' AND COALESCE(al.np_unreceived_reason,'')=''
          AND ((al.verified_qty=0 AND COALESCE(al.np_covered_elsewhere_at,'')<>'') OR (
            l.expected_qty>0 AND al.planned_qty>0 AND
            (al.verified_qty=0 OR (?='REVISION SISTEMA' AND al.verified_qty=al.planned_qty
              AND (al.np_quantity_saved=0 OR (?=1 AND al.np_quantity_saved IS NULL))))
            AND r.quantity+0.000000001>=MAX(l.expected_qty,al.planned_qty)))''',
        (shipment_id,attention['id'],attention['id'],shipment_id,attention['app_status'],int(include_unknown))).fetchall()
    return {row['reception_line_id']:row for row in rows}


def reconcile_covered_orders(connection, shipment_id, attention, username):
    """Discard only unread overlap prefills during an authorized count write."""
    from backend.services import reception
    changed = False
    for line_id, row in covered_orders(connection,shipment_id,attention).items():
        if not row['verified_qty']:
            continue
        connection.execute('UPDATE reception_attention_lines SET verified_qty=0,np_covered_elsewhere_at=? WHERE id=?',
            (reception.reception_now(),row['id']))
        reception._write_history(connection,shipment_id,'CONTEO ACUMULADO',
            f"atencion:{attention['id']}:linea:{line_id}:received_qty",row['verified_qty'],0,username,
            'Predeterminado sin lectura retirado: pedido completo leido en otra llegada; plan original conservado')
        changed = True
    if changed:
        reception._sync_reception_line_totals(connection,shipment_id)


def prior_read_review(connection, shipment_id, attention):
    ids = sorted(line_id for line_id,row in covered_orders(
        connection,shipment_id,attention,include_unknown=True).items()
        if row['np_quantity_saved'] is None and row['verified_qty']>0)
    token = ''
    if ids:
        # Bind confirmation to both deliveries and the current source quantities.
        evidence = [dict(row) for row in connection.execute('''SELECT al.*,a.app_status,
            a.condition_status,l.expected_qty FROM reception_attention_lines al
            JOIN reception_attentions a ON a.id=al.attention_id
            JOIN reception_lines l ON l.id=al.reception_line_id
            WHERE a.shipment_id=? ORDER BY al.id''',(shipment_id,))]
        token = hashlib.sha256(json.dumps([attention['id'],ids,evidence],sort_keys=True).encode()).hexdigest()
    return {'line_ids':ids,'state_token':token}


def regularize_prior_reads(connection, shipment_id, data, username, role):
    from backend.services import reception
    if role!='ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede regularizar cantidades antiguas')
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    shipment = reception._get_reception_shipment(connection,shipment_id,username,role)
    if type(data.get('attention_id')) is not int or data['attention_id']<=0:
        raise ValueError('Selecciona la atencion de llegada')
    attention = reception._location_context(connection,shipment,data['attention_id'])
    if attention['app_status']!='REVISION SISTEMA':
        raise PermissionError('Regulariza estas cantidades en Inicio de conteo')
    review = prior_read_review(connection,shipment_id,attention)
    ids = data.get('line_ids')
    action = data.get('action','remove_defaults')
    valid_ids = (ids==review['line_ids'] if action=='remove_defaults'
                 else isinstance(ids,list) and len(ids)==1 and ids[0] in review['line_ids'])
    if (data.get('confirmed') is not True or data.get('bl_awb')!=shipment['bl_awb']
            or not isinstance(ids,list) or any(type(value) is not int for value in ids)
            or action not in ('remove_defaults','keep_quantity') or not review['line_ids'] or not valid_ids
            or not isinstance(data.get('state_token'),str) or data['state_token']!=review['state_token']):
        raise ValueError('El conteo cambio o falta confirmacion; reabre la BL y revisa las cantidades antiguas')
    connection.execute('SAVEPOINT prior_read_regularization')
    try:
        for line_id in ids:
            connection.execute('UPDATE reception_attention_lines SET np_quantity_saved=? WHERE attention_id=? AND reception_line_id=?',
                (2 if action=='keep_quantity' else 0,attention['id'],line_id))
        if action=='remove_defaults':
            reconcile_covered_orders(connection,shipment_id,attention,username)
        reception._write_history(connection,shipment_id,'CONTEO ACUMULADO','regularizacion_confirmada',
            json.dumps(ids),'Cantidad fisica manual conservada' if action=='keep_quantity' else 'Cantidades antiguas sin lectura retiradas',username,
            'Administrador confirma recepcion fisica manual de esta llegada; no se inventa una lectura' if action=='keep_quantity'
            else 'Administrador confirma que no son otra recepcion fisica; lecturas completas conservadas en otra llegada')
        result = reception.reception_detail(connection,shipment_id,role,username,attention['id'])
        connection.execute('RELEASE SAVEPOINT prior_read_regularization')
        return result
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT prior_read_regularization')
        connection.execute('RELEASE SAVEPOINT prior_read_regularization')
        raise
