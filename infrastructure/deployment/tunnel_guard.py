"""Linux-only reader tunnel recovery. No app, VM, deployment or mail authority."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener

TUNNEL = 'triton-wms-home-tunnel-1'
APP = 'triton-wms-home-app-1'
PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com\b')


def parse_url(log):
    urls=[]
    for index,line in enumerate(log.splitlines()):
        try:stamp=datetime.fromisoformat(line.split(' ',1)[0].replace('Z','+00:00')).timestamp()
        except ValueError:stamp=0
        urls.extend((stamp,index,url) for url in PATTERN.findall(line))
    return max(urls)[2] if urls else None


def cycle(previous, ops, *, now, maintenance=False):
    state={**previous,'checked_at':now,'link':None,'available':False}
    state['restarts']=[stamp for stamp in previous.get('restarts',[]) if 0<=now-stamp<3600]
    def finish(status, failures=0):
        state.update(status=status,failures=failures)
        return state
    if maintenance:return finish('MAINTENANCE')
    if not ops.local():return finish('LOCAL_APP_UNAVAILABLE')
    try:meta=ops.tunnel()
    except Exception:return finish('CHECK_FAILED')
    generation=meta.get('generation',str(meta['started']))
    failures=int(previous.get('failures',0)) if previous.get('generation')==generation else 0
    state['generation']=generation
    if meta['status'] in {'paused','restarting','removing','dead'}:
        return finish('TUNNEL_BUSY')
    try:url=ops.latest_url(meta['started']) if meta['status']=='running' else None
    except Exception:return finish('CHECK_FAILED')
    if not url and meta['status']=='running' and previous.get('generation')==generation:
        url=previous.get('observed_url')
    state['observed_url']=url
    result=ops.probe(url) if url else 'FAILED'
    if result=='OK':
        state.update(link=url+'/login',available=True,verified_at=now)
        return finish('HEALTHY')
    if result in {'AUTH_REQUIRED','THROTTLED'}:return finish(result)
    if now-meta['started']<120:return finish('STARTING')
    if not ops.network():return finish('NETWORK_UNAVAILABLE')
    failures+=1
    if failures<2:return finish('SUSPECT',failures)
    last=previous.get('last_restart')
    if last is not None and now-last<600:return finish('COOLDOWN',failures)
    if len(state['restarts'])>=3:return finish('BUDGET_EXHAUSTED',failures)
    # Reserve the attempt before invoking Docker, including an ambiguous failure.
    state.update(last_restart=now,restarts=[*state['restarts'],now],status='RESTARTING',failures=failures)
    ops.reserve(state)
    try:
        ops.restart()
    except Exception:
        return finish('RESTART_FAILED',failures)
    return finish('RESTARTED')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Operations:
    def __init__(self,port=8086,reserve=lambda state:None):
        if not 1<=port<=65535:raise ValueError('Puerto local no valido')
        self.port=port
        self.reserve=reserve
        self.opener=build_opener(NoRedirect())

    def read(self,url,limit=1048576):
        with self.opener.open(url,timeout=8) as response:
            if response.status!=200 or response.geturl()!=url:raise ValueError('Respuesta inesperada')
            data=response.read(limit+1)
            if len(data)>limit:raise ValueError('Respuesta demasiado grande')
            return data

    def local(self):
        try:return json.loads(self.read(f'http://127.0.0.1:{self.port}/health',4096)).get('status')=='ok'
        except Exception:return False

    def network(self):
        try:
            self.read('https://www.cloudflare.com/cdn-cgi/trace',16384)
            return True
        except Exception:return False

    def command(self,*args,timeout=15):
        return subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock',*args],check=True,capture_output=True,
                              text=True,encoding='utf-8',errors='replace',timeout=timeout)

    def tunnel(self):
        row=json.loads(self.command('inspect','--format',
            '{"status":"{{.State.Status}}","started":"{{.State.StartedAt}}"}',TUNNEL).stdout)
        row['generation']=row['started']
        row['started']=datetime.fromisoformat(row['started'].replace('Z','+00:00')).timestamp()
        return row

    def latest_url(self,started):
        since=datetime.fromtimestamp(started).astimezone().isoformat()
        logs=self.command('logs','--timestamps','--tail','2000','--since',since,TUNNEL)
        return parse_url(logs.stdout+'\n'+logs.stderr)

    def probe(self,url):
        if not url or PATTERN.fullmatch(url) is None:return 'FAILED'
        try:
            health=json.loads(self.read(url+'/health',4096))
            if health.get('status')!='ok':return 'FAILED'
            return 'OK' if b'triton wms' in self.read(url+'/login').lower() else 'FAILED'
        except HTTPError as error:
            code=error.code
            error.close()
            if code in {301,302,303,307,308,401,403}:return 'AUTH_REQUIRED'
            return 'THROTTLED' if code==429 else 'FAILED'
        except Exception:return 'FAILED'

    def restart(self):
        self.command('restart','--timeout','15',TUNNEL,timeout=30)


@contextmanager
def locked(root):
    import fcntl
    with (root/'guard.lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def save(root,state):
    for name,content in [('status.json',json.dumps(state,indent=2)+'\n'),
                         ('current-link.txt',(state.get('link') or '')+'\n')]:
        temporary=root/(name+'.tmp')
        temporary.write_text(content,encoding='utf-8')
        temporary.replace(root/name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path,default=Path('/var/lib/triton-wms-tunnel'))
    parser.add_argument('--port',type=int,default=8086)
    args=parser.parse_args()
    if os.name!='posix':parser.error('El supervisor se ejecuta en Linux, no en Windows')
    os.umask(0o077)
    root=args.state_dir.resolve()
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        with locked(root):
            path=root/'status.json'
            previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            state=cycle(previous,Operations(args.port,lambda state:save(root,state)),now=time.time(),
                        maintenance=(root/'maintenance').exists())
            save(root,state)
            print(json.dumps(state))
    except BlockingIOError:
        print(json.dumps({'status':'ALREADY_RUNNING'}))
    except Exception:
        # Preserve unknown/corrupt state and restart budget; never reset it silently.
        print(json.dumps({'status':'CHECK_FAILED','available':False}))
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
