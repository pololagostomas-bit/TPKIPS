"""Loopback UI fixture; never opens or changes an operational database."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TRITON_AUTH_MODE"] = "demo"
scratch = Path(tempfile.mkdtemp(prefix="wms-navigation-qa-"))
os.environ["TRITON_DB_PATH"] = str(scratch / "qa.sqlite")

from backend import app
from backend.services import reception
from backend.wsgi import serve

app.DB_PATH = scratch / "qa.sqlite"
app.init_db()
with app.db() as connection:
    shipment = connection.execute(
        """INSERT INTO reception_shipments
           (bl_awb, expected_packages, app_status, current_assistant,
            current_auxiliary, created_at, updated_at)
           VALUES ('QA-RETURN-001',5,'PROGRAMADO','demo.recepcion',
                   'demo.recepcion','2026-10-07','2026-10-07')"""
    ).lastrowid
    for guide, amount in (("QA-ORIGIN", 2), ("QA-OTHER", 1)):
        reception.plan_truck_bl_packages(connection, guide, shipment, amount,
                                         "demo.recepcion", "ADMINISTRADOR")
        reception.confirm_truck_guide(connection, guide, guide, "demo.recepcion", "ADMINISTRADOR")
    reception.process_truck_guide_arrivals(
        connection, "QA-ORIGIN", [{"shipment_id": shipment, "received_packages": 2}],
        "qa-arrival", "", "demo.recepcion", "ADMINISTRADOR"
    )
    reception.process_truck_guide_locations(
        connection, "QA-ORIGIN", [{"shipment_id": shipment,
                                "locations": [{"location": "QA-TEMP", "package_count": 2}]}],
        "demo.recepcion", "ADMINISTRADOR"
    )
    connection.execute("UPDATE reception_shipments SET truck_guide='QA-OTHER' WHERE id=?", (shipment,))
    if "--scanner" in sys.argv:
        connection.execute("UPDATE reception_truck_guides SET scanner_enabled=1, source_type='ESCANEO' WHERE guide_code='QA-ORIGIN'")
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8094
print(f"QA ONLY: http://127.0.0.1:{port}/reception", flush=True)
serve("127.0.0.1", port)
