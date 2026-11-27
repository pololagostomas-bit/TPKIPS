"""Reuse a unique BL/FR/EM identity when its single documentary IP changes."""
import json


def revise(connection, matched_records, all_records, filename, username):
    from backend.services import reception as r

    def anchor(row, shipment_id):
        ips=r._ip_tokens(row['ip_reference']);ems=r._accounting_em_tokens(row['em_number'])
        awb=r._normalized_identifier(row['awb_reference']);fr=r._normalized_identifier(row['fr_number'])
        if not awb or not fr or len(ips)!=1 or len(ems)!=1:return None
        return shipment_id,awb,fr,ems[0]

    incoming={}
    for record,sid,_ in matched_records:
        key=anchor(record,sid)
        if key:incoming.setdefault(key,[]).append(record)
    if not incoming:return 0
    # Serialize against an operator binding an EM after our safety checks.
    if not connection.in_transaction:connection.execute('BEGIN IMMEDIATE')
    else:connection.execute('UPDATE reception_accounting_refs SET id=id WHERE 0')
    present={record['source_key'] for record in all_records}
    existing={}
    for row in connection.execute('SELECT * FROM reception_accounting_refs WHERE source_file=?',(filename,)):
        key=anchor(row,row['shipment_id'])
        if key:existing.setdefault(key,[]).append(dict(row))
    line_ips={}
    for row in connection.execute('SELECT shipment_id,ip_reference FROM reception_lines'):
        line_ips.setdefault(row['shipment_id'],set()).update(r._ip_tokens(row['ip_reference']))
    changed=0
    for key,records in incoming.items():
        if len(records)!=1:continue
        record=records[0];group=existing.get(key,[])
        stale=[row for row in group if row['source_key'] not in present]
        current=[row for row in group if row['source_key']==record['source_key']]
        if len(stale)!=1 or len(group)!=1+len(current) or len(current)>1:continue
        old=stale[0];old_ip=r._ip_tokens(old['ip_reference'])[0];new_ip=r._ip_tokens(record['ip_reference'])[0]
        if old_ip==new_ip:continue
        expected=line_ips.get(key[0],set())
        if new_ip not in expected or old_ip in expected:continue
        entries=[dict(row) for row in connection.execute('SELECT * FROM reception_accounting_ems WHERE accounting_ref_id=?',(old['id'],))]
        # Explicit coverage cannot silently move from one purchase IP to another.
        ids=[row['id'] for row in entries]
        duplicate=current[0] if current else None
        duplicate_entries=[]
        if duplicate:
            duplicate_entries=[dict(row) for row in connection.execute('SELECT * FROM reception_accounting_ems WHERE accounting_ref_id=?',(duplicate['id'],))]
            if any(row['attention_id'] or row['username']!='importacion' for row in duplicate_entries):continue
            if connection.execute('SELECT 1 FROM reception_history WHERE shipment_id=? AND field_name LIKE ? LIMIT 1',
                    (key[0],f"referencia:{duplicate['id']}:%")).fetchone():continue
            ids.extend(row['id'] for row in duplicate_entries)
        if ids and connection.execute('SELECT 1 FROM reception_em_arrival_coverage WHERE em_id IN ('+
                ','.join('?' for _ in ids)+') LIMIT 1',ids).fetchone():continue
        if any(row['ip_reference_key'] not in (None,old_ip) or r._accounting_em_tokens(row['em_number'])!=[key[3]]
                for row in entries):continue
        if any(row['ip_reference_key'] not in (None,new_ip) or r._accounting_em_tokens(row['em_number'])!=[key[3]]
                for row in duplicate_entries):continue
        costs=[dict(row) for row in connection.execute('SELECT * FROM reception_attention_costing WHERE shipment_id=?',(key[0],))]
        remapped=[]
        for cost in costs:
            refs=json.loads(cost['reference_ids'])
            if duplicate and duplicate['id'] in refs:
                remapped.append((json.dumps(list(dict.fromkeys(old['id'] if ref==duplicate['id'] else ref for ref in refs))),cost['attention_id']))
        snapshot={'reference':old,'em_entries':entries,'duplicate':duplicate,
                  'duplicate_em_entries':duplicate_entries,'costing':costs}
        connection.execute('SAVEPOINT accounting_ip_revision')
        try:
            if duplicate:
                connection.execute('DELETE FROM reception_accounting_source_em WHERE accounting_ref_id=?',(duplicate['id'],))
                connection.execute('DELETE FROM reception_accounting_ems WHERE accounting_ref_id=?',(duplicate['id'],))
                connection.execute('DELETE FROM reception_accounting_refs WHERE id=?',(duplicate['id'],))
                connection.executemany('UPDATE reception_attention_costing SET reference_ids=? WHERE attention_id=?',remapped)
            connection.execute('UPDATE reception_accounting_refs SET source_key=?,ip_reference=?,updated_at=? WHERE id=?',
                (record['source_key'],record['ip_reference'],r.reception_now(),old['id']))
            connection.execute('UPDATE reception_accounting_ems SET ip_reference_key=? WHERE accounting_ref_id=? AND ip_reference_key=?',
                (new_ip,old['id'],old_ip))
            r._write_history(connection,key[0],'REVISION IP FACTURAS',f"referencia:{old['id']}:ip_reference",
                json.dumps(snapshot,ensure_ascii=False),json.dumps({'ip_reference':record['ip_reference'],'reference_id':old['id']},ensure_ascii=False),
                username,'Una referencia BL/FR/EM unívoca del corte sustituye su IP; se conservan EM manual, entrega e historial')
            changed+=1
        except Exception:
            connection.execute('ROLLBACK TO accounting_ip_revision')
            raise
        finally:connection.execute('RELEASE accounting_ip_revision')
    return changed
