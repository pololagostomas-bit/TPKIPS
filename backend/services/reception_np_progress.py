"""Read evidence and deferred balances, independent of default quantities."""


def deferred_balances(connection):
    return {row['shipment_id']: row['total'] for row in connection.execute('''
        SELECT l.shipment_id, COUNT(DISTINCT UPPER(REPLACE(TRIM(l.np_code),' ',''))) AS total
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
        GROUP BY l.shipment_id''')}


def add_progress(connection, payload, selected_attention):
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
        if float(line['expected_qty'] or 0) <= 0:
            continue
        code = ''.join(str(line['np_code'] or '').upper().split())
        groups.setdefault(code, []).append(line['id'] in read)
    payload['np_progress'] = {'read': sum(all(group) for group in groups.values()), 'total': len(groups)}
