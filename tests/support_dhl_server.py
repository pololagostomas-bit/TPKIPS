"""Disposable DHL/UI fixture. Credentials and tracking responses are fictitious."""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / 'qa/runtime'
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='wms-dhl-qa-', dir=runtime))
key = scratch / 'qa.secret'
key.write_text('fictitious-test-key-not-a-real-key', encoding='ascii')
os.environ.update(TRITON_AUTH_MODE='local', TRITON_DB_PATH=str(scratch / 'qa.sqlite'),
    TRITON_BOOTSTRAP_ADMIN_USERNAME='qa.reader', TRITON_BOOTSTRAP_ADMIN_PASSWORD='QA-password-only-123!',
    TRITON_COOKIE_SECURE='0', WMS_CLOUD_AUTO_SYNC='0', WMS_PURCHASE_ALERT_WORKER='0',
    WMS_DHL_ENABLED='1', DHL_API_KEY_FILE=str(key))

from backend import app, wsgi, password_policy
from backend.services import dhl_tracking as dhl


def fake_tracking(awb, key, now):
    return dhl.parse_response({'shipments': [{'id': awb, 'service': 'express',
        'status': {'statusCode': 'transit', 'timestamp': datetime.now(timezone.utc).isoformat()},
        'details': {'totalNumberOfPieces': 2,
                    'pieceIds': ['JD0000000000000000' + ('01' if awb == '1234567890' else '03'),
                                 'JD0000000000000000' + ('02' if awb == '1234567890' else '04')]}}]}, awb, now)


dhl.fetch_tracking = fake_tracking
app.init_db()
with app.db() as connection:
    for awb in ('1234567890', '1234567891'):
        connection.execute("""INSERT INTO reception_shipments
            (bl_awb,transport_type,app_status,scheduled_date,created_at,updated_at)
            VALUES (?,'COURIER','PROGRAMADO',?,?,?)""", (awb, app.local_now()[:10], app.local_now(), app.local_now()))
    password_policy.init_schema(connection)
dhl.worker_cycle(app)
# Second fictitious result; no sleeping or real transport involved.
dhl.worker_cycle(app, time.time() + 6)
password_policy.prepare()
wsgi.application = password_policy.application
print('QA ONLY http://127.0.0.1:' + sys.argv[1], flush=True)
wsgi.serve('127.0.0.1', int(sys.argv[1]))
