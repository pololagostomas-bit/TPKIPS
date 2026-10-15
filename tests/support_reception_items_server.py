"""Count/label UI fixture. Only creates a new disposable database."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = ROOT / "qa" / "runtime"
runtime.mkdir(parents=True, exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix="wms-items-qa-", dir=runtime))
os.environ["TRITON_AUTH_MODE"] = "demo"
os.environ["TRITON_MAIL_ENABLED"] = "0"
os.environ["TRITON_DB_PATH"] = str(scratch / "qa.sqlite")
if len(sys.argv) > 2:
    os.environ["WMS_BRAND_LOGO_DIR"] = str(Path(sys.argv[2]).resolve())

from backend import app
from backend.services import reception
from backend.wsgi import serve

app.DB_PATH = scratch / "qa.sqlite"
app.init_db()
stamp = "2026-10-12 09:00:00"
with app.db() as connection:
    customers = {"QA-OV-1": "Cliente uno & mantenimiento",
                 "QA-OV-2": "Cliente dos de operaciones industriales y servicios de mantenimiento " * 2}
    for ov in customers:
        connection.execute(
            """INSERT INTO orders (sap_ov,customer_name,app_status,created_at,updated_at)
               VALUES (?,?,'ASIGNADO',?,?)""", (ov, "Nombre de OV que no debe imprimirse", stamp, stamp)
        )
    connection.execute(
        """INSERT INTO inventory_stock
           (item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,
            snapshot_at,source_file,default_location,is_current,updated_at)
           VALUES ('NP001','1','NP-001','1',12,'2026-10-12',?,'qa.xlsx','SAP-A01',1,?)""",
        (stamp, stamp),
    )
    for index, status in enumerate(["REVISION SISTEMA", "EM", "UBICACION", "REVISION SISTEMA"]
                                   + ["REVISION SISTEMA"] * 29, 1):
        sid = connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb,app_status,received_packages,current_assistant,current_auxiliary,
                transport_type,first_arrival_at,created_at,updated_at)
               VALUES (?,?,2,'demo.admin','demo.admin','AEREO',?,?,?)""",
            (f"QA-ITEMS-{index}", status, stamp, stamp, stamp),
        ).lastrowid
        for np, ov in [("NP-001", "QA-OV-1"), ("NP-001", "QA-OV-2"),
                       ("NP-NOSTOCK", "QA-OV-1"), ("NP-ZERO", "QA-OV-UNKNOWN")]:
            connection.execute(
                """INSERT INTO reception_lines (shipment_id,np_code,description,ov_number,expected_qty,customer_name,brand,ip_reference)
                   VALUES (?,?,?,?,5,?,?,?)""",
                (sid, np, "Repuesto industrial de prueba con descripcion extensa " * 2, ov, customers.get(ov, ""),
                 "CROWN JAPON" if np == "NP-NOSTOCK" else "BOBCAT EUROPA" if ov == "QA-OV-1" else "BOBCAT INDIA",
                 "QA-IP-" + ov[-1]),
            )
        shipment = connection.execute("SELECT * FROM reception_shipments WHERE id=?", (sid,)).fetchone()
        attention = reception._create_reception_attention(connection, shipment, None, "demo.admin", status)
        connection.execute("UPDATE reception_attentions SET system_quantities_initialized=1 WHERE id=?", (attention["id"],))
        for line in connection.execute("SELECT * FROM reception_lines WHERE shipment_id=?", (sid,)).fetchall():
            qty = 0 if line["np_code"] == "NP-ZERO" else 5
            location = "BIN-" + line["ov_number"] if line["np_code"] == "NP-001" else ""
            if status == "REVISION SISTEMA":
                location = "SAP-A01" if line["np_code"] == "NP-001" else ""
            connection.execute("UPDATE reception_lines SET received_qty=? WHERE id=?",
                               (7 if line["np_code"] == "NP-ZERO" else qty, line["id"]))
            connection.execute(
                """UPDATE reception_attention_lines SET verified_qty=?,final_location=?,
                   count_location_saved=1,count_location_manual=? WHERE attention_id=? AND reception_line_id=?""",
                (qty, location, int(not location), attention["id"], line["id"]),
            )
        if index == 13:
            connection.execute("UPDATE reception_attentions SET system_quantities_initialized=0 WHERE id=?", (attention["id"],))
            connection.execute(
                "UPDATE reception_attention_lines SET verified_qty=0,count_location_saved=0,count_location_manual=0,final_location=NULL WHERE attention_id=?",
                (attention["id"],),
            )
        stability_case = 14 + (index - 14) % 4 if index >= 14 else 0
        if stability_case == 15:
            other = connection.execute(
                "SELECT id FROM reception_lines WHERE shipment_id=? AND np_code='NP-001' AND ov_number='QA-OV-2'",
                (sid,),
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?",
                (attention["id"], other),
            )
            connection.execute(
                "INSERT INTO reception_lines(shipment_id,np_code,description,expected_qty) VALUES (?,'NP-HIST','Otra llegada',2)",
                (sid,),
            )
        if stability_case == 16:
            connection.execute(
                "UPDATE reception_lines SET ov_number='' WHERE shipment_id=? AND np_code='NP-001' AND ov_number='QA-OV-2'",
                (sid,),
            )
        if stability_case == 17:
            connection.execute(
                "UPDATE reception_lines SET ov_number='QA-OV-1',ip_reference='QA-IP-1' WHERE shipment_id=? AND np_code='NP-001'",
                (sid,),
            )
        for number in (1, 2):
            connection.execute(
                """INSERT INTO reception_accounting_refs(shipment_id,source_key,ip_reference,fr_number,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""", (sid,f"qa-ref-{sid}-{number}",f"QA-IP-{number}",f"QA-FR-{number}",stamp,stamp),
            )
print(f"QA ONLY http://127.0.0.1:{sys.argv[1]}/reception", flush=True)
print("Disposable database: " + str(app.DB_PATH), flush=True)
serve("127.0.0.1", int(sys.argv[1]))
