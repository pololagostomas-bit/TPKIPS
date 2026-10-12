"""Read-only reception evidence shared by queues, details, reports and work."""
from backend.services.reception_sla import local_stamp


SHIPMENT_CTE = '''WITH physical_receipts AS (
    SELECT shipment_id, MIN(received_at) AS receipt_started_at
    FROM reception_receipts WHERE received_packages>0 GROUP BY shipment_id
), physical_trucks AS (
    SELECT shipment_id, MIN(arrived_at) AS truck_started_at
    FROM reception_truck_bl_arrivals WHERE received_packages>0 GROUP BY shipment_id
), shipment_evidence AS (
    SELECT s.*, r.receipt_started_at, t.truck_started_at,
        (r.shipment_id IS NOT NULL OR t.shipment_id IS NOT NULL) AS has_received_packages,
        CASE WHEN COALESCE((SELECT h.event_type FROM reception_history h
            WHERE h.shipment_id=s.id AND h.field_name='app_status'
              AND h.new_value='ARRIBADO' ORDER BY h.id DESC LIMIT 1),'')
            <>'IMPORTACION EXCEL' AND julianday(s.first_arrival_at) IS NOT NULL
            THEN NULLIF(TRIM(s.first_arrival_at),'') END AS legacy_physical_at,
        EXISTS(SELECT 1 FROM reception_attentions a WHERE a.shipment_id=s.id
            AND a.app_status NOT IN ('PROGRAMADO','ARRIBADO','CERRADO')) AS advanced_attention
    FROM reception_shipments s
    LEFT JOIN physical_receipts r ON r.shipment_id=s.id
    LEFT JOIN physical_trucks t ON t.shipment_id=s.id
), operational_shipments AS (
    SELECT *, CASE
        WHEN app_status IN ('PROGRAMADO','ARRIBADO')
            AND has_received_packages=0
            AND legacy_physical_at IS NULL AND advanced_attention=0 THEN 'PROGRAMADO'
        WHEN app_status='PROGRAMADO'
            AND (has_received_packages=1 OR legacy_physical_at IS NOT NULL) THEN 'ARRIBADO'
        ELSE app_status END AS operational_status
    FROM shipment_evidence
) '''


def arrival_start(item):
    stamps = [stamp for key in ('receipt_started_at','truck_started_at','legacy_physical_at')
              if (stamp := local_stamp(item.get(key))) is not None]
    return min(stamps).isoformat(timespec='seconds') if stamps else None


def project_shipment(item):
    result = dict(item)
    start = arrival_start(result)
    physically_received = bool(result.get('has_received_packages') or start)
    state = result['app_status']
    result.setdefault('stored_app_status', state)
    if state in {'PROGRAMADO','ARRIBADO'}:
        if physically_received:
            state = 'ARRIBADO'
        elif not result.get('advanced_attention'):
            state = 'PROGRAMADO'
    result.update(app_status=state,physical_started_at=start,
                  physically_received=physically_received,
                  awaiting_arrival=state=='PROGRAMADO' and not physically_received)
    return result
