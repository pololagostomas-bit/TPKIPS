"""Read-only work projection; documentary evidence never creates physical arrivals."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from backend.services import reception

LIMA = timezone(timedelta(hours=-5))
DOCUMENTARY_COMPLETE = 'FR/EM COMPLETAS'


def _stamp(value):
    try:
        result = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
        return result.astimezone(LIMA).replace(tzinfo=None) if result.tzinfo else result
    except (TypeError, ValueError, OverflowError):
        return None


def _earliest(*values):
    stamps = [stamp for value in values if (stamp := _stamp(value)) is not None]
    return min(stamps).isoformat(timespec='seconds') if stamps else None


def _deadline(start, hours):
    cursor = _stamp(start)
    remaining = timedelta(hours=hours)
    while remaining > timedelta(0):
        midnight = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if cursor.weekday() == 6:
            cursor = midnight
            continue
        available = midnight - cursor
        if remaining <= available:
            return (cursor + remaining).isoformat(timespec='seconds')
        remaining -= available
        cursor = midnight


def _timing(item, start, finish, now):
    hours = 96 if str(item.get('transport_type') or '').upper() == 'MARITIMO' else 72
    start_dt = _stamp(start)
    if start_dt and start_dt > _stamp(now):
        start = None
    elapsed = (reception._elapsed_hours_excluding_sundays(start, finish or now)
               if start and (item['work_pending'] or finish) else None)
    remaining = hours - elapsed if elapsed is not None else None
    status = ('NO APLICA' if item['work_status'] == DOCUMENTARY_COMPLETE else
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
                          limit=100, offset=0, now=None):
    reception.require_reception_access(role)
    user = str(username or '').strip().casefold()
    if role != 'ADMINISTRADOR' and not user:
        raise PermissionError('Se requiere un usuario de recepcion')
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    now = now or reception.reception_now()
    where = '' if role == 'ADMINISTRADOR' else ''' WHERE
        lower(COALESCE(s.current_assistant,''))=? OR lower(COALESCE(s.current_auxiliary,''))=?
        OR EXISTS (SELECT 1 FROM reception_attentions a WHERE a.shipment_id=s.id
                   AND (lower(COALESCE(a.current_assistant,''))=? OR lower(COALESCE(a.current_auxiliary,''))=?))'''
    shipments = connection.execute('SELECT s.* FROM reception_shipments s' + where,
                                   () if role == 'ADMINISTRADOR' else (user,) * 4).fetchall()
    # Gather arrival/attention evidence once. A manifest proposal or an Excel
    # date is not an arrival and must not start a worker's SLA.
    receipts = {row['shipment_id']: row['started'] for row in connection.execute('''
        SELECT shipment_id, MIN(received_at) AS started FROM reception_receipts
        WHERE received_packages>0 GROUP BY shipment_id''')}
    arrivals = {row['shipment_id']: row['started'] for row in connection.execute('''
        SELECT shipment_id, MIN(arrived_at) AS started FROM reception_truck_bl_arrivals
        WHERE received_packages>0 GROUP BY shipment_id''')}
    confirmed = {row[0] for row in connection.execute('''
        SELECT DISTINCT m.shipment_id FROM reception_truck_bl_manifest m
        JOIN reception_truck_guides g ON lower(g.guide_code)=lower(m.truck_guide)
        WHERE COALESCE(m.operational_active,1)=1 AND g.guide_status<>'CANCELADA'
          AND (g.is_confirmed=1 OR g.source_type='ESTIMACION_PRUEBA')''')}
    attentions = defaultdict(list)
    for row in connection.execute('''SELECT a.*, r.received_at AS receipt_started_at,
                                      r.received_packages AS receipt_packages
                                      FROM reception_attentions a
                                      LEFT JOIN reception_receipts r ON r.id=a.receipt_id
                                      ORDER BY a.shipment_id,a.sequence_no'''):
        attentions[row['shipment_id']].append(dict(row))
    refs = defaultdict(list)
    for row in connection.execute('SELECT * FROM reception_accounting_refs'):
        refs[row['shipment_id']].append(row)
    closed = {row['shipment_id']: row['finished'] for row in connection.execute('''
        SELECT shipment_id,MAX(created_at) AS finished FROM reception_history
        WHERE field_name='app_status' AND new_value='CERRADO' GROUP BY shipment_id''')}
    arrival_origin = {row['shipment_id']: row['event_type'] for row in connection.execute('''
        SELECT shipment_id,event_type FROM reception_history
        WHERE field_name='app_status' AND new_value='ARRIBADO' ORDER BY id''')}
    projected = []
    for shipment in shipments:
        s = dict(shipment)
        sid = s['id']
        group = attentions[sid]
        documentary_status = reception._accounting_status_for_shipment(
            connection, sid, shipment, refs[sid], include_unreceived_ips=True)
        imported_arrival = arrival_origin.get(sid)=='IMPORTACION EXCEL'
        physical_start = _earliest(None if imported_arrival else s.get('first_arrival_at'),
                                   receipts.get(sid), arrivals.get(sid))
        operational = bool(physical_start or group or sid in confirmed or
                           float(s.get('received_packages') or 0)>0 or
                           (s['app_status'] != 'PROGRAMADO' and not
                            (s['app_status']=='ARRIBADO' and imported_arrival)))
        documentary_only = documentary_status == 'EM REGISTRADA' and not operational
        candidates = group or [None]
        if group and not any(a['app_status']!='CERRADO' for a in group) and s['app_status']!='CERRADO':
            candidates = group + [None]
        for attention in candidates:
            item = {key: s.get(key) for key in ('id','bl_awb','transport_type','supplier','scheduled_date',
                    'expected_packages','received_packages','first_arrival_at','truck_guide')}
            item['attention_id'] = attention['id'] if attention else None
            item['attention_sequence'] = attention['sequence_no'] if attention else None
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
            item['work_status'] = DOCUMENTARY_COMPLETE if documentary_only and state!='CERRADO' else state
            # Legacy advanced stages without dates stay advanced, not "pending arrival".
            if item['work_status']=='PROGRAMADO' and physical_start:
                item['work_status']='ARRIBADO'
            item['work_pending'] = item['work_status'] not in {'CERRADO',DOCUMENTARY_COMPLETE}
            item['pending_arrival'] = item['work_pending'] and item['work_status']=='PROGRAMADO' and not physical_start
            item['work_reason'] = ('Documentos completos; sin recepcion fisica registrada en WMS'
                                   if documentary_only else
                                   'Llegada heredada del Excel; verificar fecha fisica en WMS'
                                   if imported_arrival and not physical_start else '')
            reconcile_parent = bool(group) and attention is None
            if reconcile_parent:
                item['work_reason'] = 'Atenciones cerradas; revisar saldo y estado de la BL'
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
               'pending_arrival':count_bl(lambda item:item['pending_arrival']),
               'sla_at_risk':sum(value=='AMARILLO' for value in worst_sla.values()),
               'sla_overdue':sum(value=='ROJO' for value in worst_sla.values()),
               'sla_missing_start':count_bl(lambda item:not item['pending_arrival'] and not item['work_started_at']),
               'documentary_complete_count':len({item['id'] for item in projected if item['work_status']==DOCUMENTARY_COMPLETE})}
    rows = projected if include_history else active
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
    return {'items':rows[offset:offset+limit],'summary':summary,'total':len(rows),
            'total_bl':len({item['id'] for item in rows}),'offset':offset,'limit':limit,
            'has_more':offset+limit<len(rows),'generated_at':now}
