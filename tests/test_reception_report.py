import sqlite3
import unittest

from backend.services import reception


class ReceptionReportTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        reception.init_reception_schema(self.db)

    def tearDown(self):
        self.db.close()

    def _shipment(self, bl, status="ARRIBADO", transport="AEREO"):
        return self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb, transport_type, app_status, current_assistant, current_auxiliary,
                created_at, updated_at, first_arrival_at)
               VALUES (?, ?, ?, 'picker.test', 'aux.test', ?, ?, ?)""",
            (bl, transport, status, "2026-09-25 08:00:00", "2026-09-28 08:00:00",
             "2026-09-25 08:00:00"),
        ).lastrowid

    def test_report_counts_distinct_skus_and_sums_all_packing_list_units(self):
        shipment_id = self._shipment("BL-REPORT-1", status="CERRADO")
        self.db.execute(
            """INSERT INTO reception_history
               (shipment_id, event_type, field_name, old_value, new_value, username, created_at)
               VALUES (?, 'CAMBIO_ETAPA', 'app_status', 'VALIDACION', 'CERRADO', 'admin', ?)""",
            (shipment_id, "2026-09-28 08:00:00"),
        )
        self.db.executemany(
            """INSERT INTO reception_lines (shipment_id, np_code, expected_qty)
               VALUES (?, ?, ?)""",
            [(shipment_id, "NP-A", 4), (shipment_id, "NP-A", 6), (shipment_id, "NP-B", 3)],
        )
        self.db.commit()

        item = reception.reception_report(self.db)["items"][0]

        self.assertEqual(item["sku_count"], 2)
        self.assertEqual(item["total_units"], 13)
        self.assertEqual(item["sla_status"], "VERDE")
        self.assertEqual(item["remaining_hours"], 24)
        self.assertEqual(item["elapsed_hours"], 48)

    def test_closed_shipment_reports_finish_and_uses_same_color_filter_values(self):
        shipment_id = self._shipment("BL-REPORT-CLOSED", status="CERRADO")
        self.db.execute(
            """INSERT INTO reception_history
               (shipment_id, event_type, field_name, old_value, new_value, username, created_at)
               VALUES (?, 'CAMBIO_ETAPA', 'app_status', 'VALIDACION', 'CERRADO', 'admin', ?)""",
            (shipment_id, "2026-09-28 08:00:00"),
        )
        self.db.commit()

        report = reception.reception_report(self.db)
        item = report["items"][0]

        self.assertEqual(item["report_started_at"], "2026-09-25 08:00:00")
        self.assertEqual(item["report_closed_at"], "2026-09-28 08:00:00")
        self.assertEqual(item["elapsed_hours"], 48)
        self.assertIn(item["sla_status"], {"VERDE", "AMARILLO", "ROJO"})

    def test_sunday_is_excluded_from_elapsed_time(self):
        self.assertEqual(
            reception._elapsed_hours_excluding_sundays(
                "2026-09-26 12:00:00", "2026-09-28 12:00:00"
            ),
            24,
        )

    def test_missing_start_uses_only_three_semaphore_states(self):
        shipment_id = self._shipment("BL-REPORT-NO-ARRIVAL")
        self.db.execute(
            "UPDATE reception_shipments SET first_arrival_at = NULL WHERE id = ?",
            (shipment_id,),
        )
        self.db.commit()

        item = reception.reception_report(self.db)["items"][0]

        self.assertEqual(item["sla_status"], "AMARILLO")
        self.assertIsNone(item["elapsed_hours"])
        self.assertIn(item["sla_status"], {"VERDE", "AMARILLO", "ROJO"})


if __name__ == "__main__":
    unittest.main()
