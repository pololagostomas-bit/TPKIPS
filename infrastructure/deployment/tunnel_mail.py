"""Notify a verified reader URL change through the existing Microsoft mailbox."""
import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

if __package__:
    from . import tunnel_guard
else:
    import tunnel_guard

REMOTE = """
import json,sys
from backend.services import cloud_auth,purchase_alerts
payload=json.load(sys.stdin)
try:
    token=cloud_auth.access_token(scopes=cloud_auth.MAIL_SCOPES,expected_username=payload.pop('sender'))
except cloud_auth.CloudAuthError:
    print(json.dumps({'state':'BLOCKED'}));sys.exit(0)
if payload.pop('check',False):
    print(json.dumps({'state':'AUTHORIZED'}));sys.exit(0)
try:
    response=purchase_alerts._post_mail(token,payload)
    code=response.status_code
    state=('ACCEPTED' if code==202 else 'THROTTLED' if code==429 else
           'BLOCKED' if code in (401,403) else 'REJECTED' if 400<=code<500 and code!=408 else 'REVIEW')
    print(json.dumps({'state':state,'http_status':code}))
except Exception:
    print(json.dumps({'state':'REVIEW'}))
"""


def configuration(value):
    if not isinstance(value,dict) or set(value)-{'enabled','sender','to','cc'}:
        raise ValueError('Configuracion de correo invalida')
    if not isinstance(value.get('enabled',False),bool):raise ValueError('Activacion invalida')
    def addresses(items,minimum=0):
        if not isinstance(items,list) or not minimum<=len(items)<=10:raise ValueError('Destinatarios invalidos')
        result=[]
        for item in items:
            if not isinstance(item,str) or re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',item) is None:
                raise ValueError('Direccion de correo invalida')
            if item.casefold() not in {entry.casefold() for entry in result}:result.append(item)
        return result
    return {'enabled':value.get('enabled',False),'sender':addresses([value.get('sender')],1)[0],
            'to':addresses(value.get('to'),1),'cc':addresses(value.get('cc',[]))}


def current(state,now):
    try:
        return (state.get('status')=='HEALTHY' and state.get('available') is True
                and re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com/login',state['link']) is not None
                and isinstance(state.get('generation'),str) and bool(state['generation'])
                and all(math.isfinite(float(state[key])) and -5<=now-float(state[key])<=180
                        for key in ('checked_at','verified_at')))
    except (KeyError,TypeError,ValueError):return False


def verify_current(state):
    try:
        ops=tunnel_guard.Operations()
        meta=ops.tunnel()
        return (meta['status']=='running' and meta['generation']==state['generation']
                and ops.probe(state['link'].removesuffix('/login'))=='OK')
    except Exception:return False


def microsoft(config,payload):
    result=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock','exec','-i',
        '--workdir','/app',tunnel_guard.APP,'python','-c',REMOTE],
        input=json.dumps({**payload,'sender':config['sender']}),capture_output=True,
        text=True,encoding='utf-8',timeout=100,check=True)
    return json.loads(result.stdout)


def payload(config,row,now):
    local=datetime.fromtimestamp(now,timezone.utc).astimezone(timezone(timedelta(hours=-5)))
    link=html.escape(row['url'],quote=True)
    return {'subject':'Triton WMS con lector: nuevo enlace disponible',
            'to':config['to'],'cc':config['cc'],
            'html':'<p>El enlace publico del Triton WMS con lector ha cambiado.</p>'
                '<p>El nuevo enlace ya fue comprobado y esta disponible:</p>'
                f'<p><a href="{link}">Abrir Triton WMS</a></p><p>{link}</p>'
                f'<p>Comprobado: {local:%d/%m/%Y %H:%M} (Lima).</p>'
                f'<p>Este aviso se envia solo cuando cambia el enlace. Referencia: {row["event_key"]}.</p>'}


def run(root,config,state,*,now=None,delivery=None,verify=verify_current):
    config=configuration(config)
    if not config['enabled']:return {'state':'DISABLED'}
    now=time.time() if now is None else now
    if not current(state,now):return {'state':'UNAVAILABLE'}
    root=Path(root).resolve();root.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        with tunnel_guard.locked(root):
            return _run_locked(root,config,state,now,delivery or (lambda body:microsoft(config,body)),verify)
    except BlockingIOError:return {'state':'ALREADY_RUNNING'}


def _run_locked(root,config,state,now,delivery,verify):
    path=root/'deliveries.sqlite3'
    with closing(sqlite3.connect(path,timeout=2)) as db,db:
        os.chmod(path,0o600);db.row_factory=sqlite3.Row
        db.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries(id INTEGER PRIMARY KEY,event_key TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,previous_url TEXT NOT NULL,detected_at REAL NOT NULL,state TEXT NOT NULL,
            updated_at REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,
            http_status INTEGER);''')
        previous=db.execute("SELECT value FROM settings WHERE key='last_link'").fetchone()
        row=db.execute('SELECT * FROM deliveries ORDER BY id DESC LIMIT 1').fetchone()
        changed=previous is None or previous[0]!=state['link']
        if not changed:
            if row is None or row['state']=='ACCEPTED':return {'state':'UNCHANGED'}
            if row['state']=='SENDING':
                db.execute("UPDATE deliveries SET state='REVIEW',updated_at=? WHERE id=?",(now,row['id']))
                return {'state':'REVIEW','event_key':row['event_key']}
            if row['state'] in {'REVIEW','REJECTED'}:return {'state':row['state'],'event_key':row['event_key']}
            if row['retry_at']>now:return {'state':'WAITING','event_key':row['event_key']}
        if not verify(state):return {'state':'UNVERIFIED'}
        if changed:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT INTO settings VALUES('last_link',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(state['link'],))
            if previous is None:return {'state':'BASELINED'}
            db.execute("UPDATE deliveries SET state='SUPERSEDED',updated_at=? WHERE state IN ('PENDING','BLOCKED','THROTTLED')",(now,))
            identifier=db.execute('INSERT INTO deliveries(event_key,url,previous_url,detected_at,state,updated_at) '
                "VALUES (?,?,?,?,'PENDING',?)",(uuid.uuid4().hex,state['link'],previous[0],now,now)).lastrowid
            row=db.execute('SELECT * FROM deliveries WHERE id=?',(identifier,)).fetchone()
        else:db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE deliveries SET state='SENDING',attempts=attempts+1,updated_at=? WHERE id=?",(now,row['id']))
        db.commit()  # Durable reservation before any external send, including process interruption.
        try:
            result=delivery(payload(config,row,now))
            if (not isinstance(result,dict) or result.get('state') not in
                    {'ACCEPTED','BLOCKED','THROTTLED','REJECTED','REVIEW'}
                    or result.get('state')=='ACCEPTED' and result.get('http_status')!=202):
                result={'state':'REVIEW'}
        except Exception:result={'state':'REVIEW'}
        status=result['state']
        db.execute('UPDATE deliveries SET state=?,updated_at=?,retry_at=?,http_status=? WHERE id=?',
            (status,now,now+900 if status in {'BLOCKED','THROTTLED'} else 0,result.get('http_status'),row['id']))
        return {'state':status,'event_key':row['event_key'],'http_status':result.get('http_status')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path,default=Path('/var/lib/triton-wms-tunnel-mail'))
    parser.add_argument('--config',type=Path,default=Path('/etc/triton-wms-tunnel-mail.json'))
    parser.add_argument('--guard-state',type=Path,default=Path('/var/lib/triton-wms-tunnel/status.json'))
    parser.add_argument('--check-auth',action='store_true',help='Check existing Mail.Send; never sends.')
    args=parser.parse_args()
    os.umask(0o077)
    try:
        config=configuration(json.loads(args.config.read_text(encoding='utf-8')))
        result=(microsoft(config,{'check':True}) if args.check_auth else
                run(args.state_dir,config,json.loads(args.guard_state.read_text(encoding='utf-8'))))
        print(json.dumps(result))
    except Exception:
        print(json.dumps({'state':'MAIL_CHECK_FAILED'}));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
