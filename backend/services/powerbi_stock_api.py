"""Bounded delegated BI reads. Private mapping, never a Graph token fallback."""
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import requests
from backend.services import cloud_auth

BI_SCOPE='https://analysis.windows.net/powerbi/api/Dataset.Read.All'
MAX_ROWS=75000
MAX_BYTES=15*1024*1024
FIELDS=('warehouse','item_code','description','location','quantity')


class StockError(ValueError):
    def __init__(self,code='api_error',retry_after=300):
        super().__init__(code)
        self.code=code;self.retry_after=retry_after


def enabled():return os.getenv('POWERBI_STOCK_ENABLED','0')=='1'


def config_path():
    return Path(os.getenv('POWERBI_STOCK_CONFIG_PATH') or
                str(Path(os.getenv('TRITON_DB_PATH','data/triton.db')).parent/'powerbi-stock.json'))


def private_mapping():
    try:
        path=config_path()
        if path.stat().st_size>16384:raise StockError('configuration')
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise StockError('configuration')
        return data
    except (OSError,ValueError):raise StockError('configuration') from None


def identifier_state(value):
    if not value:return 'missing'
    try:UUID(str(value));return 'declared'
    except (ValueError,TypeError,AttributeError):return 'invalid'


def load_configuration():
    data=private_mapping()
    if identifier_state(data.get('dataset_id'))!='declared':raise StockError('configuration')
    if data.get('storage_mode')!='Import' or data.get('quantity_kind')!='physical_by_bin':raise StockError('configuration')
    columns=data.get('columns')
    if not isinstance(columns,dict) or set(columns)!=set(FIELDS):raise StockError('configuration')
    for name in [data.get('table'),*columns.values()]:
        if not isinstance(name,str) or not name.strip() or len(name)>120 or any(c in name for c in "'\"[]{}();") or any(ord(c)<32 for c in name):
            raise StockError('configuration')
    config={key:data[key] for key in ('dataset_id','table','columns','storage_mode','quantity_kind')}
    config['dataset_id']=str(UUID(config['dataset_id']))
    config['fingerprint']=hashlib.sha256(json.dumps(config,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    return config


def _access_token():
    try:
        with cloud_auth.locked():
            app,cache=cloud_auth.client()
            selected=cloud_auth.read_state('account.json').get('home_account_id')
            account=next((a for a in app.get_accounts() if a.get('home_account_id')==selected),None)
            if not account:raise StockError('authorization_required')
            result=app.acquire_token_silent([BI_SCOPE],account=account)
            cloud_auth.save_cache(cache)
            if not result or not result.get('access_token'):raise StockError('authorization_required')
            return result['access_token']
    except cloud_auth.CloudAuthError as error:
        raise StockError('busy' if error.code=='busy' else 'authorization_required') from None
    except requests.RequestException:raise StockError('network') from None


def utc_time(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if not dt.tzinfo:raise ValueError()
        return dt.astimezone(timezone.utc)
    except (ValueError,TypeError):raise StockError('invalid_refresh') from None


class Client:
    def __init__(self,config):
        self.config=config;self.token=None
        self.root='https://api.powerbi.com/v1.0/myorg/datasets/'+config['dataset_id']

    def _call(self,path,body=None):
        if self.token is None:self.token=_access_token()
        response=None
        try:
            response=requests.request('POST' if body is not None else 'GET',self.root+path,
                headers={'Authorization':'Bearer '+self.token,'Accept':'application/json'},
                json=body,timeout=(5,35),allow_redirects=False,stream=True)
            if response.status_code!=200:
                code={401:'authorization_required',403:'forbidden',404:'model_missing',429:'throttled'}.get(response.status_code,'api_error')
                try:retry=max(300,min(86400,float(response.headers.get('Retry-After','300'))))
                except (ValueError,TypeError):retry=300
                if not math.isfinite(retry):retry=300
                raise StockError(code,retry)
            if 'json' not in response.headers.get('Content-Type','').lower():raise StockError('protocol')
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>MAX_BYTES:raise StockError('partial')
                chunks.append(chunk)
            data=json.loads(b''.join(chunks))
            if not isinstance(data,dict) or data.get('error'):raise StockError('api_error')
            for result in data.get('results',[]):
                if not isinstance(result,dict) or result.get('error'):raise StockError('partial')
                for table in result.get('tables',[]):
                    if not isinstance(table,dict) or table.get('error'):raise StockError('partial')
            return data
        except requests.RequestException:raise StockError('network') from None
        except (ValueError,TypeError,KeyError) as error:
            if isinstance(error,StockError):raise
            raise StockError('protocol') from None
        finally:
            if response is not None:response.close()

    def refresh(self):
        rows=self._call('/refreshes?$top=1').get('value')
        if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):raise StockError('invalid_refresh')
        row=rows[0]
        if row.get('status')!='Completed':raise StockError('refresh_pending')
        start,end=utc_time(row.get('startTime')),utc_time(row.get('endTime'))
        if start>end or end>datetime.now(timezone.utc)+timedelta(minutes=5):raise StockError('invalid_refresh')
        identity=json.dumps([row.get('requestId') or row.get('id'),start.isoformat(),end.isoformat()])
        return {'key':hashlib.sha256(identity.encode()).hexdigest(),'started_at':start.isoformat(),
                'completed_at':end.isoformat()}

    def _projection(self):
        table="'"+self.config['table']+"'"
        column=lambda key:table+'['+self.config['columns'][key]+']'
        fields=', '.join('"'+key+'", '+column(key) for key in FIELDS)
        return 'DISTINCT(SELECTCOLUMNS(FILTER('+table+', TRIM('+column('warehouse')+') IN {"01", "1"}), '+fields+'))'

    def _rows(self,query):
        data=self._call('/executeQueries',{'queries':[{'query':query}],'serializerSettings':{'includeNulls':True}})
        results=data.get('results')
        if not isinstance(results,list) or len(results)!=1:raise StockError('partial')
        tables=results[0].get('tables')
        if not isinstance(tables,list) or len(tables)!=1 or not isinstance(tables[0].get('rows'),list):raise StockError('partial')
        return tables[0]['rows']

    def read_rows(self,marker):
        projection=self._projection()
        counts=self._rows('EVALUATE ROW("row_count", COALESCE(COUNTROWS('+projection+'),0))')
        expected=counts[0].get('[row_count]') if len(counts)==1 and isinstance(counts[0],dict) else None
        if type(expected) is not int or not 0<expected<=MAX_ROWS:raise StockError('partial')
        rows=self._rows('EVALUATE '+projection)
        if len(rows)!=expected:raise StockError('partial')
        mapped=[]
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'['+key+']' for key in FIELDS}:raise StockError('partial')
            item={key:row['['+key+']'] for key in FIELDS}
            if not isinstance(item['warehouse'],str) or item['warehouse'].strip() not in {'01','1'}:raise StockError('partial')
            if not isinstance(item['item_code'],str) or not item['item_code'].strip():raise StockError('partial')
            if any(item[key] is not None and not isinstance(item[key],str) for key in ('location','description')):raise StockError('partial')
            mapped.append(item)
        if self.refresh()!=marker:raise StockError('model_changed')
        return mapped
