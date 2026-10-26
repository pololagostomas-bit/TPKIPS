"""Read-only delivery evidence for BL reports; documents/plans are not receipts."""


def delivery_counts(connection):
    rows=connection.execute('''WITH deliveries AS (
        SELECT shipment_id,lower(trim(truck_guide)) AS guide
          FROM reception_truck_bl_arrivals WHERE received_packages>0
        UNION
        SELECT shipment_id,lower(trim(truck_guide)) AS guide
          FROM reception_receipts WHERE received_packages>0
    ), voided AS (
        SELECT DISTINCT r.shipment_id,lower(trim(r.truck_guide)) AS guide
          FROM reception_receipts r JOIN reception_attentions a ON a.receipt_id=r.id
         WHERE a.condition_status LIKE 'ANULADA%'
    )
    SELECT d.shipment_id,count(DISTINCT d.guide) AS deliveries
      FROM deliveries d
      JOIN reception_truck_guides g ON lower(trim(g.guide_code))=d.guide
      LEFT JOIN voided v ON v.shipment_id=d.shipment_id AND v.guide=d.guide
     WHERE d.guide<>'' AND COALESCE(g.archived_at,'')=''
       AND upper(trim(g.guide_status))<>'CANCELADA' AND v.shipment_id IS NULL
     GROUP BY d.shipment_id''').fetchall()
    return {int(row['shipment_id']):int(row['deliveries']) for row in rows}


def partial_count(items):
    if any('delivery_count' not in item for item in items):return None
    return sum(int(item.get('delivery_count') or 0)>=2 for item in items)
