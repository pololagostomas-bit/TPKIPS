"""Disposable all-module fixture. No production database or credentials."""
import os
import sys
import tempfile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / 'qa' / 'runtime'
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix="wms-mobile-qa-", dir=runtime))
os.environ["TRITON_AUTH_MODE"] = "demo"
os.environ["TRITON_DB_PATH"] = str(scratch / "qa.sqlite")
from backend import app
from backend.services.reception import create_reception
from backend.services.inventory_governance import create_material_request
from backend.wsgi import serve

app.DB_PATH = scratch / "qa.sqlite"
app.init_db()
stamp = "2026-10-08 09:00:00"
with app.db() as connection:
    for username, role in [("qa.receiver", "ASISTENTE_RECEPCION"), ("qa.auxiliary", "AUXILIAR_RECEPCION"), ("qa.worker", "PICKER_GUIADOR")]:
        connection.execute("INSERT INTO users (username,display_name,role,shift,active,created_at,updated_at) VALUES (?,?,?,'DIA',1,?,?)", (username, username, role, stamp, stamp))
    for index, status in enumerate(["PROGRAMADO", "ARRIBADO", "REVISION SISTEMA", "EM", "UBICACION", "VALIDACION", "SOLICITUD TRANSFERENCIA", "CERRADO"]):
        item = create_reception(connection, {"bl_awb": f"QA-MOBILE-{index}", "supplier": "Proveedor de repuestos industriales para operaciones", "transport_type": "AEREO", "scheduled_date": "2026-10-08", "current_assistant": "qa.receiver", "current_auxiliary": "qa.auxiliary"}, "demo.admin", "ADMINISTRADOR")
        connection.execute("UPDATE reception_shipments SET app_status=?,expected_packages=5,received_packages=2,first_arrival_at=? WHERE id=?", (status, stamp if index else None, item["id"]))
        for number in range(3):
            connection.execute("INSERT INTO reception_lines (shipment_id,np_code,description,expected_qty,received_qty,default_location) VALUES (?,?,?,8,0,'R-01-02')", (item["id"], f"QA-NP-{number}", "Repuesto de mantenimiento con descripcion larga para verificar la lectura en un celular"))
    truck_bl = connection.execute("INSERT INTO reception_shipments (bl_awb,expected_packages,app_status,current_assistant,current_auxiliary,created_at,updated_at) VALUES ('QA-TRUCK-MOBILE',5,'PROGRAMADO','qa.receiver','qa.auxiliary',?,?)", (stamp, stamp)).lastrowid
    connection.execute("INSERT INTO reception_lines (shipment_id,np_code,expected_qty) VALUES (?,'NP-TRUCK',8)", (truck_bl,))
    connection.execute("INSERT INTO orders (sap_ov,customer_name,source_order_date,app_status,created_at,updated_at) VALUES ('QA-OV-1','Cliente de mantenimiento industrial',?,'ASIGNADO',?,?)", (stamp, stamp, stamp))
    for number in range(3):
        connection.execute("INSERT INTO order_lines(sap_ov,source_row,item_code,description,pending_qty,required_qty,available_qty,warehouse) VALUES ('QA-OV-1',?,?,?,3,3,12,'1')", (number + 1, f"QA-NP-{number}", "Repuesto industrial de mantenimiento"))
    connection.execute("INSERT INTO inventory_stock(item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,snapshot_at,source_file,default_location,is_current,updated_at) VALUES ('QA-NP-0','1','QA-NP-0','1',12,'2026-10-08',?,'qa.xlsx','R-01-02',1,?)", (stamp, stamp))
    create_material_request(connection, {"item_code": "QA-NEW", "description": "Repuesto nuevo para mantenimiento industrial", "part_number": "PN-QA", "justification": "Necesidad operativa de prueba"}, "qa.receiver", "ASISTENTE_RECEPCION")
attention = app.create_attention("QA-OV-1", "demo.admin", "ADMINISTRADOR")
with app.db() as connection:
    connection.execute("UPDATE attentions SET app_status='ASIGNADO',current_picker='qa.worker',current_guide='qa.worker' WHERE id=?", (attention["id"],))
original_get = app.Handler.do_GET
def fixture_get(handler):
    path = handler.path.split('?', 1)[0]
    if path.startswith('/qa/mobile/'):
        name = path.removeprefix('/qa/mobile/')
        snapshot = runtime / 'mobile-views' / name
        if not re.fullmatch(r'[a-z0-9-]+\.html', name) or not snapshot.is_file():
            handler.send_json({'error': 'QA snapshot not found'}, 404)
            return
        body = snapshot.read_bytes().replace(b'</body>', b'<script src="/assets/mobile-workspace.js?v=qa"></script></body>')
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return
    return original_get(handler)
app.Handler.do_GET = fixture_get
print(f"QA ONLY http://127.0.0.1:{sys.argv[1]}", flush=True)
serve("127.0.0.1", int(sys.argv[1]))
