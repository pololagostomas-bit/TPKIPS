"""Small read-only parts-area projection; no source calls or operational writes."""
from collections import defaultdict
from datetime import date
from backend.services.reception_costing import source_date

ROLE='CONSULTA_REPUESTOS'
STATES={'RECEPCION':'Zona de recepción','ALMACEN':'Trabajo en almacén','COSTEO':'Costeo','DISPONIBLE':'Disponible'}


def options(values=None):
    values=values or {}
    defaults={'search':'','state':'ALL','from':'','to':'','transport':'ALL','limit':'50','offset':'0'}
    if set(values)-set(defaults):raise ValueError('Filtro de seguimiento no válido')
    data={**defaults,**values}
    if any(not isinstance(v,str) for v in data.values()):raise ValueError('Filtro de seguimiento no válido')
    data['search']=data['search'].strip()
    if len(data['search'])>100 or data['state'] not in {'ALL',*STATES} or data['transport'] not in {'ALL','AEREO','MARITIMO','COURIER','TERRESTRE','SIN DEFINIR'}:
        raise ValueError('Filtro de seguimiento no válido')
    for key in ('from','to'):
        if data[key] and date.fromisoformat(data[key]).isoformat()!=data[key]:raise ValueError('Fecha no válida')
    if data['from'] and data['to'] and data['from']>data['to']:raise ValueError('Revisa el rango de fechas')
    if not data['limit'].isdigit() or not 1<=int(data['limit'])<=100 or not data['offset'].isdigit() or len(data['offset'])>7:
        raise ValueError('Página no válida')
    return data


def report(connection,values=None):
    from backend.services import reception as r
    filters=options(values)
    groups=defaultdict(list)
    receipts=connection.execute('''SELECT r.*,a.id AS attention_id,a.sequence_no AS attention_sequence,
        a.app_status AS attention_status,a.condition_status,
        CASE WHEN c.source_current=1 THEN c.costing_date ELSE '' END AS costing_date
        FROM reception_receipts r
        LEFT JOIN reception_attentions a ON a.receipt_id=r.id AND a.shipment_id=r.shipment_id
        LEFT JOIN reception_attention_costing c ON c.attention_id=a.id AND c.shipment_id=r.shipment_id
        LEFT JOIN reception_truck_guides g ON lower(trim(g.guide_code))=lower(trim(r.truck_guide))
        WHERE r.received_packages>0 AND COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
        AND COALESCE(g.archived_at,'')='' AND COALESCE(upper(trim(g.guide_status)),'')<>'CANCELADA'
        ORDER BY r.received_at,r.id''').fetchall()
    for row in receipts:
        groups[row['shipment_id']].append({'attention_id':row['attention_id'],
            'sequence':row['attention_sequence'] or row['sequence_no'],'truck':str(row['truck_guide'] or '').strip(),
            'arrival_date':source_date(str(row['received_at'])[:10]),'packages':row['received_packages'],
            'stage':row['attention_status'] or 'ARRIBADO','costing_date':row['costing_date'] or ''})
    # Queued canonical arrivals can exist before a reception receipt is created.
    for row in connection.execute('''SELECT a.* FROM reception_truck_bl_arrivals a
        JOIN reception_truck_guides g ON lower(trim(g.guide_code))=lower(trim(a.truck_guide))
        WHERE a.received_packages>0 AND COALESCE(g.archived_at,'')=''
        AND upper(trim(g.guide_status))<>'CANCELADA'
        AND NOT EXISTS(SELECT 1 FROM reception_receipts r WHERE r.shipment_id=a.shipment_id
        AND lower(trim(r.truck_guide))=lower(trim(a.truck_guide)))'''):
        groups[row['shipment_id']].append({'attention_id':None,'sequence':None,'truck':row['truck_guide'],
            'arrival_date':source_date(str(row['arrived_at'])[:10]),'packages':row['received_packages'],
            'stage':'ARRIBADO','costing_date':''})
    refs=defaultdict(list)
    for row in connection.execute('SELECT shipment_id,em_date,costing_date FROM reception_accounting_refs'):
        refs[row['shipment_id']].append(dict(row))
    starts={row['shipment_id']:source_date(str(row['started'])[:10]) for row in connection.execute('''
        SELECT shipment_id,MIN(created_at) AS started FROM reception_history
        WHERE field_name='app_status' AND new_value='REVISION SISTEMA' AND event_type<>'IMPORTACION EXCEL'
        GROUP BY shipment_id''')}
    items=[]
    for shipment in connection.execute('SELECT id,bl_awb,app_status,transport_type FROM reception_shipments'):
        sid=shipment['id'];deliveries=groups.get(sid,[])
        if not deliveries:continue
        deliveries.sort(key=lambda row:(row['arrival_date'],row['sequence'] or 0))
        pending=[d for d in deliveries if d['stage']!='CERRADO']
        costed=sum(bool(d['costing_date']) and d['stage']=='CERRADO' for d in deliveries)
        if any(d['stage'] in {'PROGRAMADO','ARRIBADO'} for d in pending):state='RECEPCION'
        elif any(d['stage']!='SOLICITUD TRANSFERENCIA' for d in pending):state='ALMACEN'
        elif pending:state='COSTEO'
        elif shipment['app_status']=='CERRADO' and costed==len(deliveries):state='DISPONIBLE'
        elif shipment['app_status']!='CERRADO':state='ALMACEN'
        else:state='COSTEO'
        source_refs=refs.get(sid,[])
        em_dates=sorted({d for ref in source_refs if (d:=source_date(ref['em_date']))})
        cost_dates=sorted({d['costing_date'] for d in deliveries if d['costing_date']})
        trucks=list(dict.fromkeys(d['truck'] for d in deliveries if d['truck']))
        item={'id':sid,'bl_awb':shipment['bl_awb'],'state':state,'state_label':STATES[state],
            'truck_guides':trucks,'arrival_date':deliveries[0]['arrival_date'],'work_date':starts.get(sid,''),
            'em_date':em_dates[-1] if em_dates else '', 'em_dates':em_dates,
            'costing_date':cost_dates[-1] if cost_dates else '',
            'available_date':cost_dates[-1] if state=='DISPONIBLE' else '',
            'transport':shipment['transport_type'] or 'SIN DEFINIR','delivery_count':len(deliveries),
            'costed_deliveries':costed,'deliveries':deliveries,
            'pending_delivery':not pending and shipment['app_status']!='CERRADO'}
        if (filters['search'].casefold() not in (item['bl_awb']+' '+' '.join(trucks)).casefold()
            or filters['state']!='ALL' and filters['state']!=state
            or filters['from'] and item['arrival_date']<filters['from']
            or filters['to'] and item['arrival_date']>filters['to']
            or filters['transport']!='ALL' and filters['transport']!=item['transport']):continue
        items.append(item)
    items.sort(key=lambda row:(row['arrival_date'],row['id']),reverse=True)
    summary={key:sum(item['state']==key for item in items) for key in STATES}
    offset=int(filters['offset']);limit=int(filters['limit'])
    return {'items':items[offset:offset+limit],'summary':summary,'total':len(items),
        'offset':offset,'limit':limit,'has_more':offset+limit<len(items),'generated_at':r.reception_now()}
