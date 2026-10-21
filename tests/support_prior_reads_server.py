"""Loopback-only synthetic overlap fixture; no operating data or workers."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix='wms-prior-read-qa-'))
os.environ.update(TRITON_AUTH_MODE='demo',TRITON_DB_PATH=str(scratch/'qa.db'),TRITON_MAIL_ENABLED='0',
    WMS_CLOUD_AUTO_SYNC='0',WMS_PURCHASE_ALERT_WORKER='0',WMS_TRANSFER_WORKER='0',WMS_DHL_ENABLED='0')
from backend import app
from backend.services import reception
from backend.wsgi import serve

app.DB_PATH = scratch/'qa.db'
app.init_db()
with app.db() as db:
    for number in range(1, 7):
        sid = db.execute('''INSERT INTO reception_shipments
            (bl_awb,app_status,received_packages,fr_number,current_assistant,current_auxiliary,created_at,updated_at)
            VALUES (?,'REVISION SISTEMA',2,'QA-FR','demo.admin','demo.admin','2026-10-21','2026-10-21')''',
            (f'QA-OVERLAP-{number}',)).lastrowid
        for i in range(40):
            db.execute('''INSERT INTO reception_lines
                (shipment_id,np_code,description,ov_number,expected_qty) VALUES (?,?,?,?,1)''',
                (sid,f'QA-NP-{i if i<39 else 37:02d}','Repuesto sintetico',f'QA-OV-{i}'))
        shipment = db.execute('SELECT * FROM reception_shipments WHERE id=?',(sid,)).fetchone()
        old = reception._create_reception_attention(db,shipment,None,'demo.admin','REVISION SISTEMA')['id']
        other = reception._create_reception_attention(db,shipment,None,'demo.admin','REVISION SISTEMA')['id']
        db.execute('''UPDATE reception_attentions SET system_quantities_initialized=1 WHERE shipment_id=?''',(sid,))
        db.execute('''UPDATE reception_attention_lines SET verified_qty=planned_qty,np_quantity_saved=0,
            count_location_saved=1,count_location_manual=1 WHERE attention_id=?''',(old,))
        db.execute('''UPDATE reception_attention_lines SET verified_qty=planned_qty,
            np_scanned_at='2026-10-21 09:00:00',np_scanned_by='demo.admin',
            count_location_saved=1,count_location_manual=1 WHERE attention_id=?
            AND reception_line_id IN (SELECT id FROM reception_lines WHERE shipment_id=? AND np_code<>'QA-NP-38')''',
            (other,sid))
        db.execute('''UPDATE reception_attention_lines SET np_unreceived_reason='Pendiente para otra llegada'
            WHERE attention_id=? AND reception_line_id IN
            (SELECT id FROM reception_lines WHERE shipment_id=? AND np_code='QA-NP-38')''',(other,sid))
        db.execute("UPDATE reception_attentions SET app_status='CERRADO',condition_status='COMPLETADO' WHERE id=?",(other,))
        reception._sync_reception_line_totals(db,sid)
        if number==6:
            db.execute('UPDATE reception_attention_lines SET np_quantity_saved=NULL WHERE attention_id=?',(old,))
print('QA ONLY '+str(scratch),flush=True)
serve('127.0.0.1',int(sys.argv[1]))
