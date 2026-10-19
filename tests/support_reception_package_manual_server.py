"""Loopback-only manual/package UI fixture, with synthetic cache and no workers."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix='wms-manual-package-qa-'))
key = scratch / 'qa.secret'
key.write_text('fictitious-not-a-real-key', encoding='ascii')
os.environ.update(TRITON_AUTH_MODE='local', TRITON_DB_PATH=str(scratch / 'qa.sqlite'),
    TRITON_BOOTSTRAP_ADMIN_USERNAME='qa.reader', TRITON_BOOTSTRAP_ADMIN_PASSWORD='QA-password-only-123!',
    TRITON_COOKIE_SECURE='0', WMS_CLOUD_AUTO_SYNC='0', WMS_PURCHASE_ALERT_WORKER='0',
    WMS_TRANSFER_WORKER='0', WMS_DHL_ENABLED='1', DHL_API_KEY_FILE=str(key))

from backend import app, password_policy, wsgi
from backend.services import dhl_tracking as dhl


def no_network(*args, **kwargs):
    raise AssertionError('External tracking is forbidden in this fixture')


dhl.fetch_tracking = no_network
dhl.start_worker = lambda *args, **kwargs: None
app.init_db()
with app.db() as connection:
    for username, role in [('qa.assistant', 'ASISTENTE_RECEPCION'), ('qa.auxiliary', 'AUXILIAR_RECEPCION')]:
        app.identity.save(connection, {'username': username, 'display_name': username, 'role': role,
            'password': 'QA-password-only-123!'}, 'qa.reader', app.ROLES)
    for bl, transport in [('1234567890', 'COURIER'), ('QA-SEA-0001', 'MARITIMO')]:
        connection.execute('''INSERT INTO reception_shipments
            (bl_awb,transport_type,app_status,expected_packages,created_at,updated_at)
            VALUES (?,?,'PROGRAMADO',61,?,?)''', (bl, transport, app.local_now(), app.local_now()))
    connection.execute('''INSERT INTO dhl_tracking_cache
        (awb,status_code,total_pieces,checked_at,expires_at) VALUES ('1234567890','transit',61,?,?)''',
        (time.time(), time.time() + 86400))
    connection.executemany('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)',
        [('JD' + str(i).zfill(8), '1234567890') for i in range(1, 62)])
    password_policy.init_schema(connection)
password_policy.prepare()
wsgi.application = password_policy.application
print('SYNTHETIC QA ONLY http://127.0.0.1:' + sys.argv[1], flush=True)
wsgi.serve('127.0.0.1', int(sys.argv[1]))
