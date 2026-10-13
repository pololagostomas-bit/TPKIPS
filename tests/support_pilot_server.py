"""Local-only correction preview with a fresh, disposable synthetic database."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix='wms-pilot-qa-'))
os.environ.update(TRITON_AUTH_MODE='local', TRITON_DB_PATH=str(scratch / 'qa.sqlite'),
    TRITON_BOOTSTRAP_ADMIN_USERNAME='qa.reader', TRITON_BOOTSTRAP_ADMIN_PASSWORD='QA-password-only-123!',
    TRITON_COOKIE_SECURE='0', WMS_CLOUD_AUTO_SYNC='0', WMS_PURCHASE_ALERT_WORKER='0',
    WMS_DHL_ENABLED='0', TRITON_MAIL_ENABLED='0')
from backend import app, wsgi, password_policy
from tests.test_reception_pilot_correction import seed_pilot

app.init_db()
with app.db() as connection:
    for index in range(12):
        seed_pilot(connection, 'QA-PILOT-' + str(index + 1), complete=index != 11)
    password_policy.init_schema(connection)
password_policy.prepare()
wsgi.application = password_policy.application
print('QA ONLY http://127.0.0.1:' + sys.argv[1], flush=True)
wsgi.serve('127.0.0.1', int(sys.argv[1]))
