"""Light, read-only picking queues; creation timestamps come from the SAP cut."""
from datetime import datetime,time,timedelta
import re

from .workload import _internal_client,_timestamp,_now


def cutoff_window(reference=None):
    now=_timestamp(reference or _now())
    if now is None:
        raise ValueError('Fecha de referencia no válida')
    cutoff=datetime.combine(now.date(),time(16))
    while cutoff>now or cutoff.weekday()>=5:cutoff-=timedelta(days=1)
    previous=cutoff-timedelta(days=1)
    while previous.weekday()>=5:previous-=timedelta(days=1)
    delivery=cutoff.date()+timedelta(days=1)
    while delivery.weekday()>=5:delivery+=timedelta(days=1)
    return {'window_start':previous.isoformat(),'cutoff_at':cutoff.isoformat(),
            'delivery_start':datetime.combine(delivery,time(8)).isoformat(),
            'delivery_end':datetime.combine(delivery,time(10)).isoformat(),
            'timezone':'America/Lima','calendar':'Lunes a viernes',
            'overdue':now>datetime.combine(delivery,time(10))}


def work_queue(app,db,username,role,customer_type='internal',scope='current',search='',page=1,reference=None):
    app.require_dispatch_access(role)
    if customer_type not in ('internal','regular') or scope not in ('current','carryover','review'):
        raise ValueError('Cola de picking no válida')
    if isinstance(page,bool) or not str(page).isdigit() or not 1<=int(page)<=1000000:
        raise ValueError('Página no válida')
    page=int(page);search=str(search or '').strip().lower();meta=cutoff_window(reference)
    result={**meta,'items':[],'page':page,'page_size':6,'total':0,'counts':dict.fromkeys(('current','carryover','review'),0)}
    if customer_type=='regular' and not search:return result
    db.create_function('wms_internal_client',1,_internal_client,deterministic=True)
    filters,params=app.dispatch_role_filters(username,role)
    filters+=['NOT EXISTS(SELECT 1 FROM dispatch_context c WHERE c.sap_ov=o.sap_ov AND c.kind=\'STS\')',
              'wms_internal_client(o.customer_name)=?']
    params.append(int(customer_type=='internal'))
    if search:
        filters.append('''(lower(o.sap_ov) LIKE ? OR lower(o.customer_name) LIKE ?
            OR EXISTS(SELECT 1 FROM order_lines l WHERE l.sap_ov=o.sap_ov AND
              (lower(l.item_code) LIKE ? OR lower(l.description) LIKE ?)))''')
        params.extend(['%'+search+'%']*4)
    if customer_type=='internal':
        filters+=['''(o.source_present=1 OR EXISTS(SELECT 1 FROM attentions a WHERE a.sap_ov=o.sap_ov
            AND a.app_status NOT IN ('PENDIENTE','ASIGNADO','ENTREGADO','CERRADO SAP')))''',
            '''(EXISTS(SELECT 1 FROM order_lines l WHERE l.sap_ov=o.sap_ov AND l.is_pending_sap=1 AND l.pending_qty>0)
            OR EXISTS(SELECT 1 FROM attentions a WHERE a.sap_ov=o.sap_ov AND a.app_status NOT IN ('ENTREGADO','CERRADO SAP')))''']
    rows=db.execute('''SELECT o.sap_ov,o.customer_name,o.source_order_date,o.app_status,o.document_status,
        o.current_picker,o.current_guide,o.source_present,
        (SELECT a.app_status FROM attentions a WHERE a.sap_ov=o.sap_ov
            AND a.app_status NOT IN ('ENTREGADO','CERRADO SAP') ORDER BY a.sequence_no DESC LIMIT 1) AS active_status
        FROM orders o WHERE '''+' AND '.join(filters)+' ORDER BY o.source_order_date,o.sap_ov',params).fetchall()
    buckets={name:[] for name in ('current','carryover','review')}
    previous=_timestamp(meta['window_start']);cutoff=_timestamp(meta['cutoff_at'])
    for row in rows:
        item=dict(row);item['active_status']=item['active_status'] or item['app_status']
        if customer_type=='regular':
            result['items'].append(item);continue
        if item['app_status']=='CERRADO SAP' or str(item['document_status'] or '').upper() in {'CERRADO','CERRADA','CLOSED','C'}:continue
        if item['app_status']=='ENTREGADO':
            lines=db.execute('SELECT id,pending_qty FROM order_lines WHERE sap_ov=? AND is_pending_sap=1',(item['sap_ov'],)).fetchall()
            if not any(app.remaining_line_quantity(db,item['sap_ov'],line)>0 for line in lines):continue
        stamp=_timestamp(item['source_order_date'])
        if stamp is None or not re.search(r'[T ]\d{1,2}:\d{2}',str(item['source_order_date'] or '')):bucket='review'
        elif stamp<=previous:bucket='carryover'
        elif stamp<=cutoff:bucket='current'
        else:continue
        buckets[bucket].append(item)
    if customer_type=='internal':
        result['counts']={key:len(value) for key,value in buckets.items()};result['items']=buckets[scope]
    result['total']=len(result['items']);page=min(page,max(1,(result['total']+5)//6));result['page']=page
    result['items']=result['items'][(page-1)*6:page*6]
    return result
