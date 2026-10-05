import sqlite3
import unittest

from backend.services import reception


class DemoTruckGuideEligibilityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        reception.init_reception_schema(self.connection)

    def tearDown(self):
        self.connection.close()

    def _shipment(self, bl, status="PROGRAMADO", em_number="", expected=5, received=0):
        cursor = self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, received_packages, app_status, transport_type,
                em_number, scheduled_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'AEREO', ?, '2026-09-25', '2026-09-24', '2026-09-24')""",
            (bl, expected, received, status, em_number),
        )
        shipment_id = cursor.lastrowid
        self.connection.execute(
            "INSERT INTO reception_lines (shipment_id, np_code, expected_qty) VALUES (?, ?, 1)",
            (shipment_id, f"NP-{bl}"),
        )
        return shipment_id

    def _guide(self, bl):
        return self.connection.execute(
            "SELECT truck_guide FROM reception_shipments WHERE bl_awb = ?", (bl,)
        ).fetchone()[0]

    def test_only_unarrived_bl_without_em_gets_a_proposal(self):
        # Regression: an EM-stage or already-arrived BL was being regrouped
        # into a date-based truck proposal, creating a false pending arrival.
        eligible = self._shipment("BL-PENDIENTE")
        self._shipment("BL-EN-EM", status="EM")
        self._shipment("BL-EM-RESUMEN", em_number="EM-43821")
        self._shipment("BL-ARRIBADA", status="ARRIBADO")
        self._shipment("BL-CONTEO-EN-CURSO", status="REVISION SISTEMA", received=2)
        self._shipment("BL-CERRADA", status="CERRADO")
        self._shipment("BL-CANTIDAD-DESCONOCIDA", expected=0)
        self._shipment("BL-ARRIBO-LEGADO", received=1)
        self.connection.commit()

        reception.assign_demo_truck_guides(self.connection)

        self.assertTrue(self._guide("BL-PENDIENTE"))
        for bl in (
            "BL-EN-EM", "BL-EM-RESUMEN", "BL-ARRIBADA", "BL-CONTEO-EN-CURSO", "BL-CERRADA",
            "BL-ARRIBO-LEGADO",
        ):
            self.assertIsNone(self._guide(bl), bl)
        self.assertTrue(self._guide("BL-CANTIDAD-DESCONOCIDA"))
        pending_guide = self._guide("BL-CANTIDAD-DESCONOCIDA")
        self.assertEqual(
            reception.truck_guide_summary(
                self.connection, pending_guide, role="ADMINISTRADOR"
            )["data_pending_count"],
            1,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_truck_bl_manifest WHERE shipment_id = ?",
                (eligible,),
            ).fetchone()[0],
            1,
        )

    def test_em_recorded_by_ip_prevents_truck_proposal(self):
        shipment_id = self._shipment("BL-EM-IP")
        ref = self.connection.execute(
            """INSERT INTO reception_accounting_refs
               (shipment_id, source_key, ip_reference, fr_number, em_number, created_at, updated_at)
               VALUES (?, 'source-ip-em', 'IP260999-1', 'FR-299999', 'EM-43822', '2026-09-24', '2026-09-24')""",
            (shipment_id,),
        ).lastrowid
        self.connection.execute(
            """INSERT INTO reception_accounting_ems
               (accounting_ref_id, ip_reference_key, em_number, username, created_at)
               VALUES (?, 'IP2609991', 'EM-43822', 'test', '2026-09-24')""",
            (ref,),
        )
        self.connection.commit()

        reception.assign_demo_truck_guides(self.connection)

        self.assertIsNone(self._guide("BL-EM-IP"))

    def test_em_in_an_existing_proposal_is_not_pending_transit_work(self):
        shipment_id = self._shipment("BL-EM-GUIA", status="EM")
        guide = "CAMION-EM-ANTERIOR"
        self.connection.execute(
            """INSERT INTO reception_truck_guides
               (guide_code, planned_packages, source_type, is_confirmed, created_by, created_at, updated_at)
               VALUES (?, 5, 'PROPUESTA_FECHA', 0, 'test', '2026-09-24', '2026-09-24')""",
            (guide,),
        )
        self.connection.execute(
            """INSERT INTO reception_truck_bl_manifest
               (truck_guide, shipment_id, planned_packages, created_by, created_at, updated_at)
               VALUES (?, ?, 5, 'test', '2026-09-24', '2026-09-24')""",
            (guide, shipment_id),
        )
        em_summary_id = self._shipment(
            "BL-EM-RESUMEN-GUIA", em_number="EM-43823"
        )
        summary_guide = "CAMION-EM-RESUMEN"
        self.connection.execute(
            """INSERT INTO reception_truck_guides
               (guide_code, planned_packages, source_type, is_confirmed, created_by, created_at, updated_at)
               VALUES (?, 5, 'PROPUESTA_FECHA', 0, 'test', '2026-09-24', '2026-09-24')""",
            (summary_guide,),
        )
        self.connection.execute(
            """INSERT INTO reception_truck_bl_manifest
               (truck_guide, shipment_id, planned_packages, created_by, created_at, updated_at)
               VALUES (?, ?, 5, 'test', '2026-09-24', '2026-09-24')""",
            (summary_guide, em_summary_id),
        )
        self.connection.commit()

        self.assertEqual(reception.list_truck_guides(self.connection), [])
        summary = reception.truck_guide_summary(
            self.connection, guide, role="ADMINISTRADOR"
        )
        self.assertEqual(summary["open_expected_packages"], 0)
        self.assertEqual(summary["guide_status"], "FINALIZADA")
        self.assertFalse(summary["bls"][0]["truck_work_pending"])
        self.assertFalse(
            reception.truck_guide_summary(
                self.connection, summary_guide, role="ADMINISTRADOR"
            )["bls"][0]["truck_work_pending"]
        )


if __name__ == "__main__":
    unittest.main()
