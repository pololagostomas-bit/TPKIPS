"""Audited exception: one documentary EM explicitly covers selected arrivals."""
import json


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_em_arrival_coverage(
        em_id INTEGER NOT NULL REFERENCES reception_accounting_ems(id),
        attention_id INTEGER NOT NULL REFERENCES reception_attentions(id),
        origin_attention_id INTEGER NOT NULL, fr_key TEXT NOT NULL,
        ip_key TEXT NOT NULL, em_number TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        updated_by TEXT NOT NULL, updated_at TEXT NOT NULL, reason TEXT NOT NULL,
        PRIMARY KEY(em_id,attention_id,ip_key))''')


def _received(connection, shipment_id, reference, ip, attention_id):
    from backend.services import reception as r
    attention=connection.execute('''SELECT a.*,r.received_packages FROM reception_attentions a
        JOIN reception_receipts r ON r.id=a.receipt_id AND r.shipment_id=a.shipment_id
        WHERE a.shipment_id=? AND a.id=?''',(shipment_id,attention_id)).fetchone()
    return bool(attention and float(attention['received_packages'] or 0)>0
        and not str(attention['condition_status'] or '').startswith('ANULADA')
        and attention['condition_status']!='CIERRE ADMINISTRATIVO'
        and attention['app_status'] in {'EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO'}
        and r._accounting_ref_has_received_sku(connection,shipment_id,reference,ip,attention_id))


def _valid_coverages(connection, reference, ip):
    """Return only still-valid selected arrivals; source changes revoke evidence."""
    from backend.services import reception as r
    if ip not in r._ip_tokens(reference['ip_reference']):return []
    current=set(r._accounting_em_tokens(reference['em_number']))
    fr=r._normalized_identifier(reference['fr_number'])
    if not current or not fr:return []
    rows=connection.execute('''SELECT c.*,e.attention_id origin,e.em_number current_em,
        e.ip_reference_key FROM reception_em_arrival_coverage c
        JOIN reception_accounting_ems e ON e.id=c.em_id
        WHERE e.accounting_ref_id=? AND c.ip_key=? AND c.active=1''',(reference['id'],ip)).fetchall()
    return [row for row in rows
        if row['fr_key']==fr and row['em_number'] in current
        and row['em_number'] in r._accounting_em_tokens(row['current_em'])
        and row['origin']==row['origin_attention_id']
        and row['ip_reference_key'] in (None,ip)
        and _received(connection,reference['shipment_id'],reference,ip,row['attention_id'])]


def covered_ids(connection, reference, ip):
    return {row['attention_id'] for row in _valid_coverages(connection,reference,ip)}


def covered_ems(connection, reference, ip, attention_id):
    return {row['em_number'] for row in _valid_coverages(connection,reference,ip)
            if row['attention_id']==attention_id}


def eligible_ids(connection, reference, ip, attention_ids):
    return [aid for aid in attention_ids if _received(connection,reference['shipment_id'],reference,ip,aid)]


def entry_coverage(connection, reference, ip):
    result={}
    for row in _valid_coverages(connection,reference,ip):
        result.setdefault(row['em_id'],[]).append(row['attention_id'])
    return result


def effective_count(connection, shipment_id, reference, ip=None):
    """Count covered receptions separately from the number of actual documents."""
    from backend.services import reception as r
    keys=set(r._ip_tokens(reference['ip_reference']))
    family=[ref for ref in connection.execute('SELECT * FROM reception_accounting_refs WHERE shipment_id=?',(shipment_id,))
            if r._normalized_identifier(ref['fr_number'])==r._normalized_identifier(reference['fr_number'])
            and (ip in r._ip_tokens(ref['ip_reference']) if ip else set(r._ip_tokens(ref['ip_reference']))==keys)]
    return group_effective_count(connection,shipment_id,family,ip)


def group_effective_count(connection, shipment_id, references, ip=None):
    from backend.services import reception as r
    documents=len({value for ref in references for value in r._accounting_em_values(connection,ref['id'],ip)})
    covered=set()
    for ref in references:
        for key in ([ip] if ip else r._ip_tokens(ref['ip_reference'])):
            covered.update(covered_ids(connection,ref,key))
    if not covered:return documents
    for ref in references:
        for key in ([ip] if ip else r._ip_tokens(ref['ip_reference'])):
            for entry in r._accounting_em_entries(connection,ref['id'],key):
                aid=entry['attention_id']
                if (aid and set(r._accounting_em_tokens(entry['em_number'])).intersection(r._accounting_em_tokens(ref['em_number']))
                        and _received(connection,shipment_id,ref,key,aid)):
                    covered.add(aid)
    return max(documents,len(covered))


def set_coverage(connection, shipment_id, data, username, role):
    from backend.services import reception as r
    if role!='ADMINISTRADOR':raise PermissionError('Solo el administrador puede definir una EM para varias entregas')
    ids=data.get('coverage_attention_ids')
    if (not isinstance(ids,list) or len(ids)>50 or any(type(a) is not int or a<=0 for a in ids)
            or len(set(ids))!=len(ids) or len(ids)==1):
        raise ValueError('Selecciona al menos dos entregas distintas o quita la cobertura excepcional')
    if any(type(data.get(k)) is not int or data[k]<=0 for k in ['id','em_id']):
        raise ValueError('Selecciona una FR y una EM existentes')
    reason=str(data.get('reason') or '').strip()
    if data.get('confirmed') is not True or not 8<=len(reason)<=500:
        raise ValueError('Confirma las entregas e indica un motivo de 8 a 500 caracteres')
    if not connection.in_transaction:connection.execute('BEGIN IMMEDIATE')
    else:connection.execute('UPDATE reception_shipments SET id=id WHERE 0')
    r._get_reception_shipment(connection,shipment_id,username,role)
    ref=connection.execute('SELECT * FROM reception_accounting_refs WHERE id=? AND shipment_id=?',(data['id'],shipment_id)).fetchone()
    entry=connection.execute('SELECT * FROM reception_accounting_ems WHERE id=? AND accounting_ref_id=?',(data['em_id'],data['id'])).fetchone()
    if not ref or not entry or not entry['attention_id']:
        raise ValueError('Selecciona una EM existente vinculada a su entrega de origen')
    ip=str(data.get('ip_key') or '').strip()
    values=r._accounting_em_tokens(data.get('em_number'))
    if (ip not in r._ip_tokens(ref['ip_reference']) or not str(ref['fr_number'] or '').strip()
            or entry['ip_reference_key'] not in (None,ip) or len(values)!=1
            or values!=r._accounting_em_tokens(entry['em_number'])
            or values[0] not in r._accounting_em_tokens(ref['em_number'])):
        raise ValueError('La FR/IP/EM cambió; actualiza la BL y revisa la referencia')
    if ids and entry['attention_id'] not in ids:
        raise ValueError('Incluye la entrega de origen de esta EM en la cobertura')
    if any(not _received(connection,shipment_id,ref,ip,aid) for aid in ids):
        raise ValueError('Todas las entregas seleccionadas deben tener NP recibidos de esta IP y estar desde EM')
    for other in connection.execute('SELECT * FROM reception_accounting_refs WHERE shipment_id=?',(shipment_id,)):
        if (r._normalized_identifier(other['fr_number'])!=r._normalized_identifier(ref['fr_number'])
                or ip not in r._ip_tokens(other['ip_reference'])):continue
        declared=set(r._accounting_em_tokens(other['em_number']))
        for assigned in r._accounting_em_entries(connection,other['id'],ip):
            documents=set(r._accounting_em_tokens(assigned['em_number'])).intersection(declared)
            if assigned['attention_id'] in ids and documents and values[0] not in documents:
                raise ValueError('Una entrega seleccionada ya tiene otra EM de esta FR/IP; revisa su asociación')
        if any(row['attention_id'] in ids and row['em_number']!=values[0]
               for row in _valid_coverages(connection,other,ip)):
            raise ValueError('Una entrega seleccionada ya está cubierta por otra EM de esta FR/IP')
    # Replacing the explicit set supports audited revocation; it never changes
    # the EM's original attention or reopens historical physical completion.
    previous=[dict(x) for x in connection.execute('SELECT * FROM reception_em_arrival_coverage WHERE em_id=? AND ip_key=? AND active=1',(entry['id'],ip))]
    signature=(int(entry['attention_id']),r._normalized_identifier(ref['fr_number']),values[0])
    if ({x['attention_id'] for x in previous}==set(ids)
            and all((x['origin_attention_id'],x['fr_key'],x['em_number'])==signature for x in previous)):
        return False
    connection.execute('UPDATE reception_em_arrival_coverage SET active=0,updated_by=?,updated_at=?,reason=? WHERE em_id=? AND ip_key=? AND active=1',
        (username,r.reception_now(),reason,entry['id'],ip))
    for aid in ids:
        connection.execute('''INSERT INTO reception_em_arrival_coverage
            (em_id,attention_id,origin_attention_id,fr_key,ip_key,em_number,active,updated_by,updated_at,reason)
            VALUES(?,?,?,?,?,?,1,?,?,?) ON CONFLICT(em_id,attention_id,ip_key) DO UPDATE SET
            origin_attention_id=excluded.origin_attention_id,fr_key=excluded.fr_key,em_number=excluded.em_number,
            active=1,updated_by=excluded.updated_by,updated_at=excluded.updated_at,reason=excluded.reason''',
            (entry['id'],aid,signature[0],signature[1],ip,values[0],username,r.reception_now(),reason))
    r._write_history(connection,shipment_id,'COBERTURA EM',f"em:{entry['id']}:attentions",
        json.dumps(sorted(x['attention_id'] for x in previous)),json.dumps(sorted(ids)),username,
        f'EM {values[0]}; IP {ip}; {reason}')
    return True
