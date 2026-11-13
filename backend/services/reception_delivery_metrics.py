"""Read-only delivery evidence for BL reports; documents/plans are not receipts."""


def delivery_summary(connection):
    columns={row[1] for row in connection.execute("PRAGMA table_info(reception_truck_bl_arrivals)")}
    expected='expected_total_packages' if 'expected_total_packages' in columns else 'NULL'
    rows=connection.execute(f'''WITH raw_deliveries AS (
        SELECT shipment_id,lower(trim(truck_guide)) AS guide,
               received_packages AS quantity,substr(arrived_at,1,10) AS day,0 AS priority,{expected} AS expected
          FROM reception_truck_bl_arrivals WHERE received_packages>0
        UNION ALL
        SELECT shipment_id,lower(trim(truck_guide)) AS guide,
               received_packages AS quantity,substr(received_at,1,10) AS day,1 AS priority,NULL AS expected
          FROM reception_receipts WHERE received_packages>0
    ), deliveries AS (
        SELECT shipment_id,guide,MAX(expected) AS expected,
               COALESCE(MAX(CASE WHEN priority=0 THEN quantity END),SUM(quantity)) AS quantity,
               COALESCE(MIN(CASE WHEN priority=0 THEN NULLIF(day,'') END),MIN(NULLIF(day,''))) AS day
          FROM raw_deliveries GROUP BY shipment_id,guide
    ), voided AS (
        SELECT DISTINCT r.shipment_id,lower(trim(r.truck_guide)) AS guide
          FROM reception_receipts r JOIN reception_attentions a ON a.receipt_id=r.id
         WHERE a.condition_status LIKE 'ANULADA%'
    )
    SELECT d.shipment_id,count(DISTINCT d.guide) AS deliveries,
           count(DISTINCT CASE WHEN date(d.day) IS NOT NULL THEN d.day END) AS days,
           sum(d.quantity) AS received,MAX(d.expected) AS expected
      FROM deliveries d
      JOIN reception_truck_guides g ON lower(trim(g.guide_code))=d.guide
      LEFT JOIN voided v ON v.shipment_id=d.shipment_id AND v.guide=d.guide
     WHERE d.guide<>'' AND COALESCE(g.archived_at,'')=''
       AND upper(trim(g.guide_status))<>'CANCELADA' AND v.shipment_id IS NULL
     GROUP BY d.shipment_id''').fetchall()
    return {int(row['shipment_id']):{'delivery_count':int(row['deliveries']),
            'delivery_days':int(row['days']) or None,'delivery_received':float(row['received']),
            'delivery_expected':float(row['expected'] or 0)} for row in rows}


def delivery_counts(connection):
    return {sid:item['delivery_count'] for sid,item in delivery_summary(connection).items()}


def partial_count(items):
    if any('delivery_count' not in item for item in items):return None
    return sum(bool(item.get('partial_delivery',int(item.get('delivery_count') or 0)>=2)) for item in items)
