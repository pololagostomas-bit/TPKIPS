"""Current source association, separate from immutable arrival/count history."""
import json
import sqlite3


def key(value):return str(value or '').strip().upper()


def ov_key(value):
    value=key(value)
    return '' if value in {'S/N','SN','STOCK','PARA STOCK','N/A','SIN OV'} else value


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_source_bl_state(
        id INTEGER PRIMARY KEY CHECK(id=1),filename TEXT NOT NULL,sheets TEXT NOT NULL,checked_at TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_source_bl_rows(
        source_sheet TEXT NOT NULL,source_row INTEGER NOT NULL,np_code TEXT NOT NULL,
        bl_awb TEXT NOT NULL,ip_reference TEXT NOT NULL,oc_number TEXT NOT NULL,ov_number TEXT NOT NULL,
        PRIMARY KEY(source_sheet,source_row))''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_reception_source_np ON reception_source_bl_rows(np_code)')


def store(connection,rows,sheets,filename,stamp):
    connection.execute('DELETE FROM reception_source_bl_rows')
    connection.executemany('INSERT INTO reception_source_bl_rows VALUES(?,?,?,?,?,?,?)',
        [(r['source_sheet'],r['source_row'],key(r['np_code']),key(r['guide']),key(r['ip']),key(r['oc']),ov_key(r['ov'])) for r in rows])
    connection.execute('''INSERT INTO reception_source_bl_state VALUES(1,?,?,?)
        ON CONFLICT(id) DO UPDATE SET filename=excluded.filename,sheets=excluded.sheets,checked_at=excluded.checked_at''',
        (filename,json.dumps(sheets),stamp))


def _source(connection,lines):
    codes=sorted({key(line['np_code']) for line in lines if line.get('source_key') and line.get('source_sheet')})
    try:state=connection.execute('SELECT * FROM reception_source_bl_state WHERE id=1').fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        state=None
    if state:
        rows=[]
        for start in range(0,len(codes),400):
            batch=codes[start:start+400];marks=','.join('?' for _ in batch)
            rows.extend(dict(r) for r in connection.execute('SELECT * FROM reception_source_bl_rows WHERE np_code IN ('+marks+')',batch))
        return rows,set(json.loads(state['sheets'])),True
    # Older installations already retain the current OV map, including blank BL.
    # It is incomplete for stock/no-OV rows: only use positive evidence there.
    ovs=sorted({str(line.get('ov_number') or '').strip() for line in lines if ov_key(line.get('ov_number'))})
    rows=[]
    try:
        for start in range(0,len(ovs),400):
            batch=ovs[start:start+400];marks=','.join('?' for _ in batch)
            rows.extend({**dict(r),'np_code':key(r['item_code']),'ov_number':ov_key(r['sap_ov'])} for r in
                connection.execute('SELECT * FROM order_importation_refs WHERE sap_ov IN ('+marks+')',batch))
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        rows=[]
    return rows,set(),False


def _source_index(connection,lines):
    from backend.services.reception_line_identity import legacy_ids
    superseded=legacy_ids(connection)
    rows,sheets,complete=_source(connection,lines)
    by_code={}
    for row in rows:
        ov=ov_key(row['ov_number'])
        entry=by_code.setdefault((row['source_sheet'],key(row['np_code']),None if complete else ov),(set(),set()))
        bl=key(row['bl_awb'])
        entry[0].add(bl)
        entry[1].add((bl,key(row['ip_reference']),key(row['oc_number']),ov))
    return superseded,by_code,sheets,complete


def flags(connection,shipment,lines):
    return _flags(shipment,lines,*_source_index(connection,lines))


def _flags(shipment,lines,superseded,by_code,sheets,complete):
    result={}
    for line in lines:
        flag={'source_bl_eligible':True,'source_bl_state':'UNKNOWN','source_bl_message':''}
        if line['id'] in superseded:
            result[line['id']]={'source_bl_eligible':False,'source_bl_state':'SUPERSEDED',
                'source_bl_message':'Antecedente documental conservado; el pedido vigente tiene otro ID interno. Revisa las cantidades antiguas.'}
            continue
        if not line.get('source_key') or not line.get('source_sheet'):
            result[line['id']]=flag;continue
        ov=ov_key(line.get('ov_number'))
        candidates=by_code.get((line['source_sheet'],key(line['np_code']),None if complete else ov))
        if not candidates and not (complete and line['source_sheet'] in sheets):
            result[line['id']]=flag;continue
        bl=key(shipment['bl_awb'])
        bls,matches=candidates if candidates else (set(),set())
        match=(bl,key(line.get('ip_reference')),key(line.get('oc_number')),ov) in matches
        if match:flag.update(source_bl_state='CURRENT')
        else:
            state='ORDER_CHANGED' if bl in bls else 'NO_BL' if '' in bls else 'OTHER_BL' if candidates else 'MISSING'
            flag.update(source_bl_eligible=False,source_bl_state=state,
                source_bl_message='El pedido de este NP no está asignado a esta BL en el corte vigente de Importaciones')
        result[line['id']]=flag
    return result


def expected_ips_for_shipments(connection,shipments):
    """Share one fresh source index for this read, never across requests."""
    from backend.services.reception import _ip_tokens
    if not shipments:return {}
    ids=[shipment['id'] for shipment in shipments]
    lines=[]
    for start in range(0,len(ids),400):
        batch=ids[start:start+400]
        lines.extend(dict(row) for row in connection.execute('''SELECT id,shipment_id,source_key,
            source_sheet,np_code,ip_reference,oc_number,ov_number FROM reception_lines
            WHERE shipment_id IN ('''+','.join('?' for _ in batch)+')',batch))
    index=_source_index(connection,lines)
    grouped={}
    for line in lines:grouped.setdefault(line['shipment_id'],[]).append(line)
    result={}
    for shipment in shipments:
        group=grouped.get(shipment['id'],[])
        states=_flags(shipment,group,*index)
        eligible=[line for line in group if states[line['id']]['source_bl_eligible']]
        ips={ip for line in eligible for ip in _ip_tokens(line['ip_reference'])}
        result[shipment['id']]=(set() if group and not eligible else ips or set(_ip_tokens(shipment['ip_reference'])))
    return result


def annotate(connection,payload):
    states=flags(connection,payload,payload['lines'])
    issues=[]
    for line in payload['lines']:
        line.update(states[line['id']])
        if not line['source_bl_eligible']:
            issues.append({'id':line['id'],'np_code':line['np_code'],'state':line['source_bl_state'],
                'message':line['source_bl_message']})
    payload['source_bl_issues']=issues


def require_line(connection,shipment_id,line):
    shipment=connection.execute('SELECT bl_awb FROM reception_shipments WHERE id=?',(shipment_id,)).fetchone()
    line=dict(line)
    if not flags(connection,dict(shipment),[line])[line['id']]['source_bl_eligible']:
        raise PermissionError('Este NP ya no pertenece a esta BL en Importaciones. Solicita revisión al administrador.')


def excluded_ids(connection,shipment_id):
    shipment=connection.execute('SELECT bl_awb FROM reception_shipments WHERE id=?',(shipment_id,)).fetchone()
    if not shipment:return set()
    lines=[dict(row) for row in connection.execute('SELECT * FROM reception_lines WHERE shipment_id=?',(shipment_id,))]
    return {line_id for line_id,flag in flags(connection,dict(shipment),lines).items() if not flag['source_bl_eligible']}
