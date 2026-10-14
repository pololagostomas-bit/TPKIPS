"""Loopback-only fixture. Fictitious public tokens, no network workers or email."""
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / 'qa/runtime'
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='wms-transfer-qa-',dir=runtime))
os.environ.update(TRITON_AUTH_MODE='local',TRITON_DB_PATH=str(scratch / 'qa.sqlite'),
    TRITON_BOOTSTRAP_ADMIN_USERNAME='qa.reader',TRITON_BOOTSTRAP_ADMIN_PASSWORD='QA-password-only-123!',
    TRITON_COOKIE_SECURE='0',WMS_CLOUD_AUTO_SYNC='0',WMS_PURCHASE_ALERT_WORKER='0',
    WMS_DHL_ENABLED='0',TRITON_MAIL_ENABLED='0',WMS_TRANSFER_WORKER='0')
from backend import app, password_policy, wsgi
from backend.services import reception_transfer as transfer
from backend.services import cloud_auth
cloud_auth.status = lambda: {'authorized':True,'mail_username':'sender@example.test'}

password_policy.prepare()
with app.db() as db:
    for i, letter in enumerate('AB',1):
        sid = db.execute("""INSERT INTO reception_shipments(bl_awb,app_status,em_number,created_at,updated_at)
            VALUES(?,'SOLICITUD TRANSFERENCIA','QA-EM','2026-10-13','2026-10-13')""",('QA-TRANSFER-'+str(i),)).lastrowid
        aid = db.execute("""INSERT INTO reception_attentions(shipment_id,sequence_no,app_status,condition_status,created_at,updated_at)
            VALUES(?,1,'SOLICITUD TRANSFERENCIA','EN PROCESO','2026-10-13','2026-10-13')""",(sid,)).lastrowid
        transfer.enqueue(db,sid,aid)
        db.execute("""UPDATE reception_transfer_requests SET status='ACCEPTED',token_hash=?,expires_at=?
            WHERE shipment_id=?""",(hashlib.sha256((letter*43).encode()).hexdigest(),time.time()+3600 if letter=='A' else time.time()-1,sid))
wsgi.application = password_policy.application
print('QA ONLY http://127.0.0.1:'+sys.argv[1],flush=True)
wsgi.serve('127.0.0.1',int(sys.argv[1]))
