"""Acceptance contract for a BL split across multiple truck arrivals.

The current pilot exposes truck-level APIs.  These tests define the per-BL
arrival API required for the Jose copy; they intentionally fail with a clear
message until that API is implemented.  Every fixture uses an in-memory
SQLite database and cannot modify the pilot's triton.db.
"""

import sqlite3
import unittest

from backend.services import reception


class TruckBLPartialArrivalTests(unittest.TestCase):
    """A shipment's expected packages are fulfilled across separate trucks."""

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        reception.init_reception_schema(self.connection)
        self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary, created_at, updated_at)
               VALUES ('BL-PARCIAL-5', 5, 'PROGRAMADO', 'asistente.test', 'auxiliar.test', '2026-09-23', '2026-09-23')"""
        )
        self.shipment_id = self.connection.execute(
            "SELECT id FROM reception_shipments WHERE bl_awb = 'BL-PARCIAL-5'"
        ).fetchone()["id"]
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def _api(self, name):
        api = getattr(reception, name, None)
        self.assertTrue(
            callable(api),
            f"API pendiente en backend.services.reception: {name}(). "
            "El piloto aún no expone operaciones de llegada por BL y camión.",
        )
        return api

    def _plan(self, guide, count):
        result = self._api("plan_truck_bl_packages")(
            self.connection,
            guide,
            self.shipment_id,
            count,
            "admin.test",
            "ADMINISTRADOR",
        )
        self._api("confirm_truck_guide")(
            self.connection, guide, f"REAL-{guide}", "admin.test", "ADMINISTRADOR"
        )
        return result

    def _confirm(self, guide, count, key):
        return self._api("confirm_truck_bl_arrival")(
            self.connection,
            guide,
            self.shipment_id,
            count,
            key,
            "asistente.test",
            "ASISTENTE_RECEPCION",
        )

    def _balance(self):
        return self._api("truck_bl_package_balance")(self.connection, self.shipment_id)

    def test_one_bl_can_be_planned_and_received_across_three_trucks(self):
        """Expected 5; truck arrivals 2, 1, 2 yield balances 2/3, 3/2, 5/0."""
        for guide, quantity, key, received, pending in (
            ("CAMION-1", 2, "arrival-1", 2, 3),
            ("CAMION-2", 1, "arrival-2", 3, 2),
            ("CAMION-3", 2, "arrival-3", 5, 0),
        ):
            self._plan(guide, quantity)
            self._confirm(guide, quantity, key)
            balance = self._balance()
            self.assertEqual(balance["expected_packages"], 5)
            self.assertEqual(balance["received_packages"], received)
            self.assertEqual(balance["pending_packages"], pending)

    def test_retrying_same_arrival_does_not_duplicate_received_packages(self):
        self._plan("CAMION-1", 2)
        first = self._confirm("CAMION-1", 2, "stable-arrival-id-1")
        retry = self._confirm("CAMION-1", 2, "stable-arrival-id-1")

        self.assertEqual(first["arrival_id"], retry["arrival_id"])
        balance = self._balance()
        self.assertEqual(balance["received_packages"], 2)
        self.assertEqual(balance["pending_packages"], 3)

    def test_zero_received_for_one_bl_keeps_its_balance_pending(self):
        self._plan("CAMION-1", 2)
        result = self._confirm("CAMION-1", 0, "arrival-with-missing-bl")

        self.assertEqual(result["received_packages"], 0)
        balance = self._balance()
        self.assertEqual(balance["expected_packages"], 5)
        self.assertEqual(balance["received_packages"], 0)
        self.assertEqual(balance["pending_packages"], 5)

    def test_location_belongs_to_each_arrival_and_does_not_overwrite_history(self):
        self._plan("CAMION-1", 2)
        first = self._confirm("CAMION-1", 2, "arrival-1")
        self._api("assign_truck_bl_arrival_location")(
            self.connection, first["arrival_id"], "ZONA-A", 2,
            "auxiliar.test", "AUXILIAR_RECEPCION",
        )

        self._plan("CAMION-2", 1)
        second = self._confirm("CAMION-2", 1, "arrival-2")
        self._api("assign_truck_bl_arrival_location")(
            self.connection, second["arrival_id"], "ZONA-B", 1,
            "auxiliar.test", "AUXILIAR_RECEPCION",
        )

        locations = self._api("list_truck_bl_arrival_locations")(
            self.connection, self.shipment_id
        )
        self.assertEqual(
            [(row["arrival_id"], row["location"], row["package_count"]) for row in locations],
            [(first["arrival_id"], "ZONA-A", 2), (second["arrival_id"], "ZONA-B", 1)],
        )

    def test_saving_plan_again_does_not_create_another_allocation(self):
        self._plan("CAMION-1", 2)
        before = self._api("list_truck_bl_plans")(self.connection, self.shipment_id)

        self._plan("CAMION-1", 2)
        after = self._api("list_truck_bl_plans")(self.connection, self.shipment_id)

        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["planned_packages"], 2)

    def test_bulk_arrival_requires_zero_for_missing_bl_and_saves_location_per_bl(self):
        second = self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, expected_packages, app_status, current_assistant, current_auxiliary, created_at, updated_at)
               VALUES ('BL-PARCIAL-OTRA', 3, 'PROGRAMADO', 'asistente.test', 'auxiliar.test', '2026-09-23', '2026-09-23')"""
        ).lastrowid
        self._plan("CAMION-1", 2)
        self._api("plan_truck_bl_packages")(
            self.connection, "CAMION-1", second, 3, "admin.test", "ADMINISTRADOR"
        )
        with self.assertRaisesRegex(ValueError, "cada BL activa"):
            self._api("process_truck_guide_arrivals")(
                self.connection, "CAMION-1",
                [{"shipment_id": self.shipment_id, "received_packages": 2,
                  "locations": [{"location": "Z-A", "package_count": 2}]}],
                "truck-event-1", "", "asistente.test", "ASISTENTE_RECEPCION",
            )
        result = self._api("process_truck_guide_arrivals")(
            self.connection, "CAMION-1",
            [
                {"shipment_id": self.shipment_id, "received_packages": 2,
                 "locations": [{"location": "Z-A", "package_count": 2}]},
                {"shipment_id": second, "received_packages": 0, "locations": []},
            ],
            "truck-event-1", "", "asistente.test", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(result["received_packages"], 2)
        self.assertEqual(result["unlocated_packages"], 0)
        rows = {row["bl_awb"]: row for row in result["bls"]}
        self.assertEqual(rows["BL-PARCIAL-5"]["received_this_truck"], 2)
        self.assertEqual(rows["BL-PARCIAL-OTRA"]["received_this_truck"], 0)
        self.assertEqual(rows["BL-PARCIAL-OTRA"]["pending_packages"], 3)
        self.assertEqual(len(reception.list_truck_bl_arrival_locations(self.connection, self.shipment_id)), 1)

    def test_closing_packages_moves_to_zone_and_locations_close_the_guide(self):
        self._plan("CAMION-1", 2)

        arrival = self._api("process_truck_guide_arrivals")(
            self.connection,
            "CAMION-1",
            [{"shipment_id": self.shipment_id, "received_packages": 2, "locations": []}],
            "truck-event-zone-step",
            "No habrá más bultos",
            "admin.test",
            "ADMINISTRADOR",
        )

        self.assertEqual(arrival["guide_status"], "ZONA_RECEPCION")
        self.assertEqual(arrival["unlocated_packages"], 2)
        closed = self._api("process_truck_guide_locations")(
            self.connection,
            "CAMION-1",
            [{
                "shipment_id": self.shipment_id,
                "locations": [{"location": "ZONA JOSE", "package_count": 2}],
            }],
            "admin.test",
            "ADMINISTRADOR",
        )

        self.assertEqual(closed["guide_status"], "LISTA_PARA_CONTEO")
        self.assertTrue(closed["counting_enabled"])
        self.assertEqual(closed["unlocated_packages"], 0)

    def test_new_truck_guide_is_selectable_before_any_bl_is_added(self):
        guide = self._api("create_truck_guide")(
            self.connection, "2026-09-23", "admin.test", "ADMINISTRADOR"
        )["truck_guide"]
        self.assertEqual(guide, "CAMION-20260923-01")
        summary = reception.truck_guide_summary(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )
        self.assertEqual(summary["bl_count"], 0)
        listed = reception.list_truck_guides(self.connection)
        self.assertIn(guide, [row["truck_guide"] for row in listed])


if __name__ == "__main__":
    unittest.main()
