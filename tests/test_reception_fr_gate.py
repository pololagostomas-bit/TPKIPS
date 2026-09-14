"""Regresiones de FR: SQLite en memoria, sin importar app ni abrir la BD real.

Ejecutar: py -B -m unittest tests.test_reception_fr_gate -v
"""

import sqlite3
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from backend.services import reception as service
from backend.services.traceability import init_traceability_schema


class ReceptionFRGateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        service.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute("""CREATE TABLE order_importation_refs
            (bl_awb TEXT, sap_ov TEXT, transport_type TEXT, ip_reference TEXT, oc_number TEXT)""")
        self.db.execute("CREATE TABLE attentions (id INTEGER PRIMARY KEY, sap_ov TEXT)")
        self.db.execute("PRAGMA foreign_keys = ON")
        lots = patch.object(service, "advanced_lots_enabled", return_value=False)
        lots.start()
        self.addCleanup(lots.stop)
        self.shipment_id = service.create_reception(
            self.db, {"bl_awb": "AWB-FR-TEST"}, "admin", "ADMINISTRADOR"
        )["id"]
        self.line_id = self.db.execute(
            """INSERT INTO reception_lines (shipment_id, np_code, expected_qty)
               VALUES (?, 'NP-TEST', 5)""", (self.shipment_id,)
        ).lastrowid

    def references(self, **values):
        return service.update_reception_references(
            self.db, self.shipment_id, values, "admin", "ADMINISTRADOR"
        )

    def assign(self):
        return self.references(current_assistant="assistant", current_auxiliary="auxiliary")

    def arrive(self, quantity=1):
        return service.add_physical_receipt(
            self.db, self.shipment_id, {"received_packages": quantity},
            "auxiliary", "AUXILIAR_RECEPCION",
        )

    def change(self, status, username="assistant", role="ASISTENTE_RECEPCION"):
        return service.change_reception_status(
            self.db, self.shipment_id, {"status": status}, username, role
        )

    def start_review(self):
        self.assign()
        self.arrive()
        return self.change("REVISION SISTEMA")

    def accounting_row(self, ip, fr="", em=""):
        return self.db.execute(
            """INSERT INTO reception_accounting_refs
               (shipment_id, source_key, ip_reference, fr_number, em_number, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, '2026-09-07', '2026-09-07')""",
            (self.shipment_id, ip, ip, fr, em),
        ).lastrowid

    def test_assignment_arrival_and_review_without_fr(self):
        self.assign()
        arrived = self.arrive()
        self.assertEqual(arrived["app_status"], "ARRIBADO")
        reviewed = self.change("REVISION SISTEMA")
        self.assertEqual(reviewed["accounting_status"], "PENDIENTE CONTABILIDAD")
        self.assertEqual(reviewed["lines"][0]["received_qty"], 5)
        changed = service.update_reception_line_quantity(
            self.db, self.shipment_id, self.line_id,
            {"received_qty": 4, "reason": "Faltante"}, "auxiliary", "AUXILIAR_RECEPCION",
        )
        self.assertEqual(changed["lines"][0]["received_qty"], 4)
        self.assertEqual(changed["app_status"], "REVISION SISTEMA")

    def test_warning_in_detail_and_list_does_not_enqueue_email(self):
        assigned = self.assign()
        self.assertIn("EM", assigned["accounting_warning"])
        self.assertIn("factura de reserva", assigned["accounting_warning"].lower())
        listed = service.list_receptions(self.db, "", "ASISTENTE_RECEPCION", "assistant")
        self.assertEqual(listed[0]["accounting_warning"], assigned["accounting_warning"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_notifications").fetchone()[0], 0)
        completed = self.references(fr_number="FR-1")
        self.assertEqual(completed["accounting_warning"], "")

    def test_pending_shipments_visible_only_to_assigned_responsibles(self):
        self.assign()
        for status in ("PENDIENTE CONTABILIDAD", "PENDIENTE FR", "CONFLICTO IP"):
            self.db.execute("UPDATE reception_shipments SET accounting_status = ?", (status,))
            for role, username in (("ASISTENTE_RECEPCION", "assistant"), ("AUXILIAR_RECEPCION", "auxiliary")):
                for state in ("PROGRAMADO", "ARRIBADO", "REVISION SISTEMA"):
                    with self.subTest(status=status, role=role, state=state):
                        self.db.execute("UPDATE reception_shipments SET app_status = ?", (state,))
                        for search in ("", "AWB-FR-TEST", "NP-TEST"):
                            rows = service.list_receptions(self.db, search, role, username)
                            self.assertEqual([row["id"] for row in rows], [self.shipment_id])
                        self.assertEqual(service.list_receptions(self.db, "", role, "someone-else"), [])
                        with self.assertRaises(PermissionError):
                            service.reception_detail(self.db, self.shipment_id, role, "someone-else")
        self.assertEqual(len(service.list_receptions(self.db)), 1)
        with self.assertRaises(PermissionError):
            service.list_receptions(self.db, role="PICKER", username="assistant")

    def test_missing_fr_blocks_em_without_mutations_or_lots(self):
        self.start_review()
        before = list(self.db.iterdump())
        with patch.object(service, "advanced_lots_enabled", return_value=True), patch.object(
            service, "generate_lots_for_shipment"
        ) as generate:
            for role, username in (("ADMINISTRADOR", "admin"), ("ASISTENTE_RECEPCION", "assistant"), ("AUXILIAR_RECEPCION", "auxiliary")):
                with self.subTest(role=role), self.assertRaisesRegex(PermissionError, "factura de reserva"):
                    self.change("EM", username, role)
            generate.assert_not_called()
        self.assertEqual(list(self.db.iterdump()), before)

    def test_manual_fr_unblocks_em_but_em_number_still_required_for_location(self):
        self.start_review()
        self.references(fr_number="FR-MANUAL")
        self.assertEqual(self.change("EM")["app_status"], "EM")
        with self.assertRaisesRegex(PermissionError, "Registra la EM"):
            self.change("UBICACION")
        self.references(em_number="EM-MANUAL")
        self.assertEqual(self.change("UBICACION")["app_status"], "UBICACION")

    def test_partial_fr_by_ip_allows_review_but_blocks_em(self):
        self.db.execute("UPDATE reception_lines SET ip_reference = 'IP-1, IP-2'")
        self.accounting_row("IP-1", "FR-1")
        self.references(fr_number="FR-1")
        self.assertEqual(self.start_review()["accounting_status"], "PENDIENTE FR")
        with self.assertRaisesRegex(PermissionError, "factura de reserva"):
            self.change("EM")
        self.accounting_row("IP-2", "FR-2")
        # El resumen almacenado sigue pendiente: la puerta debe consultar las IP actuales.
        self.assertEqual(self.change("EM")["app_status"], "EM")

    def test_stale_ready_summary_cannot_bypass_missing_ip_fr(self):
        self.db.execute("UPDATE reception_lines SET ip_reference = 'IP-1, IP-2'")
        self.accounting_row("IP-1", "FR-1")
        self.assign()
        self.arrive()
        self.db.execute("""UPDATE reception_shipments SET app_status = 'REVISION SISTEMA',
            accounting_status = 'PENDIENTE EM', fr_number = 'FR-1'""")
        with self.assertRaisesRegex(PermissionError, "factura de reserva"):
            self.change("EM")

    def test_reference_without_ip_and_fr_cannot_bypass_gate(self):
        self.accounting_row("", "", "EM-ONLY")
        self.assign()
        self.arrive()
        self.db.execute("""UPDATE reception_shipments SET app_status = 'REVISION SISTEMA',
            fr_number = 'FR-UNRELATED', accounting_status = 'PENDIENTE EM'""")
        with self.assertRaisesRegex(PermissionError, "factura de reserva"):
            self.change("EM")

    def test_conflict_is_visible_and_blocks_at_em_not_review(self):
        self.db.execute("UPDATE reception_shipments SET accounting_conflict_count = 1")
        self.assertEqual(self.start_review()["app_status"], "REVISION SISTEMA")
        self.references(fr_number="FR-CONFLICT")
        with self.assertRaisesRegex(PermissionError, "IP"):
            self.change("EM")

    def test_accounting_import_completes_missing_fr_without_losing_review(self):
        self.db.execute("UPDATE reception_lines SET ip_reference = 'IP-1, IP-2'")
        workbook = Workbook()
        self.addCleanup(workbook.close)
        sheet = workbook.active
        sheet.title = "FACTURAS DHL"
        sheet.append(["AWB", "IP", "FACTURA RESERVA", "ENTRADA DE MERCANCIA", "FECHA DE RECEPCION", "FECHA DE EM"])
        sheet.append(["AWB-FR-TEST", "IP-1", "FR-1", "", "", ""])
        service.import_reception_accounting_workbook(
            self.db, workbook, "synthetic.xlsx", "admin", "ADMINISTRADOR"
        )
        self.assertEqual(self.start_review()["accounting_status"], "PENDIENTE FR")
        service.update_reception_line_quantity(
            self.db, self.shipment_id, self.line_id, {"received_qty": 4, "reason": "Faltante"},
            "auxiliary", "AUXILIAR_RECEPCION",
        )
        with self.assertRaisesRegex(PermissionError, "factura de reserva"):
            self.change("EM")
        sheet.append(["AWB-FR-TEST", "IP-2", "FR-2", "", "", ""])
        result = service.import_reception_accounting_workbook(
            self.db, workbook, "synthetic.xlsx", "admin", "ADMINISTRADOR"
        )
        self.assertEqual(result["references_created"], 1)
        detail = service.reception_detail(self.db, self.shipment_id)
        self.assertEqual(detail["app_status"], "REVISION SISTEMA")
        self.assertEqual(detail["accounting_status"], "PENDIENTE EM")
        self.assertEqual(detail["accounting_warning"], "")
        self.assertEqual(detail["lines"][0]["received_qty"], 4)
        self.assertEqual(self.change("EM")["app_status"], "EM")

    def test_complete_reference_fr_allows_em_without_summary_fr(self):
        self.start_review()
        self.db.execute("UPDATE reception_lines SET ip_reference = 'IP-1'")
        self.accounting_row("IP-1", "FR-1")
        with patch("backend.services.traceability.advanced_lots_enabled", return_value=True), patch.object(
            service, "advanced_lots_enabled", return_value=True
        ), patch.object(
            service, "generate_lots_for_shipment", wraps=service.generate_lots_for_shipment
        ) as generate:
            result = self.change("EM")
            generate.assert_called_once_with(self.db, self.shipment_id, "assistant")
        self.assertEqual(result["app_status"], "EM")
        self.assertEqual(len(result["lots"]), 1)
        self.assertEqual(result["lots"][0]["received_qty"], 5)

    def test_blank_fr_blocks_em_even_with_stale_ready_status(self):
        self.assign()
        self.arrive()
        for fr in (None, "", "   "):
            with self.subTest(fr=fr):
                self.db.execute("""UPDATE reception_shipments SET app_status = 'REVISION SISTEMA',
                    fr_number = ?, accounting_status = 'PENDIENTE EM'""", (fr,))
                with self.assertRaisesRegex(PermissionError, "factura de reserva"):
                    self.change("EM")

    def test_assignment_required_but_incomplete_arrival_does_not_block_review(self):
        self.db.execute("UPDATE reception_shipments SET app_status = 'ARRIBADO'")
        with self.assertRaisesRegex(PermissionError, "asistente y un auxiliar"):
            self.change("REVISION SISTEMA", "admin", "ADMINISTRADOR")
        self.assign()
        self.db.execute("UPDATE reception_shipments SET expected_packages = 2")
        self.arrive()
        self.assertEqual(self.change("REVISION SISTEMA")["app_status"], "REVISION SISTEMA")
        self.arrive()

    def test_permissions_sequential_flow_and_review_only_edits_unchanged(self):
        self.assign()
        with self.assertRaises(PermissionError):
            self.change("ARRIBADO", "intruder")
        with self.assertRaisesRegex(PermissionError, "una etapa"):
            self.change("EM")
        with self.assertRaises(PermissionError):
            service.update_reception_line_quantity(
                self.db, self.shipment_id, self.line_id, {"received_qty": 1},
                "auxiliary", "AUXILIAR_RECEPCION",
            )
        self.arrive()
        self.change("REVISION SISTEMA")
        self.assertEqual(self.arrive()["app_status"], "REVISION SISTEMA")
        with self.assertRaises(PermissionError):
            self.change("REVISION SISTEMA")


if __name__ == "__main__":
    unittest.main()
