"""Truck lookup regressions using only a disposable SQLite database."""
import os
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import app
from backend.services import reception
from backend.wsgi import application


class TruckLookupTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        database = patch.object(app, "DB_PATH", Path(scratch.name) / "lookup.db")
        database.start()
        self.addCleanup(database.stop)
        environment = patch.dict(os.environ, {"TRITON_AUTH_MODE": "demo"})
        environment.start()
        self.addCleanup(environment.stop)
        app.init_db()
        self.connection = self.enterContext(app.db())
        self.shipment = self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant,
                current_auxiliary, created_at, updated_at)
               VALUES ('BL-LOOKUP-001', 5, 'PROGRAMADO', 'assistant.lookup',
                       'aux.lookup', '2026-10-07', '2026-10-07')"""
        ).lastrowid
        reception.plan_truck_bl_packages(
            self.connection, "LOOKUP-A", self.shipment, 2, "admin", "ADMINISTRADOR"
        )
        reception.plan_truck_bl_packages(
            self.connection, "LOOKUP-B", self.shipment, 1, "admin", "ADMINISTRADOR"
        )

    def test_pending_queue_still_excludes_truck_transit_work(self):
        self.assertEqual(reception.list_receptions(self.connection), [])

    def test_navigation_script_is_served_as_javascript(self):
        status = []
        body = b"".join(application({
            "PATH_INFO": "/assets/truck-navigation.js",
            "QUERY_STRING": "v=regression",
            "REQUEST_METHOD": "GET",
            "wsgi.input": io.BytesIO(),
        }, lambda code, headers: status.append((code, dict(headers)))))
        self.assertTrue(status[0][0].startswith("200"))
        self.assertIn("javascript", status[0][1]["Content-Type"])
        self.assertIn(b"WmsTruckNavigation", body)

    def test_explicit_lookup_finds_transit_bl_and_every_linked_truck(self):
        rows = reception.list_receptions(self.connection, search="BL-LOOKUP-001")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.shipment)
        self.assertEqual(set(rows[0]["linked_truck_guides"].split(",")), {"LOOKUP-A", "LOOKUP-B"})

    def test_explicit_lookup_finds_closed_bl_without_reopening_it(self):
        self.connection.execute(
            "UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?", (self.shipment,)
        )
        rows = reception.list_receptions(self.connection, search="BL-LOOKUP-001")
        self.assertEqual(rows[0]["app_status"], "CERRADO")

    def test_lookup_keeps_assignment_permissions(self):
        for role, username in (
            ("ASISTENTE_RECEPCION", "assistant.lookup"),
            ("AUXILIAR_RECEPCION", "aux.lookup"),
        ):
            self.assertEqual(len(reception.list_receptions(
                self.connection, search="BL-LOOKUP-001", role=role, username=username
            )), 1)
            self.assertEqual(reception.list_receptions(
                self.connection, search="BL-LOOKUP-001", role=role, username="someone.else"
            ), [])

    def test_detail_exposes_unallocated_balance_not_full_pending_quantity(self):
        detail = reception.reception_detail(self.connection, self.shipment)
        self.assertEqual(detail["pending_to_plan_packages"], 2)
        self.assertEqual(len(detail["truck_plans"]), 2)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM reception_truck_bl_manifest"
        ).fetchone()[0], 2)
