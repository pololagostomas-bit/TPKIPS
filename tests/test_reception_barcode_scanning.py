import sqlite3
import unittest
from unittest.mock import patch

from backend.services import dhl_tracking, reception


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

    def test_scan_returns_local_brand_and_expected_context_without_remote_fetch(self):
        self.db.execute("UPDATE reception_lines SET brand='BOBCAT EUROPA' WHERE shipment_id=?",(self.shipment_id,))
        for brand in ['BOBCAT INDIA','LIEBHERR']:
            self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,brand,expected_qty) VALUES (?,'QA',?,1)",
                            (self.shipment_id,brand))
        reception.add_scanned_truck_bl(self.db,self.guide,'BL-90001','operador.test','ADMINISTRADOR')
        with patch.object(dhl_tracking,'fetch_tracking') as fetch:
            first = reception.scan_truck_package(self.db,self.guide,self.shipment_id,'QA-BOX','operador.test','ADMINISTRADOR')
            again = reception.scan_truck_package(self.db,self.guide,self.shipment_id,'QA-BOX','operador.test','ADMINISTRADOR')
            summary = reception.truck_guide_summary(self.db,self.guide,'operador.test','ADMINISTRADOR')
        self.assertEqual(first['bl_context']['brands'],['BOBCAT','LIEBHERR'])
        self.assertEqual(first['bl_context']['package_progress'],{'expected':2,'source':'WMS','previously_received':0})
        self.assertEqual(first['bl_context'],again['bl_context'])
        self.assertEqual(summary['bls'][0]['package_progress']['expected'],2)
        fetch.assert_not_called()

    def test_maritime_bl_uses_existing_record_without_dhl_or_expected_quantity(self):
        self.db.execute(
            "UPDATE reception_shipments SET transport_type='MARITIMO',expected_packages=0 WHERE id=?",
            (self.shipment_id,),
        )
        with patch.object(dhl_tracking, "fetch_tracking") as fetch:
            first = reception.add_scanned_truck_bl(
                self.db, self.guide, " bl 90001 ", "operador.test", "ASISTENTE_RECEPCION"
            )
            self.assertEqual(first["shipment_id"], self.shipment_id)
            before = list(self.db.iterdump())
            duplicate = reception.add_scanned_truck_bl(
                self.db, self.guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
            )
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(list(self.db.iterdump()), before)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_receipts").fetchone()[0], 0)
            self.assertEqual(self.db.execute("SELECT received_packages FROM reception_shipments").fetchone()[0], 0)
            for code in ("SEA-BOX-01", "SEA-BOX-02"):
                reception.scan_truck_package(
                    self.db, self.guide, self.shipment_id, code, "operador.test", "ASISTENTE_RECEPCION"
                )
            self.assertFalse(dhl_tracking.enqueue(self.db, self.shipment_id))
            self.assertFalse(dhl_tracking.shipment_status(self.db, self.shipment_id)["applicable"])
            arrived = reception.finalize_scanned_truck_arrival(
                self.db, self.guide, "", "operador.test", "ASISTENTE_RECEPCION"
            )
            self.assertEqual(arrived["guide_status"], "ZONA_RECEPCION")
            self.assertEqual(arrived["bls"][0]["received_this_truck"], 2)
            self.assertEqual(arrived["bls"][0]["transport_type"], "MARITIMO")
            fetch.assert_not_called()

    def test_bl_entry_rejects_missing_closed_ambiguous_and_auxiliary_without_writes(self):
        for code, role, error in (("UNKNOWN", "ADMINISTRADOR", ValueError),
                                  ("BL-90001", "AUXILIAR_RECEPCION", PermissionError)):
            before = list(self.db.iterdump())
            with self.assertRaises(error):
                reception.add_scanned_truck_bl(self.db, self.guide, code, "operador.test", role)
            self.assertEqual(list(self.db.iterdump()), before)
        self.db.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?", (self.shipment_id,))
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, "cerrada"):
            reception.add_scanned_truck_bl(self.db, self.guide, "BL-90001", "operador.test", "ADMINISTRADOR")
        self.assertEqual(list(self.db.iterdump()), before)
        self.db.execute("UPDATE reception_shipments SET app_status='PROGRAMADO' WHERE id=?", (self.shipment_id,))
        self.db.execute(
            "INSERT INTO reception_shipments(bl_awb,transport_type,created_at,updated_at) VALUES ('BL90001','MARITIMO','2026-10-01','2026-10-01')"
        )
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, "varios expedientes"):
            reception.add_scanned_truck_bl(self.db, self.guide, "BL-90001", "operador.test", "ADMINISTRADOR")
        self.assertEqual(list(self.db.iterdump()), before)

    def test_maritime_later_partial_arrival_remains_visible_after_previous_attention_advanced(self):
        self.db.execute("UPDATE reception_shipments SET transport_type='MARITIMO',expected_packages=0")
        reception.add_scanned_truck_bl(self.db, self.guide, "BL-90001", "operador.test", "ADMINISTRADOR")
        reception.scan_truck_package(self.db, self.guide, self.shipment_id, "SEA-FIRST", "operador.test", "ADMINISTRADOR")
        reception.finalize_scanned_truck_arrival(self.db, self.guide, "", "operador.test", "ADMINISTRADOR")
        reception.process_truck_guide_locations(
            self.db, self.guide, [{"shipment_id":self.shipment_id,"locations":[{"location":"TEMP-1","package_count":1}]}],
            "operador.test", "ADMINISTRADOR",
        )
        self.db.execute("UPDATE reception_shipments SET app_status='EM'")
        self.db.execute("UPDATE reception_attentions SET app_status='EM'")
        second = reception.create_scanner_truck_guide(self.db, "operador.test", "ADMINISTRADOR")["truck_guide"]
        reception.add_scanned_truck_bl(self.db, second, "BL-90001", "operador.test", "ADMINISTRADOR")
        summary = reception.truck_guide_summary(self.db, second, "operador.test", "ADMINISTRADOR")
        self.assertTrue(summary["bls"][0]["truck_work_pending"])
        reception.scan_truck_package(self.db, second, self.shipment_id, "SEA-SECOND", "operador.test", "ADMINISTRADOR")
        arrival = reception.finalize_scanned_truck_arrival(self.db, second, "", "operador.test", "ADMINISTRADOR")
        self.assertTrue(arrival["bls"][0]["truck_work_pending"])
        self.assertEqual(arrival["count_startable_bl_count"], 1)
        attention_id = self.db.execute(
            "SELECT a.id FROM reception_attentions a JOIN reception_receipts r ON r.id=a.receipt_id WHERE r.truck_guide=?",
            (second,),
        ).fetchone()[0]
        self.assertEqual(arrival["bls"][0]["attention_id"], attention_id)
        self.assertEqual(arrival["bls"][0]["received_this_truck"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_receipts").fetchone()[0], 2)

    def test_bl_barcode_cannot_count_as_a_unique_box_and_stale_closed_selection_is_blocked(self):
        reception.add_scanned_truck_bl(self.db, self.guide, "BL-90001", "operador.test", "ADMINISTRADOR")
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, "no un codigo unico"):
            reception.scan_truck_package(self.db, self.guide, self.shipment_id, "bl 90001", "operador.test", "ADMINISTRADOR")
        self.assertEqual(list(self.db.iterdump()), before)
        self.db.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?", (self.shipment_id,))
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, "cerrada"):
            reception.scan_truck_package(self.db, self.guide, self.shipment_id, "SEA-BOX-01", "operador.test", "ADMINISTRADOR")
        self.assertEqual(list(self.db.iterdump()), before)

    def test_bl_entry_reports_other_active_truck_even_with_stale_pointer_or_manifest(self):
        reception.add_scanned_truck_bl(self.db, self.guide, "BL-90001", "operador.test", "ADMINISTRADOR")
        other = reception.create_scanner_truck_guide(self.db, "operador.test", "ADMINISTRADOR")["truck_guide"]
        for status in ("PENDIENTE", "EN_CURSO", "ZONA_RECEPCION"):
            self.db.execute("UPDATE reception_truck_guides SET guide_status=? WHERE guide_code=?", (status, self.guide))
            self.db.execute("UPDATE reception_shipments SET truck_guide=NULL WHERE id=?", (self.shipment_id,))
            before = list(self.db.iterdump())
            with self.assertRaisesRegex(ValueError, self.guide):
                reception.add_scanned_truck_bl(self.db, other, "BL-90001", "operador.test", "ADMINISTRADOR")
            self.assertEqual(list(self.db.iterdump()), before)
        self.db.execute("UPDATE reception_truck_bl_manifest SET operational_active=0")
        self.db.execute("UPDATE reception_shipments SET truck_guide=? WHERE id=?", (self.guide, self.shipment_id))
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, self.guide):
            reception.add_scanned_truck_bl(self.db, other, "BL-90001", "operador.test", "ADMINISTRADOR")
        self.assertEqual(list(self.db.iterdump()), before)

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

    def test_selected_bl_without_packages_does_not_block_scanned_arrival_locations(self):
        other_id = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary,
                transport_type, created_at, updated_at)
               VALUES ('BL-90003', 0, 'PROGRAMADO', 'operador.test', 'auxiliar.test',
                       'AEREO', '2026-10-01', '2026-10-01')"""
        ).lastrowid
        for code in ("BL-90001", "BL-90003"):
            reception.add_scanned_truck_bl(
                self.db, self.guide, code, "operador.test", "ASISTENTE_RECEPCION"
            )
        before = dict(self.db.execute(
            "SELECT * FROM reception_shipments WHERE id=?", (other_id,)
        ).fetchone())
        preview = reception.truck_guide_summary(
            self.db, self.guide, "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertTrue(next(row for row in preview["bls"] if row["id"] == other_id)["truck_work_pending"])
        reception.scan_truck_package(
            self.db, self.guide, self.shipment_id, "PKG-REAL", "operador.test", "ASISTENTE_RECEPCION"
        )
        arrived = reception.finalize_scanned_truck_arrival(
            self.db, self.guide, "", "operador.test", "ASISTENTE_RECEPCION"
        )
        untouched = next(row for row in arrived["bls"] if row["id"] == other_id)
        self.assertIsNone(untouched["arrival_id"])
        self.assertFalse(untouched["truck_work_pending"])
        self.assertFalse(arrived["steps_complete"])
        self.assertEqual(arrived["count_startable_bl_count"], 1)
        with self.assertRaisesRegex(ValueError, "cantidad y ubicaci"):
            reception.enable_truck_guide_counting(
                self.db, self.guide, "operador.test", "ASISTENTE_RECEPCION"
            )
        located = reception.process_truck_guide_locations(
            self.db, self.guide,
            [{"shipment_id": self.shipment_id,
              "locations": [{"location": "TEMP-A1", "package_count": 1}]}],
            "operador.test", "ASISTENTE_RECEPCION",
        )
        self.assertTrue(located["steps_complete"])
        self.assertTrue(located["counting_enabled"])
        self.assertEqual(located["received_packages"], 1)
        self.assertEqual(dict(self.db.execute(
            "SELECT * FROM reception_shipments WHERE id=?", (other_id,)
        ).fetchone()), before)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM reception_truck_bl_arrivals WHERE shipment_id=?", (other_id,)
        ).fetchone()[0], 0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM reception_attentions WHERE shipment_id=?", (other_id,)
        ).fetchone()[0], 0)

    def test_non_scanner_unknown_quantity_still_requires_an_explicit_arrival(self):
        reception.add_scanned_truck_bl(
            self.db, self.guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
        )
        self.db.execute("UPDATE reception_shipments SET expected_packages=0 WHERE id=?", (self.shipment_id,))
        self.db.execute(
            "UPDATE reception_truck_guides SET scanner_enabled=0, guide_status='ZONA_RECEPCION' WHERE guide_code=?",
            (self.guide,),
        )
        summary = reception.truck_guide_summary(
            self.db, self.guide, "operador.test", "ASISTENTE_RECEPCION"
        )
        self.assertTrue(summary["bls"][0]["truck_work_pending"])
        self.assertFalse(summary["steps_complete"])
        with self.assertRaisesRegex(ValueError, "cantidad y ubicaci"):
            reception.enable_truck_guide_counting(
                self.db, self.guide, "operador.test", "ASISTENTE_RECEPCION"
            )

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
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, "sigue en el camion"):
            reception.add_scanned_truck_bl(
                self.db, other_guide, "BL-90001", "operador.test", "ASISTENTE_RECEPCION"
            )
        self.assertEqual(list(self.db.iterdump()), before)
        # A later partial arrival is allowed only after the first truck is finished.
        self.db.execute(
            "UPDATE reception_truck_guides SET guide_status='LISTA_PARA_CONTEO' WHERE guide_code=?",
            (self.guide,),
        )
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
