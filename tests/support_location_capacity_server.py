"""Disposable location master and SAP-like defaults; no production services."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / 'qa' / 'runtime'
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='wms-capacity-qa-', dir=runtime))
os.environ['TRITON_AUTH_MODE'] = 'demo'
os.environ['TRITON_MAIL_ENABLED'] = '0'
os.environ['TRITON_DB_PATH'] = str(scratch / 'qa.sqlite')
os.environ['WMS_BRAND_LOGO_DIR'] = str(Path(sys.argv[2]).resolve())

from backend import app
from backend.services import location_capacity as capacity
from backend.wsgi import serve

app.DB_PATH = scratch / 'qa.sqlite'
app.init_db()
stamp = '2026-10-14T09:00:00'
with app.db() as connection:
    payload = {'text':'\n'.join(f'01-{index:02d}-A-01-01' for index in range(1,116))}
    checked = capacity.preview(connection, payload, 'ADMINISTRADOR')
    capacity.save_master(connection, {**payload,**checked,'reason':'Fixture inicial de prueba'}, 'qa.admin','ADMINISTRADOR')
    for index, location in enumerate(['01-01-A-01-01','01-02-A-01-01','QA-NOT-MAPPED',''], 1):
        connection.execute('''INSERT INTO inventory_stock
            (item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,snapshot_at,
             source_file,default_location,is_current,updated_at)
             VALUES (?,'1',?,'1',2,'2026-10-14',?,'qa.xlsx',?,1,?)''',
            (f'QANP{index}',f'QA-NP-{index}',stamp,location,stamp))
print(f'QA ONLY http://127.0.0.1:{sys.argv[1]}/locations', flush=True)
serve('127.0.0.1', int(sys.argv[1]))
