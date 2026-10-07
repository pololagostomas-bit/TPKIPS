"""Disposable local UI fixture. Never opens the operational database."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['TRITON_AUTH_MODE'] = 'demo'
scratch = Path(tempfile.mkdtemp(prefix='triton-scan-qa-'))
os.environ['TRITON_DB_PATH'] = str(scratch / 'qa.sqlite')

from backend import app
from backend.services import reception
from backend.wsgi import serve

app.DB_PATH = scratch / 'qa.sqlite'
app.init_db()
with app.db() as connection:
    for index, bl in enumerate(['QA-BL-001', 'QA-BL-002']):
        shipment = connection.execute(
            """INSERT INTO reception_shipments
            (bl_awb,expected_packages,app_status,current_assistant,current_auxiliary,
             transport_type,created_at,updated_at)
            VALUES (?,3,'PROGRAMADO','demo.recepcion','demo.recepcion','AEREO',
                    '2026-10-01','2026-10-01')""", (bl,)
        ).lastrowid
        connection.execute(
            """INSERT INTO reception_lines
               (shipment_id,np_code,description,expected_qty,ov_number)
               VALUES (?,'NP-001','Artículo de prueba',8,'OV-QA-1')""", (shipment,)
        )
        if index:
            connection.execute(
                """INSERT INTO reception_lines
                   (shipment_id,np_code,description,expected_qty,ov_number)
                   VALUES (?,'NP-001','Mismo NP, otra OV',2,'OV-QA-2')""", (shipment,)
            )
port = int(sys.argv[1]) if len(sys.argv) > 1 else 9012
print(f'QA ONLY: http://127.0.0.1:{port}/reception', flush=True)
print('Disposable database: ' + str(app.DB_PATH), flush=True)
serve('127.0.0.1', port)
