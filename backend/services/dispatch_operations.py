"""Typed dispatch documents over the existing WMS order and reservation ledger."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import math
from datetime import date


def clean(value, label, limit):
    value = str(value or '').strip()
    if not value or len(value) > limit:
        raise ValueError(f'{label}: indica un valor de hasta {limit} caracteres.')
    return value


def amount(value, minimum=0):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError('Cantidad no válida.') from None
    if not math.isfinite(result) or result < minimum:
        raise ValueError('Cantidad fuera del rango permitido.')
    return result


def signed_photo(payload):
    if not isinstance(payload, dict) or payload.get('recipient_signed') is not True or payload.get('warehouse_signed') is not True:
        raise ValueError('Confirma que la guía muestra las firmas del receptor y del almacén.')
    mime = payload.get('mime_type')
    if mime not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValueError('Adjunta una foto JPG, PNG o WEBP de la guía firmada.')
    try:
        image = base64.b64decode(str(payload.get('image_base64') or '').split(',')[-1], validate=True)
    except (ValueError, TypeError):
        raise ValueError('La foto de la guía no tiene un formato válido.') from None
    if not image or len(image) > 8 * 1024 * 1024:
        raise ValueError('La foto debe tener un tamaño máximo de 8 MB.')
    signatures = {'image/png': image.startswith(b'\x89PNG\r\n\x1a\n'),
                  'image/jpeg': image.startswith(b'\xff\xd8\xff'),
                  'image/webp': image[:4] == b'RIFF' and image[8:12] == b'WEBP'}
    if not signatures[mime]:
        raise ValueError('El archivo no coincide con el formato de imagen indicado.')
    return mime, image


def init_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS dispatch_branches(code TEXT PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dispatch_context(
            sap_ov TEXT PRIMARY KEY REFERENCES orders(sap_ov),kind TEXT NOT NULL,
            destination TEXT NOT NULL DEFAULT '',area TEXT NOT NULL DEFAULT '',equipment TEXT NOT NULL DEFAULT '',
            source_reference TEXT NOT NULL DEFAULT '',local_created INTEGER NOT NULL DEFAULT 0,
            request_key TEXT UNIQUE,request_hash TEXT,created_by TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dispatch_reads(
            attention_line_id INTEGER PRIMARY KEY REFERENCES attention_lines(id),
            code TEXT NOT NULL,quantity REAL NOT NULL,method TEXT NOT NULL,reason TEXT NOT NULL,
            scanned_by TEXT NOT NULL,scanned_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dispatch_shipping_info(
            attention_id INTEGER PRIMARY KEY REFERENCES attentions(id),guide_reference TEXT NOT NULL,
            updated_by TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dispatch_shipments(
            attention_id INTEGER PRIMARY KEY REFERENCES attentions(id),destination TEXT NOT NULL,
            guide_reference TEXT NOT NULL,shipped_at TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'EN TRANSITO',
            received_at TEXT,received_by TEXT);
        CREATE TABLE IF NOT EXISTS dispatch_receipts(
            request_key TEXT PRIMARY KEY,attention_id INTEGER NOT NULL REFERENCES attentions(id),
            request_hash TEXT NOT NULL,receiver TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dispatch_receipt_lines(
            request_key TEXT NOT NULL REFERENCES dispatch_receipts(request_key),
            attention_line_id INTEGER NOT NULL REFERENCES attention_lines(id),quantity REAL NOT NULL,
            PRIMARY KEY(request_key,attention_line_id));
        CREATE TABLE IF NOT EXISTS dispatch_receipt_evidence(
            request_key TEXT PRIMARY KEY REFERENCES dispatch_receipts(request_key),
            file_name TEXT NOT NULL,mime_type TEXT NOT NULL,image_bytes BLOB NOT NULL,
            uploaded_by TEXT NOT NULL,uploaded_at TEXT NOT NULL);

    ''')


def _admin(role):
    if role != 'ADMINISTRADOR':
        raise PermissionError('Esta acción corresponde al administrador.')


def save_branch(db, payload, username, role):
    _admin(role)
    code=clean(payload.get('code'),'Código de sucursal',30).upper()
    name=clean(payload.get('name'),'Nombre de sucursal',100)
    if code in {'01','1'}:
        raise ValueError('El almacén 01 es el origen; registra una sucursal diferente.')
    db.execute('INSERT INTO dispatch_branches VALUES(?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name',(code,name))
    return {'code':code,'name':name}


def set_context(db, code, payload, username, role):
    _admin(role)
    if not db.execute('SELECT 1 FROM orders WHERE sap_ov=?',(code,)).fetchone():
        raise ValueError('Documento no encontrado.')
    kind=payload.get('kind','OV')
    if kind not in {'OV','INTERNA','STS'}:
        raise ValueError('Selecciona OV, pedido interno o STS.')
    old=db.execute('SELECT * FROM dispatch_context WHERE sap_ov=?',(code,)).fetchone()
    started=db.execute('SELECT 1 FROM attentions WHERE sap_ov=?',(code,)).fetchone()
    if (old['kind'] if old else 'OV') != kind and started:
        raise ValueError('El tipo de documento no puede cambiar después de iniciar una atención.')
    destination=str(payload.get('destination') or '').strip().upper()
    if old and old['kind']=='STS' and destination!=old['destination'] and started:
        raise ValueError('La sucursal no puede cambiar después de iniciar una atención.')
    area=str(payload.get('area') or '').strip()
    equipment=str(payload.get('equipment') or '').strip()
    if len(area)>100 or len(equipment)>100:
        raise ValueError('Área o equipo demasiado largo.')
    if kind=='STS' and not db.execute('SELECT 1 FROM dispatch_branches WHERE code=?',(destination,)).fetchone():
        raise ValueError('Selecciona una sucursal registrada.')
    if kind=='INTERNA' and not area:
        raise ValueError('Indica el área interna solicitante.')
    reference=str(payload.get('source_reference') or '').strip()
    if len(reference)>120:
        raise ValueError('Referencia demasiado larga.')
    db.execute('''INSERT INTO dispatch_context(sap_ov,kind,destination,area,equipment,source_reference,created_by,updated_at)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(sap_ov) DO UPDATE SET kind=excluded.kind,destination=excluded.destination,
        area=excluded.area,equipment=excluded.equipment,source_reference=excluded.source_reference,updated_at=excluded.updated_at''',
        (code,kind,destination,area,equipment,reference,username,datetime.now(ZoneInfo('America/Lima')).isoformat(timespec='seconds')))
    # The context changes classification, never creates a second demand line.
    from backend import app
    app.write_history(db,code,'CLASIFICACION','canal',old['kind'] if old else 'OV',kind,username)
    return context(db,code)


def context(db, code):
    row=db.execute('SELECT * FROM dispatch_context WHERE sap_ov=?',(code,)).fetchone()
    return dict(row) if row else {'sap_ov':code,'kind':'OV','destination':'','area':'','equipment':'','source_reference':''}


def create_request(app, payload, username, role):
    _admin(role)
    key=clean(payload.get('request_key'),'Identificador de solicitud',100)
    kind=payload.get('kind')
    if kind not in {'STS','INTERNA'}:
        raise ValueError('Las OV se cargan desde su corte. Aquí crea una STS o un pedido interno.')
    try:
        due=date.fromisoformat(payload.get('due_date')).isoformat()
    except (TypeError, ValueError):
        raise ValueError('Indica una fecha requerida válida.') from None
    destination=str(payload.get('destination') or '').strip().upper()
    lines=payload.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=500 or any(not isinstance(line,dict) for line in lines):
        raise ValueError('Registra entre 1 y 500 NP.')
    normalized=[];seen=set()
    for line in lines:
        code=clean(line.get('item_code'),'NP',120).upper()
        if code in seen:
            raise ValueError('Unifica la cantidad de cada NP; el listado contiene un duplicado.')
        seen.add(code)
        normalized.append({'item_code':code,'quantity':amount(line.get('quantity'),minimum=1e-9)})
    canonical={'kind':kind,'destination':destination,'area':str(payload.get('area') or '').strip(),
               'equipment':str(payload.get('equipment') or '').strip(),'due_date':due,
               'source_reference':str(payload.get('source_reference') or '').strip(),'lines':normalized}
    fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    with app.db() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT * FROM dispatch_context WHERE request_key=?',(key,)).fetchone()
        if existing:
            if existing['created_by']!=username:
                raise PermissionError('La solicitud pertenece a otro usuario.')
            if existing['request_hash']!=fingerprint:
                raise ValueError('La misma solicitud ya se guardó con otros datos. Actualiza antes de repetir.')
            return context(db,existing['sap_ov'])
        prefix=('STS' if kind=='STS' else 'INT')+'-'+app.now()[:10].replace('-','')[2:]+'-'
        sequence=db.execute('SELECT COUNT(*) FROM orders WHERE sap_ov LIKE ?',(prefix+'%',)).fetchone()[0]+1
        reference=prefix+str(sequence).zfill(4)
        stamp=app.now()
        db.execute('''INSERT INTO orders(sap_ov,customer_name,delivery_date,source_order_date,destination,
            app_status,source_present,created_at,updated_at) VALUES(?,?,?,?,?,'PENDIENTE',1,?,?)''',
            (reference,destination if kind=='STS' else canonical['area'],due,stamp[:10],destination,stamp,stamp))
        set_context(db,reference,canonical,username,role)
        for index,line in enumerate(normalized,1):
            item=db.execute('SELECT description,snapshot_qty FROM inventory_stock WHERE upper(trim(item_code))=? AND warehouse_key=? AND is_current=1 LIMIT 1',
                            (line['item_code'],'1')).fetchone()
            if not item:
                raise ValueError('El NP '+line['item_code']+' no figura en el catálogo de stock. Carga el corte vigente.')
            db.execute('''INSERT INTO order_lines(sap_ov,source_row,item_code,description,required_qty,pending_qty,available_qty,warehouse)
                VALUES(?,?,?,?,?,?,?,'1')''',(reference,index,line['item_code'],item['description'] or '',line['quantity'],line['quantity'],item['snapshot_qty']))
        db.execute('UPDATE dispatch_context SET request_key=?,request_hash=?,local_created=1 WHERE sap_ov=?',(key,fingerprint,reference))
        app.write_history(db,reference,'CREACION','tipo','',kind,username)
        return context(db,reference)


def _picker(app, aid, username, role):
    with app.db() as db:
        attention=db.execute('SELECT * FROM attentions WHERE id=?',(aid,)).fetchone()
    if not attention:
        raise ValueError('Atención no encontrada.')
    if role not in {'PICKER','PICKER_GUIADOR'} or not app.same_username(username,attention['current_picker']):
        raise PermissionError('Solo el picker asignado registra las lecturas.')
    if attention['app_status']!='EN PICKING':
        raise ValueError('Inicia el picking antes de verificar NP.')
    return attention


def scan(app, aid, code, username, role, line_id=None):
    _picker(app,aid,username,role)
    code=str(code or '').strip().strip('*').strip().upper()
    if not code or len(code)>180:
        raise ValueError('Escanea o escribe un NP válido.')
    with app.db() as db:
        candidates=[dict(r) for r in db.execute('SELECT * FROM attention_lines WHERE attention_id=? AND upper(trim(item_code))=? ORDER BY id',(aid,code))]
    if line_id is not None:
        candidates=[r for r in candidates if r['id']==int(line_id)]
    if not candidates:
        raise ValueError('El NP no corresponde a esta atención.')
    if len(candidates)>1:
        return {'choices':[{'id':r['id'],'name':r['item_code'],'description':r['description'],'required':r['planned_qty'],'picked':r['picked_qty']} for r in candidates]}
    line=candidates[0]
    if line['picked_qty']<=0:
        raise ValueError('El NP no tiene cantidad reservada. Revisa su saldo o registra un parcial.')
    return confirm_line(app,aid,line['id'],line['picked_qty'],'Lectura NP',username,role,code=code)


def confirm_line(app, aid, line_id, quantity, reason, username, role, code=None):
    _picker(app,aid,username,role)
    quantity=amount(quantity)
    if code is None:
        reason=clean(reason,'Confirmación manual',200)
    app.update_attention_line(aid,line_id,'picked_qty',quantity,username,role,dispatch_read={'code':code,'reason':reason})
    return {'line_id':line_id,'quantity':quantity,'conform':True}


def record_read(db, line, quantity, payload, username, timestamp):
    code=payload.get('code')
    db.execute('''INSERT INTO dispatch_reads VALUES(?,?,?,?,?,?,?) ON CONFLICT(attention_line_id) DO UPDATE SET
        code=excluded.code,quantity=excluded.quantity,method=excluded.method,reason=excluded.reason,
        scanned_by=excluded.scanned_by,scanned_at=excluded.scanned_at''',
        (line['id'],code or line['item_code'],quantity,'LECTOR' if code else 'MANUAL',payload['reason'],username,timestamp))
    from backend import app
    app.write_attention_history(db, line['attention_id'], 'VERIFICACION NP', line['item_code'], None,
        str(quantity), username, ('LECTOR: ' if code else 'MANUAL: ') + payload['reason'])


def finish_picking(app, aid, username, role):
    _picker(app,aid,username,role)
    with app.db() as db:
        validate_reads(db,aid)
    return app.change_attention_status(aid,'PICKING FINALIZADO',username,role)


def validate_reads(db, aid):
    missing=db.execute('''SELECT COUNT(*) FROM attention_lines l LEFT JOIN dispatch_reads r ON r.attention_line_id=l.id
        WHERE l.attention_id=? AND l.picked_qty>0 AND (r.attention_line_id IS NULL OR abs(r.quantity-l.picked_qty)>0.000001)''',(aid,)).fetchone()[0]
    if missing:raise ValueError(f'Faltan {missing} NP por escanear o confirmar manualmente.')


def prepare_shipping(db, attention, reference, username, role, timestamp):
    from backend import app
    if role!='ADMINISTRADOR' and (role not in app.GUIDE_ROLES or not app.same_username(username,attention['current_guide'])):
        raise PermissionError('La atención no está asignada a tu usuario.')
    guide=clean(reference,'Guía de envío',120)
    if attention['app_status']=='ENTREGADO':
        saved=db.execute('SELECT guide_reference FROM dispatch_shipping_info WHERE attention_id=?',(attention['id'],)).fetchone()
        if saved and saved[0]==guide:return
        raise ValueError('El envío ya está confirmado. Conserva su guía original.')
    if attention['app_status'] not in {'EN GUIADO','GUIADO FINALIZADO'}:
        raise ValueError('Completa picking e inicia guiado antes de registrar el envío.')
    db.execute('INSERT INTO dispatch_shipping_info VALUES(?,?,?,?) ON CONFLICT(attention_id) DO UPDATE SET guide_reference=excluded.guide_reference,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
               (attention['id'],guide,username,timestamp))


def ship(app, aid, payload, username, role):
    return app.change_attention_status(aid,'ENTREGADO',username,role,shipping_reference=payload.get('guide_reference',''))


def on_delivered(db, attention, username, timestamp):
    """Runs inside the existing delivery transaction: no second stock deduction."""
    info=context(db,attention['sap_ov'])
    if info['kind']=='STS':
        history = db.execute("""SELECT MAX(CASE WHEN new_value='PICKING FINALIZADO' THEN id END),
            COALESCE(MAX(CASE WHEN new_value IN ('EN PICKING','PENDIENTE') THEN id END),0)
            FROM attention_history WHERE attention_id=?""", (attention['id'],)).fetchone()
        if not history[0] or history[0] <= history[1]:
            raise ValueError('Finaliza y valida el picking antes de despachar la STS.')
        guide=db.execute('SELECT guide_reference FROM dispatch_shipping_info WHERE attention_id=?',(attention['id'],)).fetchone()
        if not guide:
            raise ValueError('Registra la guía de envío antes de despachar la STS.')
        db.execute('INSERT OR IGNORE INTO dispatch_shipments(attention_id,destination,guide_reference,shipped_at) VALUES(?,?,?,?)',
                   (attention['id'],info['destination'],guide[0],timestamp))


def shipments(db, code=None):
    where=' WHERE a.sap_ov=?' if code else ''
    rows=db.execute('''SELECT s.*,a.sap_ov FROM dispatch_shipments s JOIN attentions a ON a.id=s.attention_id'''+where+' ORDER BY s.shipped_at DESC',
                    (code,) if code else ()).fetchall()
    result=[]
    for row in rows:
        item=dict(row);item['lines']=[]
        for line in db.execute('SELECT id,item_code,description,picked_qty FROM attention_lines WHERE attention_id=? AND picked_qty>0',(row['attention_id'],)):
            received=db.execute('SELECT COALESCE(SUM(quantity),0) FROM dispatch_receipt_lines WHERE attention_line_id=?',(line['id'],)).fetchone()[0]
            item['lines'].append(dict(line,received_qty=received,pending_qty=max(0,line['picked_qty']-received)))
        item['receipts'] = [dict(receipt) for receipt in db.execute(
            'SELECT r.request_key,r.receiver,r.created_at,r.created_by FROM dispatch_receipts r JOIN dispatch_receipt_evidence e ON e.request_key=r.request_key WHERE r.attention_id=? ORDER BY r.created_at', (row['attention_id'],))]
        result.append(item)
    return result


def receive(app, aid, payload, username, role):
    _admin(role)
    key=clean(payload.get('request_key'),'Identificador de recepción',100)
    receiver=clean(payload.get('receiver'),'Nombre del receptor',120)
    lines=payload.get('lines',[])
    if not isinstance(lines,list) or not 1<=len(lines)<=500 or any(not isinstance(line,dict) for line in lines):
        raise ValueError('Registra al menos un NP recibido.')
    try:
        normalized=[{'id':int(r.get('id', 0)),'quantity':amount(r.get('quantity'),minimum=1e-9)} for r in lines]
    except (TypeError, OverflowError):
        raise ValueError('Línea de recepción no válida.') from None
    if len({r['id'] for r in normalized})!=len(normalized):
        raise ValueError('El listado de recepción contiene líneas duplicadas.')
    evidence = payload.get('evidence')
    mime, image = signed_photo(evidence)
    fingerprint=hashlib.sha256(json.dumps({'attention':aid,'receiver':receiver,'lines':normalized,
        'mime_type':mime,'photo_hash':hashlib.sha256(image).hexdigest()},sort_keys=True).encode()).hexdigest()
    with app.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM dispatch_receipts WHERE request_key=?',(key,)).fetchone()
        if old:
            if old['request_hash']!=fingerprint or old['created_by']!=username:
                raise ValueError('La recepción ya existe con datos diferentes.')
            return shipments(db,db.execute('SELECT sap_ov FROM attentions WHERE id=?',(aid,)).fetchone()[0])
        shipment=db.execute('SELECT s.*,a.sap_ov FROM dispatch_shipments s JOIN attentions a ON a.id=s.attention_id WHERE s.attention_id=?',(aid,)).fetchone()
        if not shipment:
            raise ValueError('No existe un envío confirmado para esta atención.')
        pending={line['id']:line['pending_qty'] for item in shipments(db,shipment['sap_ov']) if item['attention_id']==aid for line in item['lines']}
        for row in normalized:
            if row['id'] not in pending or row['quantity']>pending[row['id']]+1e-6:
                raise ValueError('La recepción excede lo enviado o incluye un NP ajeno.')
        stamp=app.now()
        db.execute('INSERT INTO dispatch_receipts VALUES(?,?,?,?,?,?)',(key,aid,fingerprint,receiver,username,stamp))
        db.executemany('INSERT INTO dispatch_receipt_lines VALUES(?,?,?)',[(key,r['id'],r['quantity']) for r in normalized])
        db.execute('INSERT INTO dispatch_receipt_evidence VALUES(?,?,?,?,?,?)',
            (key, str(evidence.get('file_name') or 'guia_firmada.jpg')[:180], mime, image, username, stamp))
        remaining=sum(r['pending_qty'] for item in shipments(db,shipment['sap_ov']) if item['attention_id']==aid for r in item['lines'])
        state='RECIBIDO' if remaining<1e-6 else 'RECEPCION PARCIAL'
        db.execute('UPDATE dispatch_shipments SET state=?,received_at=?,received_by=? WHERE attention_id=?',
                   (state,stamp if state=='RECIBIDO' else None,username,aid))
        app.write_attention_history(db,aid,'RECEPCION SUCURSAL','estado',shipment['state'],state,username,receiver)
        return shipments(db,shipment['sap_ov'])
