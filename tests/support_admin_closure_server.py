"""Disposable admin closure browser fixture. No corporate data or integrations."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix='wms-admin-closure-qa-'))
os.environ.update(TRITON_AUTH_MODE='demo', TRITON_MAIL_ENABLED='0',
    TRITON_DB_PATH=str(scratch/'qa.sqlite'), WMS_CLOUD_AUTO_SYNC='0',
    WMS_PURCHASE_ALERT_WORKER='0', WMS_TRANSFER_WORKER='0', WMS_DHL_ENABLED='0')
from backend import app
from backend.services import reception
from backend.wsgi import serve
from tests.test_reception_partial_count_http import seed_partial

app.DB_PATH = scratch/'qa.sqlite'
app.init_db()
with app.db() as db:
    for index in range(1, 7):
        db.execute('''INSERT INTO reception_shipments(bl_awb,app_status,condition_status,
            created_at,updated_at) VALUES (?,'PROGRAMADO','POR ARRIBAR',?,?)''',
            (f'QA-ADMIN-PHANTOM-{index}', reception.reception_now(), reception.reception_now()))
        for kind in ('DOC', 'PARTIAL'):
            sid, aid, ids = seed_partial(db, f'QA-ADMIN-{kind}-{index}')
            rid = db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,received_at,username,location_text)
                VALUES (?,1,1,'2026-10-20 08:00:00','demo.admin','QA-ZONE')''', (sid,)).lastrowid
            db.execute('''UPDATE reception_attentions SET receipt_id=?,current_assistant='demo.admin',
                current_auxiliary='demo.admin',system_quantities_initialized=1 WHERE id=?''', (rid, aid))
            db.execute('''UPDATE reception_shipments SET current_assistant='demo.admin',
                current_auxiliary='demo.admin' WHERE id=?''', (sid,))
            if kind == 'DOC':
                db.execute('UPDATE reception_lines SET ip_reference=? WHERE shipment_id=?', ('QA-IP', sid))
                db.execute('''INSERT INTO reception_accounting_refs
                    (shipment_id,source_key,ip_reference,fr_number,em_number,created_at,updated_at)
                    VALUES (?,?,?,'QA-FR','QA-EM',?,?)''', (sid, 'qa-'+str(sid), 'QA-TYPO',
                    reception.reception_now(), reception.reception_now()))
            else:
                db.execute('''UPDATE reception_attention_lines SET verified_qty=0,
                    np_unreceived_reason='Not received in this delivery'
                    WHERE attention_id=? AND reception_line_id=?''', (aid, ids[-1]))
                reception._sync_reception_line_totals(db, sid)
print('QA ONLY '+str(scratch), flush=True)
serve('127.0.0.1', int(sys.argv[1]))
