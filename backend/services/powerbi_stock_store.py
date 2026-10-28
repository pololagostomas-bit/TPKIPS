"""Local BI cut metadata and warehouse01 inventory activation; no network."""
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from backend.services.daily_operations import local_now, normalize_cutoff, record_import
from backend.services.powerbi_stock_api import StockError

SOURCE_FILE='Stock Power BI'


def init_schema(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS powerbi_stock_state(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
    connection.execute('''CREATE TABLE IF NOT EXISTS powerbi_stock_locations(
        item_key TEXT NOT NULL,warehouse_key TEXT NOT NULL,location TEXT NOT NULL,
        quantity REAL NOT NULL,cutoff_at TEXT NOT NULL,
        PRIMARY KEY(item_key,warehouse_key,location))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS powerbi_stock_items(
        item_code_key TEXT PRIMARY KEY,item_key TEXT NOT NULL,item_code TEXT NOT NULL,
        quantity REAL NOT NULL,default_location TEXT NOT NULL,description TEXT NOT NULL,
        cutoff_at TEXT NOT NULL,locations TEXT NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_bi_stock_item_key ON powerbi_stock_items(item_key)')


def state(connection):
    row=connection.execute('SELECT value FROM powerbi_stock_state WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {}


def update_state(connection,**updates):
    value={**state(connection),**updates}
    connection.execute('INSERT INTO powerbi_stock_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',
                       (json.dumps(value),))
    return value


def latest(connection):
    row=connection.execute("SELECT id,cutoff_at,summary FROM data_imports WHERE source_type='stock' ORDER BY cutoff_at DESC,id DESC LIMIT 1").fetchone()
    if not row:return {}
    try:summary=json.loads(row['summary'])
    except (ValueError,TypeError):summary={}
    return {'id':row['id'],'cutoff_at':row['cutoff_at'],'summary':summary if isinstance(summary,dict) else {}}


def same_cut(current,config,marker):
    summary=current.get('summary',{})
    return summary.get('source_kind')=='powerbi' and summary.get('source_fingerprint')==config['fingerprint'] and summary.get('refresh_key')==marker['key']


def activate(connection,items,config,marker,actor):
    current=latest(connection)
    if same_cut(current,config,marker):return {'state':'unchanged','import_id':current['id'],'cutoff_at':current['cutoff_at']}
    cutoff=normalize_cutoff(marker['started_at'])
    if current and current['cutoff_at']>cutoff:raise StockError('newer_cut')
    summary={'source_kind':'powerbi','source_fingerprint':config['fingerprint'],
        'refresh_key':marker['key'],'refresh_started_at':marker['started_at'],
        'refresh_completed_at':marker['completed_at'],'inventory_skus':len(items),
        'positive_bins':sum(len(item['locations']) for item in items),'stock_updated':True}
    identity={'source_type':'stock','filename':SOURCE_FILE,
        'file_hash':hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=True).encode()).hexdigest(),
        'cutoff_at':cutoff,'loaded_at':local_now(),'username':actor}
    # Avoid resurrecting a cut that an administrator replaced at the same cutoff.
    if connection.execute("SELECT 1 FROM data_imports WHERE source_type='stock' AND cutoff_at=? AND file_hash=?",(cutoff,identity['file_hash'])).fetchone():raise StockError('replaced_cut')
    connection.execute("UPDATE inventory_stock SET is_current=0 WHERE warehouse_key='1'")
    connection.execute("DELETE FROM powerbi_stock_locations WHERE warehouse_key='1'")
    connection.execute('DELETE FROM powerbi_stock_items')
    families=defaultdict(list)
    for item in items:
        families[item['item_key']].append(item)
        connection.execute('INSERT INTO powerbi_stock_items VALUES(?,?,?,?,?,?,?,?)',
            (item['item_code'].upper(),item['item_key'],item['item_code'],item['quantity'],
             item['default_location'],item.get('description',''),cutoff,json.dumps(item['locations'])))
    for variants in families.values():
        item=variants[0]
        # Legacy normalized keys are compatibility indexes only. Never give a
        # caller that did not resolve the exact BI code another article's stock.
        if len(variants)>1:item={**item,'quantity':0,'default_location':'','description':'','locations':[]}
        connection.execute('''INSERT INTO inventory_stock
            (item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,snapshot_at,source_file,
             default_location,is_current,updated_at,description) VALUES (?,'1',?,'01',?,?,?,?,?,1,?,?)
            ON CONFLICT(item_key,warehouse_key) DO UPDATE SET item_code=excluded.item_code,warehouse=excluded.warehouse,
            snapshot_qty=excluded.snapshot_qty,snapshot_day=excluded.snapshot_day,snapshot_at=excluded.snapshot_at,
            source_file=excluded.source_file,default_location=excluded.default_location,is_current=1,
            updated_at=excluded.updated_at,description=excluded.description''',
            (item['item_key'],item['item_code'],item['quantity'],cutoff[:10],cutoff,SOURCE_FILE,
             item['default_location'],identity['loaded_at'],item.get('description','')))
        connection.executemany('INSERT INTO powerbi_stock_locations VALUES(?,\'1\',?,?,?)',
            [(item['item_key'],bin['location'],bin['quantity'],cutoff) for bin in item['locations']])
    record_import(connection,identity,summary)
    import_id=connection.execute('SELECT last_insert_rowid()').fetchone()[0]
    return {'state':'updated','import_id':import_id,'cutoff_at':cutoff,
            'inventory_skus':len(items),'positive_bins':summary['positive_bins']}


def snapshot(connection,code,warehouse='1'):
    """Exact BI identity, or an authoritative zero for an unknown BI code.

    None means a manual/legacy source owns the current cut. No matching by
    punctuation-stripped keys, no inventory/allocation/history mutations.
    """
    if warehouse not in {'1','01'}:return None
    try:
        row=connection.execute('''SELECT s.*,b.item_code AS bi_code,b.quantity AS bi_quantity,
            b.default_location AS bi_location,b.description AS bi_description
            FROM powerbi_stock_items b JOIN inventory_stock s ON s.item_key=b.item_key
            AND s.warehouse_key='1' AND s.is_current=1 AND s.snapshot_at=b.cutoff_at
            AND s.source_file=? WHERE b.item_code_key=?''',(SOURCE_FILE,str(code).strip().upper())).fetchone()
        if row:
            return {**dict(row),'item_code':row['bi_code'],'snapshot_qty':row['bi_quantity'],
                'default_location':row['bi_location'],'description':row['bi_description'],
                'exact_code':str(code).strip().upper()}
        cut=latest(connection)
        if cut.get('summary',{}).get('source_kind')!='powerbi':return None
        from backend.services.daily_operations import item_key
        return {'item_key':item_key(code),'warehouse_key':'1','item_code':str(code).strip(),
            'warehouse':'01','snapshot_qty':0,'snapshot_day':cut['cutoff_at'][:10],
            'snapshot_at':cut['cutoff_at'],'source_file':SOURCE_FILE,'default_location':'',
            'is_current':0,'updated_at':cut['cutoff_at'],'description':'','exact_code':str(code).strip().upper()}
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        return None


def inventory_source(connection):
    """SQL projection for reports that count current warehouse01 stock rows."""
    try:
        if not connection.execute('SELECT 1 FROM powerbi_stock_items LIMIT 1').fetchone():return None
        source='''SELECT b.item_code_key AS item_key,b.quantity AS snapshot_qty,
            b.default_location,b.cutoff_at AS snapshot_at FROM powerbi_stock_items b
            JOIN inventory_stock s ON s.item_key=b.item_key AND s.warehouse_key='1'
            AND s.is_current=1 AND s.snapshot_at=b.cutoff_at AND s.source_file='Stock Power BI' '''
        if not connection.execute('SELECT 1 FROM ('+source+') LIMIT 1').fetchone():return None
        return '('+source+')'
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        return None


def locations(connection,key,code=None):
    try:
        if code is not None:
            row=connection.execute('''SELECT b.locations FROM powerbi_stock_items b
                JOIN inventory_stock s ON s.item_key=b.item_key AND s.warehouse_key='1'
                AND s.is_current=1 AND s.snapshot_at=b.cutoff_at AND s.source_file=?
                WHERE b.item_code_key=?''',(SOURCE_FILE,str(code).strip().upper())).fetchone()
            if row:return json.loads(row[0])
        return [dict(row) for row in connection.execute('''SELECT b.location,b.quantity FROM powerbi_stock_locations b
            JOIN inventory_stock s ON s.item_key=b.item_key AND s.warehouse_key=b.warehouse_key
              AND s.is_current=1 AND s.snapshot_at=b.cutoff_at AND s.source_file=?
            WHERE b.item_key=? AND b.warehouse_key='1' ORDER BY b.quantity DESC,b.location''',(SOURCE_FILE,key))]
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        return []
