"""Disposable loopback fixture for truck controls; never uses production data."""
import os
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TRITON_AUTH_MODE"] = "demo"
scratch = Path(tempfile.mkdtemp(prefix="truck-controls-qa-"))
os.environ["TRITON_DB_PATH"] = str(scratch / "qa.sqlite")
from backend import app
from backend.wsgi import serve
app.DB_PATH = scratch / "qa.sqlite"
app.init_db()
with app.db() as connection:
    for width in [1366,375,320]:
        sid = connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb,expected_packages,app_status,current_assistant,current_auxiliary,created_at,updated_at)
               VALUES (?,5,'PROGRAMADO','demo.recepcion','demo.recepcion','2026-10-07','2026-10-07')""",
            (f"QA-CONTROLS-{width}",)
        ).lastrowid
        connection.execute("INSERT INTO reception_lines (shipment_id,np_code,expected_qty) VALUES (?,'NP-CONTROLS',8)",(sid,))
print(f"QA ONLY http://127.0.0.1:{sys.argv[1]}/reception",flush=True)
serve("127.0.0.1",int(sys.argv[1]))
