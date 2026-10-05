import sqlite3
import unittest

from backend.services import reception


class ReceptionBarcodeScanningTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        reception.init_reception_schema(self.db)
        self.db.execute(
            """CREATE TABLE order_importation_refs (
                   bl_awb TEXT, sap_ov TEXT, transport_type TEXT,
                   ip_reference TEXT, oc_number TEXT
               )"""
        )
        self.shipment_id = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary,
                transport_type, created_at, updated_at)
               VALUES ('BL-90001', 2, 'PROGRAMADO', 'operador.test', 'auxiliar.test',
                       'AEREO', '2026-10-01', '2026-10-01')"""
        ).lastrowid
        self.db.execute(
            "INSERT INTO reception_lines (shipment_id, np_code, description, expected_qty) VALUES (?, '0012345', 'NP TEST', 8)",
            (self.shipment_id,),
        )
        self.guide = reception.create_scanner_truck_guide(
            self.db, "operador.test", "ASISTENTE_RECEPCION"
        )["truck_guide"]

    def tearDown(self):
        self.db.close()

    def test_scanned_bl_packages_are_deduplicated_and_become_normal_reception(self):
        linked = reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertTrue(linked["added"])
        self.assertEqual(linked["shipment_id"], self.shipment_id)

        first = reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "PKG-0001", "operador.test", "ASISTENTE_RECEPCION"
        )
        before_retry = list(self.db.iterdump())
        changes_before_retry = self.db.total_changes
        retry = reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, " pkg-0001 ", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertEqual(first["count"], 1)
        self.assertTrue(retry["duplicate"])
        self.assertFalse(retry["accepted"])
        self.assertEqual(retry["count"], 1)
        self.assertEqual(self.db.total_changes, changes_before_retry)
        self.assertEqual(list(self.db.iterdump()), before_retry)
        second = reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "PKG-0002", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertEqual(second["count"], 2)

        closed_arrival = reception.finalize_scanned_truck_arrival(
            self.db, self.guide, "", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertEqual(closed_arrival["guide_status"], "ZONA_RECEPCION")
        self.assertEqual(closed_arrival["bls"][0]["received_this_truck"], 2)
        self.assertEqual(closed_arrival["bls"][0]["package_scan_count"], 2)

        closed_zone = reception.process_truck_guide_locations(
            self.db, self.guide,
            [{"shipment_id": self.shipment_id,
              "locations": [{"location": "TEMP-A1", "package_count": 2}]}],
            "operador.test", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(closed_zone["guide_status"], "LISTA_PARA_CONTEO")
        self.assertEqual(closed_zone["bls"][0]["locations"][0]["location_text"], "TEMP-A1")

    def test_package_code_cannot_be_reused_for_a_different_manifest(self):
        self.db.execute("UPDATE reception_shipments SET bl_awb='BL-90002' WHERE id=?", (self.shipment_id,))
        other_id = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary,
                transport_type, created_at, updated_at)
               VALUES ('BL-90003', 1, 'PROGRAMADO', 'operador.test', 'auxiliar.test',
                       'AEREO', '2026-10-01', '2026-10-01')"""
        ).lastrowid
        reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90002", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90003", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "UNIQUE-PACKAGE", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assert_duplicate_rejected_without_changes(self.guide, other_id, "BL-90002")

    def assert_duplicate_rejected_without_changes(self, target_guide, target_id, original_bl):
        before = list(self.db.iterdump())
        changes_before = self.db.total_changes
        for package_code in ("UNIQUE-PACKAGE", " unique-package "):
            with self.subTest(package_code=package_code):
                with self.assertRaisesRegex(ValueError, "otra BL o guía") as error:
                    reception.scan_truck_package(
                        self.db, target_guide, target_id, package_code,
                        "operador.test", "ASISTENTE_RECEPCION",
                    )
                self.assertIn(f"BL/AWB: {original_bl}", str(error.exception))
                self.assertIn(f"guía: {self.guide}", str(error.exception))
                self.assertEqual(self.db.total_changes, changes_before)
                self.assertEqual(list(self.db.iterdump()), before)

    def test_duplicate_in_another_guide_identifies_original_bl_and_guide(self):
        reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "UNIQUE-PACKAGE",
            "operador.test", "ASISTENTE_RECEPCION",
        )
        other_guide = reception.create_scanner_truck_guide(
            self.db, "operador.test", "ASISTENTE_RECEPCION"
        )["truck_guide"]
        other_id = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary,
                transport_type, created_at, updated_at)
               VALUES ('BL-90003', 1, 'PROGRAMADO', 'operador.test', 'auxiliar.test',
                       'AEREO', '2026-10-01', '2026-10-01')"""
        ).lastrowid
        for bl_code, target_id in (("BL-90001", self.shipment_id), ("BL-90003", other_id)):
            with self.subTest(bl_code=bl_code):
                reception.add_scanned_truck_bl(
                    self.db, other_guide, bl_code, "operador.test", "ASISTENTE_RECEPCION"
                )
                self.assert_duplicate_rejected_without_changes(other_guide, target_id, "BL-90001")

    def test_unknown_package_code_is_rejected_and_empty_scan_guides_are_selectable(self):
        with self.assertRaisesRegex(ValueError, "Escanea primero la BL"):
            reception.scan_truck_package(
                self.db, self.guide, self.shipment_id, "NO-MANIFEST", "operador.test", "ASISTENTE_RECEPCION"
            )
        guides = reception.list_truck_guides(
            self.db, role="ASISTENTE_RECEPCION", username="operador.test"
        )
        self.assertIn(self.guide, {row["truck_guide"] for row in guides})

    def test_admin_rewind_voids_package_scans_without_deleting_audit(self):
        reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "PKG-REWIND", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.finalize_scanned_truck_arrival(
            self.db, self.guide, "", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.revert_truck_guide(
            self.db, self.guide, "admin.test", "ADMINISTRADOR", "PENDIENTE"
        )
        scan = self.db.execute(
            "SELECT scan_status, voided_by, void_reason FROM reception_truck_package_scans"
        ).fetchone()
        self.assertEqual(scan["scan_status"], "ANULADO")
        self.assertEqual(scan["voided_by"], "admin.test")
        self.assertTrue(scan["void_reason"])
        retried = reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "PKG-REWIND", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertEqual(retried["count"], 1)

    def test_cancelled_scan_guide_stays_out_of_active_queue_and_can_be_archived(self):
        reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "PKG-CANCEL", "operador.test", "ASISTENTE_RECEPCION"
        )
        reception.cancel_scanned_truck_arrival(
            self.db, self.guide, "operador.test", "ASISTENTE_RECEPCION"
        )

        # Simula una copia donde una migración previa reclasificó por error el
        # camión SCAN-* como manual; volver a inicializar el esquema debe reparar esa clasificación.
        self.db.execute(
            "UPDATE reception_truck_guides SET source_type='ADMINISTRADOR' WHERE guide_code=?",
            (self.guide,),
        )
        reception.init_reception_schema(self.db)
        header = self.db.execute(
            "SELECT source_type, guide_status, scanner_enabled FROM reception_truck_guides WHERE guide_code=?",
            (self.guide,),
        ).fetchone()
        self.assertEqual(header["source_type"], "ESCANEO")
        self.assertEqual(header["guide_status"], "CANCELADA")
        self.assertEqual(header["scanner_enabled"], 0)

        active = reception.list_truck_guides(
            self.db, role="ADMINISTRADOR", username="admin.test", include_completed=False
        )
        self.assertNotIn(self.guide, {row["truck_guide"] for row in active})
        history = reception.list_truck_guides(
            self.db, role="ADMINISTRADOR", username="admin.test", include_completed=True
        )
        self.assertIn(self.guide, {row["truck_guide"] for row in history})

        with self.assertRaisesRegex(PermissionError, "Solo el administrador"):
            reception.archive_cancelled_scanned_truck_guide(
                self.db, self.guide, "limpieza de prueba", "operador.test", "ASISTENTE_RECEPCION"
            )
        result = reception.archive_cancelled_scanned_truck_guide(
            self.db, self.guide, "recepción duplicada", "admin.test", "ADMINISTRADOR"
        )
        self.assertTrue(result["archived"])
        scans = self.db.execute(
            "SELECT scan_status, voided_by FROM reception_truck_package_scans WHERE truck_guide=?",
            (self.guide,),
        ).fetchall()
        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0]["scan_status"], "ANULADO")
        self.assertEqual(scans[0]["voided_by"], "operador.test")
        archived = self.db.execute(
            "SELECT archived_by, archive_reason FROM reception_truck_guides WHERE guide_code=?",
            (self.guide,),
        ).fetchone()
        self.assertEqual(archived["archived_by"], "admin.test")
        self.assertEqual(archived["archive_reason"], "recepción duplicada")
        visible = reception.list_truck_guides(
            self.db, role="ADMINISTRADOR", username="admin.test", include_completed=True
        )
        self.assertNotIn(self.guide, {row["truck_guide"] for row in visible})


if __name__ == "__main__":
    unittest.main()
