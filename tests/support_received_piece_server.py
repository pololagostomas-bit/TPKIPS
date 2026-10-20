"""Loopback-only fixture: three documentary pieces, physical scans start empty."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / 'qa/runtime'
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='received-pieces-', dir=runtime))
key = scratch / 'qa.secret'
key.write_text('fictitious-test-key-not-a-real-key', encoding='ascii')
os.environ.update(TRITON_AUTH_MODE='local', TRITON_DB_PATH=str(scratch / 'qa.sqlite'),
    TRITON_BOOTSTRAP_ADMIN_USERNAME='qa.reader', TRITON_BOOTSTRAP_ADMIN_PASSWORD='QA-password-only-123!',
    TRITON_COOKIE_SECURE='0', WMS_CLOUD_AUTO_SYNC='0', WMS_PURCHASE_ALERT_WORKER='0',
    WMS_TRANSFER_WORKER='0', WMS_DHL_ENABLED='1', DHL_API_KEY_FILE=str(key))

from backend import app, wsgi, password_policy
from backend.services import dhl_tracking as dhl

def no_network(*args, **kwargs):
    raise AssertionError('This fixture must not call DHL')

dhl.fetch_tracking = no_network
app.init_db()
with app.db() as db:
    db.execute("""INSERT INTO reception_shipments
        (bl_awb,transport_type,app_status,created_at,updated_at,current_assistant,current_auxiliary)
        VALUES ('1234567890','COURIER','PROGRAMADO',?,?,'qa.assistant','qa.auxiliary')""",
        (app.local_now(), app.local_now()))
    db.execute("""INSERT INTO dhl_tracking_cache
        (awb,status_code,total_pieces,checked_at,expires_at) VALUES ('1234567890','transit',3,?,?)""",
        (time.time(), time.time() + 86400))
    db.executemany('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)',
        [(code, '1234567890') for code in ['123456789012345675', '123456789012345682', 'JD000001']])
    password_policy.init_schema(db)
password_policy.prepare()
wsgi.application = password_policy.application
print('Disposable received-piece QA http://127.0.0.1:' + sys.argv[1], flush=True)
wsgi.serve('127.0.0.1', int(sys.argv[1]))
