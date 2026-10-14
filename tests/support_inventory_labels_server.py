"""Disposable inventory/label fixture. No production DB, mail, sync or workers."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / 'qa' / 'runtime'
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='wms-inventory-labels-', dir=runtime))
os.environ['TRITON_AUTH_MODE'] = 'demo'
os.environ['TRITON_MAIL_ENABLED'] = '0'
os.environ['TRITON_DB_PATH'] = str(scratch / 'qa.sqlite')
if len(sys.argv) > 2:
    os.environ['WMS_BRAND_LOGO_DIR'] = str(Path(sys.argv[2]).resolve())

from backend import app
from backend.services.daily_operations import item_key
from backend.wsgi import serve

app.DB_PATH = scratch / 'qa.sqlite'
app.init_db()
stamp = '2026-10-14 09:00:00'
with app.db() as connection:
    sid = connection.execute('''INSERT INTO reception_shipments(bl_awb,created_at,updated_at)
                               VALUES ('QA-INVENTORY-PRIVATE',?,?)''', (stamp, stamp)).lastrowid
    for code, description, brand, qty, location in [
        ('ICM/2022-273.a', 'Repuesto industrial para mantenimiento', 'BOBCAT EUROPA', 2, '01-22-B-11-01'),
        ('31EE-02110', 'ELEMENT-BREATHER', 'HYUNDAI', 4, '01-02-A-01-01'),
        ('NP-NOSTOCK', 'Filtro de repuesto sin stock', 'CROWN INDIA', 0, 'STALE-LOCATION'),
        ('NP-LONG', 'Repuesto industrial de prueba con descripcion extensa ' * 4, 'LIEBHERR', 3, '01-LONG-LOCATION-02'),
    ]:
        connection.execute('''INSERT INTO inventory_stock
            (item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,
             snapshot_at,source_file,default_location,is_current,updated_at)
            VALUES (?,'1',?,'1',?,'2026-10-14',?,'qa.xlsx',?,1,?)''',
            (item_key(code), code, qty, stamp, location, stamp))
        connection.execute('''INSERT INTO inventory_governance_items
            (item_key,item_code,description,created_by,created_at) VALUES (?,?,?,'qa',?)''',
            (item_key(code), code, description, stamp))
        connection.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,brand,description,ov_number,customer_name)
            VALUES (?,?,?,?,'PRIVATE-OV','PRIVATE-CUSTOMER')''', (sid, code, brand, description))
    connection.execute('''INSERT INTO inventory_governance_barcodes
        (item_key,item_code,barcode,barcode_key,symbology,created_by,created_at)
        VALUES ('ICM2022273A','ICM/2022-273.a','WMS-ICM2022273A','WMSICM2022273A','CODE39','qa',?)''', (stamp,))
print('QA ONLY http://127.0.0.1:' + sys.argv[1] + '/inventory', flush=True)
serve('127.0.0.1', int(sys.argv[1]))
