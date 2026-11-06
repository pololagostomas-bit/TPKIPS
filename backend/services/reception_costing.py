"""Documentary costing completes step five, without asserting a SAP transfer."""
import json
from datetime import date, datetime


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_attention_costing(
        attention_id INTEGER PRIMARY KEY REFERENCES reception_attentions(id),
        shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id),
        costing_date TEXT NOT NULL,observed_at TEXT NOT NULL,reference_ids TEXT NOT NULL,
        source_current INTEGER NOT NULL DEFAULT 1)''')


def source_date(value):
    value=str(value or '').strip()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    for pattern in ('%d/%m/%Y','%Y-%m-%d %H:%M:%S','%Y-%m-%dT%H:%M:%S'):
        try:return datetime.strptime(value,pattern).date().isoformat()
        except ValueError:pass
    return ''


def _bound_ems(connection, reference, ip, attention_id):
    from backend.services import reception as r, accounting_source_em
    ems = set(r._accounting_em_values(connection, reference['id'], ip)).intersection(
        r._accounting_em_tokens(reference['em_number']))
    entries = r._accounting_em_entries(connection, reference['id'], ip)
    shared = set(accounting_source_em.values(connection, reference['id'], ip))
    if shared:
        entries += [entry for entry in r._accounting_em_entries(connection, reference['id'])
                    if shared.intersection(r._accounting_em_tokens(entry['em_number']))]
    result = {em for entry in entries if int(entry['attention_id'] or 0) == attention_id
              for em in r._accounting_em_tokens(entry['em_number']) if em in ems}
    from backend.services.reception_em_coverage import covered_ems
    result.update(covered_ems(connection,reference,ip,attention_id).intersection(ems))
    return result


def evidence(connection,shipment_id,attention_id):
    from backend.services import reception as r
    attention=connection.execute('SELECT * FROM reception_attentions WHERE id=? AND shipment_id=?',
        (attention_id,shipment_id)).fetchone()
    missing={'ready':False,'costing_date':'','detail':'Pendiente de fecha de costeo en Facturas','reference_ids':[]}
    if not attention or str(attention['condition_status'] or '').startswith('ANULADA') or attention['condition_status']=='CIERRE ADMINISTRATIVO':
        return missing
    shipment=connection.execute('SELECT * FROM reception_shipments WHERE id=?',(shipment_id,)).fetchone()
    if int(shipment['accounting_conflict_count'] or 0)>0 or shipment['accounting_status']=='CONFLICTO IP':
        return {**missing,'detail':'Referencias contables por revisar'}
    receipt=connection.execute('SELECT * FROM reception_receipts WHERE id=? AND shipment_id=?',
        (attention['receipt_id'],shipment_id)).fetchone()
    arrival=source_date(str(receipt['received_at'])[:10]) if receipt and float(receipt['received_packages'] or 0)>0 else ''
    if not arrival:return {**missing,'detail':'Sin llegada física verificable de esta entrega'}
    from backend.services.reception_source_bl import excluded_ids
    excluded=excluded_ids(connection,shipment_id)
    if any(row['reception_line_id'] in excluded for row in connection.execute(
            'SELECT reception_line_id FROM reception_attention_lines WHERE attention_id=? AND verified_qty>0',(attention_id,))):
        return {**missing,'detail':'Asociación de NP y BL pendiente de regularizar'}
    lines=connection.execute('''SELECT l.ip_reference FROM reception_attention_lines a
        JOIN reception_lines l ON l.id=a.reception_line_id
        WHERE a.attention_id=? AND l.shipment_id=? AND a.verified_qty>0''',(attention_id,shipment_id)).fetchall()
    ips=set()
    for line in lines:
        keys=r._ip_tokens(line['ip_reference'])
        if not keys:return {**missing,'detail':'IP pendiente de identificar en la entrega'}
        ips.update(keys)
    if not ips:return missing
    references=connection.execute('SELECT * FROM reception_accounting_refs WHERE shipment_id=?',(shipment_id,)).fetchall()
    today=source_date(r.reception_now()[:10]);dates=[];reference_ids=set()
    for ip in ips:
        matching=[ref for ref in references if ip in r._ip_tokens(ref['ip_reference'])]
        # Conflicting duplicate references must not silently let one date win.
        if not matching:return missing
        bound = {ref['id']: _bound_ems(connection, ref, ip, attention_id) for ref in matching}
        scoped = [ref for ref in matching if bound[ref['id']]]
        # Repeated rows of the same FR can describe later EMs, not additional
        # documents required by this already scoped arrival. A different FR
        # remains subject to the existing all-references/conflict guards.
        if scoped and len({r._normalized_identifier(ref['fr_number']) for ref in matching}) == 1:
            matching = scoped
        for ref in matching:
            cost=source_date(ref['costing_date'])
            if not (ref['source_file'] and str(ref['fr_number'] or '').strip() and cost and arrival<=cost<=today):
                return missing
            em_date=source_date(ref['em_date'])
            if em_date and cost<em_date:return {**missing,'detail':'Fecha de costeo anterior a la EM'}
            ems=set(r._accounting_em_values(connection,ref['id'],ip)).intersection(
                r._accounting_em_tokens(ref['em_number']))
            if not ems:return {**missing,'detail':'EM pendiente para la entrega'}
            other=connection.execute('''SELECT DISTINCT a.id,l.ip_reference FROM reception_attentions a
                JOIN reception_attention_lines al ON al.attention_id=a.id
                JOIN reception_lines l ON l.id=al.reception_line_id
                WHERE a.shipment_id=? AND a.id<>? AND al.verified_qty>0
                AND a.condition_status NOT LIKE 'ANULADA%' ''',(shipment_id,attention_id)).fetchall()
            if any(ip in r._ip_tokens(row['ip_reference']) for row in other):
                if not bound[ref['id']]:
                    return {**missing,'detail':'Relacionar la EM de esta entrega antes de aplicar el costeo'}
            dates.append(cost);reference_ids.add(ref['id'])
    return {'ready':True,'costing_date':max(dates),'detail':'Costeo registrado en Facturas',
        'reference_ids':sorted(reference_ids)}


def reconcile(connection,shipment_id,actor):
    """Called only from source import/startup/step transition, never on GET."""
    from backend.services import reception as r,reception_transfer as transfer
    from backend.services.reception_closure import master_state
    pending=connection.execute("""SELECT a.* FROM reception_attentions a WHERE shipment_id=?
        AND app_status IN ('SOLICITUD TRANSFERENCIA','CERRADO')""",
        (shipment_id,)).fetchall()
    changed=0
    for attention in pending:
        proof=evidence(connection,shipment_id,attention['id'])
        if attention['app_status']=='CERRADO':
            previous=connection.execute('SELECT * FROM reception_attention_costing WHERE attention_id=?',(attention['id'],)).fetchone()
            if previous is None:
                if proof['ready']:
                    connection.execute('INSERT INTO reception_attention_costing VALUES(?,?,?,?,?,1)',
                        (attention['id'],shipment_id,proof['costing_date'],r.reception_now(),json.dumps(proof['reference_ids'])))
                    r._write_history(connection,shipment_id,'COSTEO',f"atencion:{attention['id']}:costing_date",
                        '',proof['costing_date'],actor,'Costeo documental de una atención ya cerrada; se conserva su cierre')
                    changed+=1
                continue
            current=int(proof['ready'])
            cost=proof['costing_date'] if current else previous['costing_date']
            if cost!=previous['costing_date'] or current!=previous['source_current']:
                connection.execute('UPDATE reception_attention_costing SET costing_date=?,source_current=?,observed_at=? WHERE attention_id=?',
                    (cost,current,r.reception_now(),attention['id']))
                r._write_history(connection,shipment_id,'COSTEO',f"atencion:{attention['id']}:costing_date",
                    previous['costing_date'],cost if current else '',actor,
                    'Actualización documental del costeo; se conserva el cierre operativo')
                changed+=1
            continue
        if not proof['ready']:continue
        connection.execute('SAVEPOINT auto_costing')
        try:
            now=r.reception_now()
            connection.execute('''INSERT INTO reception_attention_costing VALUES(?,?,?,?,?,1)
                ON CONFLICT(attention_id) DO UPDATE SET costing_date=excluded.costing_date,
                observed_at=excluded.observed_at,reference_ids=excluded.reference_ids,source_current=1''',
                (attention['id'],shipment_id,proof['costing_date'],now,json.dumps(proof['reference_ids'])))
            connection.execute("""UPDATE reception_attentions SET app_status='CERRADO',
                condition_status='COMPLETADO',completed_at=?,updated_at=? WHERE id=?""",(now,now,attention['id']))
            transfer.revoke(connection,shipment_id,attention['id'])
            status,condition=master_state(connection,shipment_id)
            old=connection.execute('SELECT app_status FROM reception_shipments WHERE id=?',(shipment_id,)).fetchone()[0]
            connection.execute('UPDATE reception_shipments SET app_status=?,condition_status=?,updated_at=? WHERE id=?',
                (status,condition,now,shipment_id))
            reason=f"Atención {attention['sequence_no']}: paso 5 completado por fecha de costeo {proof['costing_date']} de Facturas"
            r._write_history(connection,shipment_id,'COSTEO',f"atencion:{attention['id']}:costing_date",'',proof['costing_date'],actor,reason)
            r._write_history(connection,shipment_id,'ESTADO','app_status',old,status,actor,reason)
            changed+=1
        except Exception:
            connection.execute('ROLLBACK TO auto_costing')
            raise
        finally:connection.execute('RELEASE auto_costing')
    return changed
