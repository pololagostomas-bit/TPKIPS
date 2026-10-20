"""Disposable local-only reception workflow, no external integrations."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix='independent-arrivals-qa-'))
os.environ.update(TRITON_AUTH_MODE='demo', TRITON_DB_PATH=str(scratch / 'qa.sqlite'),
    WMS_CLOUD_AUTO_SYNC='0', WMS_PURCHASE_ALERT_WORKER='0', WMS_TRANSFER_WORKER='0', WMS_DHL_ENABLED='0')
from backend import app
from backend.services import reception
from backend.wsgi import serve

app.init_db()
with app.db() as db:
    for width in (320, 393, 1366, 873):
        sid = db.execute('''INSERT INTO reception_shipments
            (bl_awb,expected_packages,current_assistant,current_auxiliary,created_at,updated_at)
            VALUES (?,4,'demo.recepcion','demo.recepcion','2026-10-19','2026-10-19')''',
            ('QA-ARRIVALS-' + str(width),)).lastrowid
        for np, qty in (('NP-FIRST', 8), ('NP-LATER', 2)):
            db.execute('INSERT INTO reception_lines(shipment_id,np_code,description,expected_qty) VALUES (?,?,?,?)',
                       (sid, np, 'Synthetic spare part', qty))
        for suffix in ('A', 'B'):
            guide = f'QA-{width}-{suffix}'
            reception.plan_truck_bl_packages(db, guide, sid, 1, 'demo.recepcion', 'ADMINISTRADOR')
            reception.confirm_truck_guide(db, guide, guide, 'demo.recepcion', 'ADMINISTRADOR')
            reception.process_truck_guide_arrivals(db, guide, [{'shipment_id': sid, 'received_packages': 1}],
                guide, '', 'demo.recepcion', 'ADMINISTRADOR')
            reception.process_truck_guide_locations(db, guide,
                [{'shipment_id': sid, 'locations': [{'location': 'TEMP-QA', 'package_count': 1}]}],
                'demo.recepcion', 'ADMINISTRADOR')
            db.execute('''INSERT INTO reception_truck_package_scans
                (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
                VALUES (?,?,?,?,?,?)''', (guide, sid, guide+'-PIECE', guide+'-PIECE', 'demo.recepcion', '2026-10-19'))
        db.execute('UPDATE reception_shipments SET truck_guide=? WHERE id=?', (f'QA-{width}-B', sid))
print('Disposable arrivals QA http://127.0.0.1:' + sys.argv[1], flush=True)
serve('127.0.0.1', int(sys.argv[1]))
