"""Read-only work projection; documentary evidence never creates physical arrivals."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from backend.services import reception
from backend.services.reception_sla import deadline, local_stamp
from backend.services.reception_closure import closure_check
from backend.services.reception_projection import SHIPMENT_CTE, project_shipment

LIMA = timezone(timedelta(hours=-5))
DOCUMENTARY_COMPLETE = 'FR/EM COMPLETAS'


def _stamp(value):
    return local_stamp(value)


def _earliest(*values):
    stamps = [stamp for value in values if (stamp := _stamp(value)) is not None]
    return min(stamps).isoformat(timespec='seconds') if stamps else None


def _deadline(start, hours):
    return deadline(start, hours)


def _timing(item, start, finish, now):
    hours = 96 if str(item.get('transport_type') or '').upper() == 'MARITIMO' else 72
    start_dt = _stamp(start)
    if start_dt and start_dt > _stamp(now):
        start = None
    elapsed = (reception._elapsed_hours_excluding_sundays(start, finish or now)
               if start and (item['work_pending'] or finish) else None)
    remaining = hours - elapsed if elapsed is not None else None
    status = ('SIN INICIO' if item['pending_arrival'] else
              'NO APLICA' if item['work_status'] == DOCUMENTARY_COMPLETE else
              'FINALIZADO' if not item['work_pending'] else
              'SIN INICIO' if remaining is None else
              'ROJO' if remaining < 0 else 'AMARILLO' if remaining <= 12 else 'VERDE')
    return {'work_started_at': start, 'work_closed_at': finish,
            'sla_hours': hours, 'sla_status': status,
            'elapsed_hours': round(elapsed, 2) if elapsed is not None else None,
            'remaining_hours': round(remaining, 2) if remaining is not None else None,
            'sla_due_at': _deadline(start, hours) if start else None}


def reception_work_report(connection, username='', role='ADMINISTRADOR', *,
                          include_history=False, search='', stage='', sla='',
                          limit=100, offset=0, now=None, view=''):
    reception.require_reception_access(role)
    user = str(username or '').strip().casefold()
    if role != 'ADMINISTRADOR' and not user:
        raise PermissionError('Se requiere un usuario de recepcion')
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    view = view or ('all' if include_history else 'pending')
    if view not in {'all','pending','arrival','history'}:
        raise ValueError('Vista de recepcion invalida')
    now = now or reception.reception_now()
    where = '' if role == 'ADMINISTRADOR' else ''' WHERE
        lower(COALESCE(s.current_assistant,''))=? OR lower(COALESCE(s.current_auxiliary,''))=?
        OR EXISTS (SELECT 1 FROM reception_attentions a WHERE a.shipment_id=s.id
                   AND (lower(COALESCE(a.current_assistant,''))=? OR lower(COALESCE(a.current_auxiliary,''))=?))'''
    shipments = connection.execute(SHIPMENT_CTE + 'SELECT s.* FROM operational_shipments s' + where,
                                   () if role == 'ADMINISTRADOR' else (user,) * 4).fetchall()
    attentions = defaultdict(list)
    for row in connection.execute('''SELECT a.*, r.received_at AS receipt_started_at,
                                      r.received_packages AS receipt_packages
                                      FROM reception_attentions a
                                      LEFT JOIN reception_receipts r ON r.id=a.receipt_id
                                      WHERE COALESCE(a.condition_status,'') NOT LIKE 'ANULADA%'
                                      ORDER BY a.shipment_id,a.sequence_no'''):
        attentions[row['shipment_id']].append(dict(row))
    refs = defaultdict(list)
    for row in connection.execute('SELECT * FROM reception_accounting_refs'):
        refs[row['shipment_id']].append(row)
    closed = {row['shipment_id']: row['finished'] for row in connection.execute('''
        SELECT shipment_id,MAX(created_at) AS finished FROM reception_history
        WHERE field_name='app_status' AND new_value='CERRADO' GROUP BY shipment_id''')}
    projected = []
    for shipment in shipments:
        s = project_shipment(shipment)
        sid = s['id']
        group = attentions[sid]
        documentary_status = reception._accounting_status_for_shipment(
            connection, sid, shipment, refs[sid], include_unreceived_ips=True)
        physical_start = s['physical_started_at']
        candidates = group or [None]
        if group and not any(a['app_status']!='CERRADO' for a in group) and s['app_status']!='CERRADO':
            candidates = group + [None]
        for attention in candidates:
            item = {key: s.get(key) for key in ('id','bl_awb','transport_type','supplier','scheduled_date',
                    'expected_packages','received_packages','first_arrival_at','truck_guide')}
            item['attention_id'] = attention['id'] if attention else None
            item['attention_sequence'] = attention['sequence_no'] if attention else None
            item['attention_position'] = group.index(attention)+1 if attention else None
            item['attention_total'] = len(group)
            for owner in ('current_assistant','current_auxiliary'):
                item[owner] = (attention.get(owner) if attention else None) or s.get(owner)
            if role!='ADMINISTRADOR' and user not in {
                str(item.get(owner) or '').strip().casefold() for owner in ('current_assistant','current_auxiliary')}:
                continue
            state = attention['app_status'] if attention else s['app_status']
            item['app_status'] = state
            item['accounting_status'] = documentary_status
            item['documentary_complete'] = documentary_status == 'EM REGISTRADA'
            item['work_status'] = state
            # Legacy advanced stages without dates stay advanced, not "pending arrival".
            if item['work_status']=='PROGRAMADO' and s['physically_received']:
                item['work_status']='ARRIBADO'
            if state in {'PROGRAMADO','ARRIBADO'} and not s['physically_received'] and not s['advanced_attention']:
                item['work_status'] = 'PROGRAMADO'
            item['app_status'] = item['work_status']
            item['pending_arrival'] = item['work_status']=='PROGRAMADO' and not s['physically_received']
            item['work_pending'] = item['work_status'] != 'CERRADO' and not item['pending_arrival']
            item['work_reason'] = 'En espera de registrar la llegada del camion' if item['pending_arrival'] else ''
            reconcile_parent = bool(group) and attention is None
            if reconcile_parent:
                item['work_reason'] = 'Atenciones cerradas; revisar saldo y estado de la BL'
            item['closure_eligible'] = False
            item['attention_received_packages'] = float(attention.get('receipt_packages') or 0) if attention else None
            # Each partial arrival has its own operational attention and start.
            start = (_earliest(attention.get('receipt_started_at'))
                     if attention and float(attention.get('receipt_packages') or 0)>0 else None) or physical_start
            if reconcile_parent:
                start = None
            finish = (attention.get('completed_at') if attention else closed.get(sid)) if state=='CERRADO' else None
            item.update(_timing(item,start,finish,now))
            projected.append(item)
    active = [item for item in projected if item['work_pending']]
    by_bl = defaultdict(list)
    for item in active:
        by_bl[item['id']].append(item)
    by_status = defaultdict(int)
    worst_sla = {}
    for group in by_bl.values():
        # One BL in the KPI, even when two arrival tasks are visible.
        state = min(group,key=lambda item: reception.RECEPTION_STATE_INDEX.get(item['work_status'],99))['work_status']
        by_status[state] += 1
        worst_sla[group[0]['id']] = min(group, key=lambda item:
            {'ROJO':0,'AMARILLO':1,'SIN INICIO':2,'VERDE':3}.get(item['sla_status'],4))['sla_status']
    count_bl = lambda predicate: len({item['id'] for item in active if predicate(item)})
    summary = {'module':'reception','total':len(by_bl),'by_status':dict(by_status),
               'open_attentions':sum(item['attention_id'] is not None for item in active),
               'pending_arrival':len({item['id'] for item in projected if item['pending_arrival']}),
               'sla_at_risk':sum(value=='AMARILLO' for value in worst_sla.values()),
               'sla_overdue':sum(value=='ROJO' for value in worst_sla.values()),
               'sla_missing_start':count_bl(lambda item:not item['pending_arrival'] and not item['work_started_at']),
               'documentary_complete_count':len({item['id'] for item in projected if item['documentary_complete'] and not item['work_pending']})}
    rows = (projected if view=='all' else active if view=='pending' else
            [item for item in projected if item['pending_arrival']] if view=='arrival' else
            [item for item in projected if item['work_status']=='CERRADO'])
    query = str(search or '').strip().casefold()
    if query:
        rows = [item for item in rows if query in str(item['bl_awb']).casefold()]
    if stage:
        rows = [item for item in rows if item['work_status']==stage]
    if sla:
        rows = [item for item in rows if item['sla_status']==sla and
                (sla!='AMARILLO' or worst_sla.get(item['id'])=='AMARILLO')]
    rows.sort(key=lambda item:(not item['work_pending'],
        {'ROJO':0,'AMARILLO':1,'VERDE':2,'SIN INICIO':3}.get(item['sla_status'],4),
        item['sla_due_at'] or '9999',item['scheduled_date'] or '9999',item['id'],item['attention_sequence'] or 0))
    page = rows[offset:offset+limit]
    page_brands = {}
    for item in page:
        if item['id'] not in page_brands:
            page_brands[item['id']] = reception._shipment_brands(connection,item['id'],item.get('brand_summary'))
        item['brands'] = page_brands[item['id']]
    # Closure buttons are page-local; their validation cannot affect global KPIs.
    if role == 'ADMINISTRADOR':
        for item in page:
            if item['app_status']!='CERRADO' and not item['attention_id']:
                eligible, reason = closure_check(connection, item['id'], allow_documentary=True)
                item['closure_eligible'] = eligible
                item['closure_reason'] = reason
    return {'items':page,'summary':summary,'total':len(rows),'view':view,
            'total_bl':len({item['id'] for item in rows}),'offset':offset,'limit':limit,
            'has_more':offset+limit<len(rows),'generated_at':now}
