import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import app
from backend.services import reception
from backend.services.truck_entry import resolve_entered_bl


class DirectTruckEntryTests(unittest.TestCase):
    def test_lookup_reuses_existing_and_rejects_closed_or_ambiguous_bl(self):
        with app.db() as db:
            shipment, created = resolve_entered_bl(db, '000-REUSE', 'admin.test', 'ADMINISTRADOR')
            self.assertTrue(created)
            reused, created = resolve_entered_bl(db, '000reuse', 'admin.test', 'ADMINISTRADOR')
            self.assertFalse(created)
            self.assertEqual(shipment['id'], reused['id'])
            db.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?", (shipment['id'],))
            with self.assertRaisesRegex(ValueError, 'cerrada'):
                resolve_entered_bl(db, '000-REUSE', 'admin.test', 'ADMINISTRADOR')
            db.execute("INSERT INTO reception_shipments(bl_awb,created_at,updated_at) VALUES ('000REUSE','2026-10-07','2026-10-07')")
            with self.assertRaisesRegex(ValueError, 'varios expedientes'):
                resolve_entered_bl(db, '000-REUSE', 'admin.test', 'ADMINISTRADOR')
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        db_patch = patch.object(app, "DB_PATH", Path(scratch.name) / "qa.sqlite")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        env = patch.dict(os.environ, {"TRITON_AUTH_MODE": "demo"})
        env.start()
        self.addCleanup(env.stop)
        app.init_db()
        self.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, path, data=None, role="ADMINISTRADOR"):
        request = Request(self.base + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Content-Type": "application/json", "X-User": "admin.test", "X-Role": role})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_new_bl_without_programming_arrives_and_is_located(self):
        if hasattr(reception, "create_scanner_truck_guide"):
            self.skipTest("Scanner variant creates its own scanner guides")
        guide = self.request("/api/truck-guides", {})["truck_guide"]
        self.assertIn(guide, {g["truck_guide"] for g in self.request("/api/truck-guides")})
        entry = {"truck_guide": guide, "bl_code": "000-NEW-BL", "packages": 2}
        result = self.request("/api/receptions/truck-guide/entry", entry)
        sid = result["shipment_id"]
        with app.db() as db:
            db.execute("UPDATE reception_shipments SET current_assistant='qa.assistant',current_auxiliary='qa.auxiliary' WHERE id=?", (sid,))
        self.assertTrue(result["created"])
        retry = self.request("/api/receptions/truck-guide/entry", {**entry, "bl_code": "000NEWBL", "packages": 9})
        self.assertTrue(retry["duplicate"])
        self.assertEqual(retry["shipment_id"], sid)
        with app.db() as db:
            reception.init_reception_schema(db)
            self.assertEqual(db.execute("SELECT expected_packages FROM reception_shipments WHERE id=?", (sid,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT source_type FROM reception_truck_guides WHERE guide_code=?", (guide,)).fetchone()[0], "INGRESO_DIRECTO")
            self.assertEqual(db.execute("SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id=?", (sid,)).fetchone()[0], 2)
        arrived = self.request("/api/receptions/truck-arrival", {
            "truck_guide": guide, "arrival_key": "direct-qa",
            "bls": [{"shipment_id": sid, "received_packages": 2}]})
        self.assertEqual(arrived["guide_status"], "ZONA_RECEPCION")
        closed = self.request("/api/receptions/truck-guide/locations", {
            "truck_guide": guide, "bls": [{"shipment_id": sid,
                "locations": [{"location": "QA-TEMP", "package_count": 2}]}]})
        self.assertEqual(closed["guide_status"], "LISTA_PARA_CONTEO")
        with app.db() as db:
            self.assertEqual(db.execute("SELECT expected_packages,received_packages FROM reception_shipments WHERE id=?", (sid,)).fetchone()[:], (0, 2))
        with self.assertRaises(HTTPError):
            self.request("/api/receptions/truck-guide/entry", {**entry, "bl_code": "MUST-NOT-CREATE"})
        with app.db() as db:
            self.assertIsNone(db.execute("SELECT id FROM reception_shipments WHERE bl_awb='MUST-NOT-CREATE'").fetchone())

    def test_invalid_role_or_quantity_cannot_create_expedients(self):
        if hasattr(reception, "create_scanner_truck_guide"):
            self.skipTest("Manual endpoint is unavailable in the scanner variant")
        guide = self.request("/api/truck-guides", {})["truck_guide"]
        for packages, role in [(0, "ADMINISTRADOR"), (1.5, "ADMINISTRADOR"),
                                (1, "AUXILIAR_RECEPCION")]:
            with self.subTest(packages=packages, role=role), self.assertRaises(HTTPError):
                self.request("/api/receptions/truck-guide/entry", {
                    "truck_guide": guide, "bl_code": "NOT-CREATED", "packages": packages}, role)
        with app.db() as db:
            self.assertIsNone(db.execute("SELECT id FROM reception_shipments WHERE bl_awb='NOT-CREATED'").fetchone())

    def test_scanner_accepts_new_bl_without_expected_quantities(self):
        if not hasattr(reception, "create_scanner_truck_guide"):
            self.skipTest("Manual variant has no scanner")
        guide = self.request("/api/receptions/truck-guide/scan-create", {})["truck_guide"]
        result = self.request("/api/receptions/truck-guide/scan-bl", {
            "truck_guide": guide, "bl_code": "000-SCANNED-BL"}, "ASISTENTE_RECEPCION")
        self.assertTrue(result["created"])
        sid = result["shipment_id"]
        for code in ["QA-UNPLANNED-1", "QA-UNPLANNED-2"]:
            self.request("/api/receptions/truck-guide/scan-package", {
                "truck_guide": guide, "shipment_id": sid, "package_code": code})
        arrived = self.request("/api/receptions/truck-guide/scan-finalize", {"truck_guide": guide})
        self.assertEqual(arrived["received_packages"], 2)
        with app.db() as db:
            self.assertEqual(db.execute("SELECT expected_packages FROM reception_shipments WHERE id=?", (sid,)).fetchone()[0], 0)
