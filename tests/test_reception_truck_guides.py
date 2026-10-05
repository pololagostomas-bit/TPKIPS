import sqlite3
import unittest

from backend.services import reception
from backend.services.traceability import init_traceability_schema


class ReceptionTruckGuideTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        reception.init_reception_schema(self.connection)
        init_traceability_schema(self.connection)
        # list_receptions correlates optional references imported by the
        # procurement module; the unit fixture needs only its read schema.
        self.connection.execute(
            """CREATE TABLE order_importation_refs (
                   bl_awb TEXT, sap_ov TEXT, transport_type TEXT,
                   ip_reference TEXT, oc_number TEXT
               )"""
        )

    def tearDown(self):
        self.connection.close()

    def _shipment(
        self,
        bl_awb,
        guide=None,
        expected_packages=0,
        scheduled_date="2026-09-22",
        app_status="PROGRAMADO",
        transport_type="AEREO",
    ):
        cursor = self.connection.execute(
            """INSERT INTO reception_shipments
               (bl_awb, truck_guide, expected_packages, app_status, scheduled_date, transport_type,
                current_assistant, current_auxiliary, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'asistente.test', 'auxiliar.test', '2026-09-22T00:00:00', '2026-09-22T00:00:00')""",
            (bl_awb, guide, expected_packages, app_status, scheduled_date, transport_type),
        )
        self.connection.execute(
            "INSERT INTO reception_lines (shipment_id, np_code, expected_qty) VALUES (?, ?, 1)",
            (cursor.lastrowid, f"NP-{bl_awb}"),
        )

    def _guide_for(self, bl_awb):
        return self.connection.execute(
            "SELECT id, truck_guide FROM reception_shipments WHERE bl_awb = ?", (bl_awb,)
        ).fetchone()

    def _arrive_and_enable(self, guide, received=6):
        reception.confirm_truck_guide(
            self.connection, guide, f"REAL-{guide}", "admin.test", "ADMINISTRADOR"
        )
        summary = reception.truck_guide_summary(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )
        remaining = float(received or 0)
        bls = []
        for item in summary["bls"]:
            if item["app_status"] == "CERRADO":
                continue
            amount = min(float(item["planned_packages"] or 0), remaining)
            remaining -= amount
            bls.append({
                "shipment_id": item["id"],
                "received_packages": int(amount),
                "locations": ([{"location": "ZONA A", "package_count": int(amount)}]
                              if amount else []),
            })
        reception.process_truck_guide_arrivals(
            self.connection, guide, bls, f"test-arrival-{guide}",
            "Manifiesto DHL de prueba", "admin.test", "ADMINISTRADOR",
        )
        return reception.enable_truck_guide_counting(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )

    def test_admin_can_correct_temporary_location_at_every_bl_stage(self):
        self._shipment('BL-ADMIN-LOCATION', expected_packages=3)
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for('BL-ADMIN-LOCATION')
        self._arrive_and_enable(shipment['truck_guide'], received=3)
        receipt_id = self.connection.execute(
            'SELECT id FROM reception_receipts WHERE shipment_id=?', (shipment['id'],)
        ).fetchone()[0]
        for stage in reception.RECEPTION_STATES:
            with self.subTest(stage=stage):
                self.connection.execute('UPDATE reception_shipments SET app_status=? WHERE id=?', (stage, shipment['id']))
                destination = 'TEMP-' + stage
                reception.update_reception_location(
                    self.connection, shipment['id'], {'receipt_id': receipt_id, 'location': destination},
                    'admin.test', 'ADMINISTRADOR',
                )
                self.assertEqual(self.connection.execute(
                    'SELECT app_status FROM reception_shipments WHERE id=?', (shipment['id'],)
                ).fetchone()[0], stage)
                self.assertEqual(self.connection.execute(
                    'SELECT location_text FROM reception_receipts WHERE id=?', (receipt_id,)
                ).fetchone()[0], destination)
                location = self.connection.execute(
                    '''SELECT l.location_text, l.package_count FROM reception_truck_bl_locations l
                       JOIN reception_truck_bl_arrivals a ON a.id=l.arrival_id WHERE a.shipment_id=?''',
                    (shipment['id'],),
                ).fetchone()
                self.assertEqual(tuple(location), (destination, 3))
        with self.assertRaises(PermissionError):
            reception.update_reception_location(
                self.connection, shipment['id'], {'receipt_id': receipt_id, 'location': 'UNAUTHORIZED'},
                'asistente.test', 'ASISTENTE_RECEPCION',
            )
        self.assertTrue(self.connection.execute(
            "SELECT 1 FROM reception_history WHERE shipment_id=? AND event_type='ZONA RECEPCION' AND old_value='TEMP-ARRIBADO'",
            (shipment['id'],),
        ).fetchone())

    def test_count_does_not_require_current_or_historical_location(self):
        self._shipment('BL-HISTORY-LOCATION', expected_packages=3)
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for('BL-HISTORY-LOCATION')
        self._arrive_and_enable(shipment['truck_guide'], received=3)
        self.connection.execute(
            '''INSERT INTO reception_receipts
               (shipment_id, sequence_no, received_packages, location_text, username, received_at)
               VALUES (?, 0, 1, NULL, 'legacy', '2026-09-01')''', (shipment['id'],)
        )
        self.connection.execute(
            "UPDATE reception_receipts SET location_text='' WHERE shipment_id=? AND truck_guide=?",
            (shipment['id'], shipment['truck_guide']),
        )
        result = reception.change_reception_status(
            self.connection, shipment['id'], {'status': 'REVISION SISTEMA', 'require_location': True},
            'admin.test', 'ADMINISTRADOR',
        )
        self.assertEqual(result['app_status'], 'REVISION SISTEMA')
        self.assertIsNone(self.connection.execute(
            'SELECT location_text FROM reception_receipts WHERE shipment_id=? AND sequence_no=0',
            (shipment['id'],),
        ).fetchone()[0])

    def test_confirmed_date_defines_one_truck_for_several_bls(self):
        self._shipment("BL-CAMION-1")
        self._shipment("BL-CAMION-2")
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)

        rows = self.connection.execute(
            "SELECT truck_guide FROM reception_shipments WHERE COALESCE(TRIM(truck_guide), '') <> ''"
        ).fetchall()
        self.assertEqual({row["truck_guide"] for row in rows}, {"CAMION-20260922-01"})
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_truck_guides WHERE guide_code = 'CAMION-20260922-01'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_shipments WHERE truck_guide = 'CAMION-20260922-01'"
            ).fetchone()[0],
            2,
        )

    def test_grouping_is_idempotent_and_never_changes_bl_operational_data(self):
        self._shipment("BL-ESTABLE-1", expected_packages=3)
        self._shipment("BL-ESTABLE-2", expected_packages=5, app_status="REVISION SISTEMA")
        self.connection.execute(
            "UPDATE reception_shipments SET received_packages = 2 WHERE bl_awb = 'BL-ESTABLE-2'"
        )
        self.connection.commit()

        reception.assign_demo_truck_guides(self.connection)
        first = self.connection.execute(
            """SELECT bl_awb, truck_guide, expected_packages, received_packages, app_status
                 FROM reception_shipments ORDER BY bl_awb"""
        ).fetchall()
        reception.assign_demo_truck_guides(self.connection)
        second = self.connection.execute(
            """SELECT bl_awb, truck_guide, expected_packages, received_packages, app_status
                 FROM reception_shipments ORDER BY bl_awb"""
        ).fetchall()

        self.assertEqual([tuple(row) for row in first], [tuple(row) for row in second])
        self.assertEqual(
            [("BL-ESTABLE-1", "CAMION-20260922-01", 3.0, 0.0, "PROGRAMADO"),
             ("BL-ESTABLE-2", None, 5.0, 2.0, "REVISION SISTEMA")],
            [tuple(row) for row in second],
        )

    def test_truck_tracking_keeps_bl_counts_independent(self):
        for index in range(21):
            self._shipment(f"BL-{index:02d}", expected_packages=2)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)

        rows = reception.list_receptions(
            self.connection, limit=10, truck_guide="CAMION-20260922-01"
        )
        next_truck = reception.list_receptions(
            self.connection, limit=10, truck_guide="CAMION-20260922-02"
        )

        self.assertEqual(len(rows), 20)
        self.assertEqual(len(next_truck), 1)
        self.assertEqual(
            {row["truck_guide"] for row in reception.list_truck_guides(self.connection, "0922")},
            {"CAMION-20260922-01", "CAMION-20260922-02"},
        )
        self.assertEqual(
            [row["truck_guide"] for row in reception.list_truck_guides(self.connection, "BL19")],
            ["CAMION-20260922-01"],
        )
        guide = rows[0]["truck_guide"]
        self.assertEqual({row["truck_guide"] for row in rows}, {guide})
        before = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(received_packages), 0) FROM reception_receipts"
        ).fetchone()
        result = reception.process_truck_arrival(
            self.connection,
            guide,
            40,
            [
                {"location": "ZONA A", "package_count": 25},
                {"location": "ZONA B", "package_count": 15},
            ],
            "Diferencia informativa: DHL esperaba 40",
            "admin.test",
            "ADMINISTRADOR",
            True,
        )
        self.assertEqual(result["bl_count"], 20)
        self.assertEqual(result["expected_packages"], 40)
        self.assertEqual(result["received_packages"], 0)
        self.assertEqual(result["legacy_unallocated"], True)
        self.assertEqual(result["legacy_tracking"]["received_packages"], 40)
        self.assertEqual(result["unlocated_packages"], 0)
        self.assertEqual(result["locations"], [])
        self.assertEqual(result["legacy_tracking"]["locations"], [
            {"location_text": "ZONA A", "package_count": 25.0},
            {"location_text": "ZONA B", "package_count": 15.0},
        ])
        self.assertFalse(result["steps_complete"])
        with self.assertRaises(ValueError):
            reception.enable_truck_guide_counting(
                self.connection, guide, "admin.test", "ADMINISTRADOR"
            )
        after = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(received_packages), 0) FROM reception_receipts"
        ).fetchone()
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(
            self.connection.execute("SELECT COALESCE(SUM(received_packages), 0) FROM reception_shipments").fetchone()[0],
            0,
        )

    def test_legacy_aggregate_remains_visible_but_not_added_to_new_bl_receipts(self):
        self._shipment("BL-LEGADO-MAS-NUEVO", expected_packages=2)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment_id, guide = self._guide_for("BL-LEGADO-MAS-NUEVO")
        reception.plan_truck_bl_packages(
            self.connection, guide, shipment_id, 1, "admin.test", "ADMINISTRADOR"
        )
        reception.confirm_truck_guide(
            self.connection, guide, "GR-LEGADO-REAL", "admin.test", "ADMINISTRADOR"
        )
        arrival = reception.confirm_truck_bl_arrival(
            self.connection, guide, shipment_id, 1, "new-arrival-key",
            "admin.test", "ADMINISTRADOR",
        )
        reception.assign_truck_bl_arrival_location(
            self.connection, arrival["arrival_id"], "ZONA NUEVA", 1,
            "admin.test", "ADMINISTRADOR",
        )
        self.connection.execute(
            """INSERT INTO reception_truck_arrivals
               (truck_guide, expected_packages, received_packages, notes, username, received_at, updated_at)
               VALUES (?, 15, 15, 'Histórico no distribuido', 'admin.test', '2026-09-01', '2026-09-01')""",
            (guide,),
        )
        self.connection.execute(
            "INSERT INTO reception_truck_locations (truck_guide, location_text, package_count) VALUES (?, 'ZONA HISTORICA', 15)",
            (guide,),
        )
        summary = reception.truck_guide_summary(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )
        self.assertEqual(summary["received_packages"], 1)
        self.assertTrue(summary["legacy_unallocated"])
        self.assertEqual(summary["legacy_tracking"]["received_packages"], 15)

    def test_counting_cannot_be_enabled_before_the_truck_arrives(self):
        self._shipment("BL-SIN-LLEGADA", expected_packages=4)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        guide = self._guide_for("BL-SIN-LLEGADA")["truck_guide"]

        with self.assertRaises(ValueError):
            reception.enable_truck_guide_counting(
                self.connection, guide, "admin.test", "ADMINISTRADOR"
            )

        self.assertEqual(
            self.connection.execute(
                "SELECT guide_status FROM reception_truck_guides WHERE guide_code = ?", (guide,)
            ).fetchone()[0],
            "PENDIENTE",
        )

    def test_counting_requires_both_reception_responsibles(self):
        self._shipment("BL-SIN-RESPONSABLE", expected_packages=2)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        guide = self._guide_for("BL-SIN-RESPONSABLE")["truck_guide"]
        summary = reception.truck_guide_summary(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )
        reception.confirm_truck_guide(
            self.connection, guide, f"REAL-{guide}", "admin.test", "ADMINISTRADOR"
        )
        reception.process_truck_guide_arrivals(
            self.connection, guide,
            [{"shipment_id": summary["bls"][0]["id"], "received_packages": 2,
              "locations": [{"location": "ZONA A", "package_count": 2}]}],
            "arrival-no-assistant", "", "admin.test", "ADMINISTRADOR",
        )
        self.connection.execute(
            "UPDATE reception_shipments SET current_assistant = '' WHERE bl_awb = 'BL-SIN-RESPONSABLE'"
        )
        with self.assertRaisesRegex(PermissionError, "asistente y un auxiliar"):
            reception.enable_truck_guide_counting(
                self.connection, guide, "admin.test", "ADMINISTRADOR"
            )
        self.connection.execute(
            "UPDATE reception_shipments SET current_assistant = 'asistente.test' WHERE bl_awb = 'BL-SIN-RESPONSABLE'"
        )
        reception.enable_truck_guide_counting(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )

    def test_split_arrivals_have_independent_attentions_and_can_start_out_of_order(self):
        self._shipment("BL-DOS-ATENCIONES", expected_packages=5, scheduled_date="2026-09-23")
        shipment = self._guide_for("BL-DOS-ATENCIONES")
        shipment_id = shipment["id"]
        self.connection.execute(
            """UPDATE reception_lines
                  SET np_code='NP-5', description='Artículo de prueba', expected_qty=5
                WHERE shipment_id=?""",
            (shipment_id,),
        )
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        first_guide = self._guide_for("BL-DOS-ATENCIONES")["truck_guide"]
        reception.plan_truck_bl_packages(
            self.connection, first_guide, shipment_id, 2, "admin.test", "ADMINISTRADOR"
        )
        reception.confirm_truck_guide(
            self.connection, first_guide, f"REAL-{first_guide}", "admin.test", "ADMINISTRADOR"
        )
        reception.process_truck_guide_arrivals(
            self.connection, first_guide,
            [{"shipment_id": shipment_id, "received_packages": 1,
              "locations": [{"location": "ZONA 1", "package_count": 1}]}],
            "first-truck-event", "", "admin.test", "ADMINISTRADOR",
        )
        reception.enable_truck_guide_counting(
            self.connection, first_guide, "admin.test", "ADMINISTRADOR"
        )
        reception.start_truck_guide_bl_counting(
            self.connection, first_guide, shipment_id, "admin.test", "ADMINISTRADOR"
        )
        first_attention = reception._active_reception_attention(self.connection, shipment_id)
        self.connection.execute(
            "UPDATE reception_attention_lines SET verified_qty=2 WHERE attention_id=?",
            (first_attention["id"],),
        )

        second_guide = reception.create_truck_guide(
            self.connection, "2026-09-23", "admin.test", "ADMINISTRADOR"
        )["truck_guide"]
        reception.plan_truck_bl_packages(
            self.connection, second_guide, shipment_id, 1, "admin.test", "ADMINISTRADOR"
        )
        reception.confirm_truck_guide(
            self.connection, second_guide, f"REAL-{second_guide}", "admin.test", "ADMINISTRADOR"
        )
        reception.process_truck_guide_arrivals(
            self.connection, second_guide,
            [{"shipment_id": shipment_id, "received_packages": 1,
              "locations": [{"location": "ZONA 2", "package_count": 1}]}],
            "second-truck-event", "", "admin.test", "ADMINISTRADOR",
        )
        reception.enable_truck_guide_counting(
            self.connection, second_guide, "admin.test", "ADMINISTRADOR"
        )
        second_count = reception.start_truck_guide_bl_counting(
            self.connection, second_guide, shipment_id, "admin.test", "ADMINISTRADOR"
        )
        self.assertTrue(second_count["counting_started"])
        queued_receipt = self.connection.execute(
            "SELECT id FROM reception_receipts WHERE shipment_id=? AND truck_guide=?",
            (shipment_id, second_guide),
        ).fetchone()
        self.assertIsNotNone(self.connection.execute(
            "SELECT 1 FROM reception_attentions WHERE receipt_id=?", (queued_receipt["id"],)
        ).fetchone())

        self.connection.execute(
            "UPDATE reception_shipments SET app_status='SOLICITUD TRANSFERENCIA', transfer_assistant_checked=1 WHERE id=?",
            (shipment_id,),
        )
        reception.change_reception_status(
            self.connection, shipment_id, {"status": "CERRADO"},
            "admin.test", "ADMINISTRADOR",
        )
        self.assertEqual(self.connection.execute(
            "SELECT app_status FROM reception_shipments WHERE id=?", (shipment_id,)
        ).fetchone()[0], "REVISION SISTEMA")
        self.assertEqual(self.connection.execute(
            "SELECT pending_packages FROM (SELECT 5 - received_packages AS pending_packages FROM reception_shipments WHERE id=?)",
            (shipment_id,),
        ).fetchone()[0], 3)

        second_count = reception.start_truck_guide_bl_counting(
            self.connection, second_guide, shipment_id, "admin.test", "ADMINISTRADOR"
        )
        self.assertFalse(second_count["counting_started"])
        second_attention = self.connection.execute(
            """SELECT a.sequence_no, a.receipt_id, r.truck_guide
                 FROM reception_attentions a JOIN reception_receipts r ON r.id=a.receipt_id
                WHERE a.shipment_id=? ORDER BY a.sequence_no DESC LIMIT 1""",
            (shipment_id,),
        ).fetchone()
        self.assertEqual(second_attention["sequence_no"], 2)
        self.assertEqual(second_attention["truck_guide"], second_guide)
        self.assertEqual(self.connection.execute(
            "SELECT planned_qty FROM reception_attention_lines WHERE attention_id=(SELECT id FROM reception_attentions WHERE shipment_id=? AND sequence_no=2)",
            (shipment_id,),
        ).fetchone()[0], 3)

    def test_arrival_then_enable_marks_only_the_guide_ready_for_counting(self):
        self._shipment("BL-LISTA-1", expected_packages=3)
        self._shipment("BL-LISTA-2", expected_packages=3)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        guide = self._guide_for("BL-LISTA-1")["truck_guide"]

        summary = self._arrive_and_enable(guide)

        self.assertEqual(summary["guide_status"], "LISTA_PARA_CONTEO")
        header = self.connection.execute(
            """SELECT guide_status, count_enabled_at, count_enabled_by
                 FROM reception_truck_guides WHERE guide_code = ?""",
            (guide,),
        ).fetchone()
        self.assertEqual(header["guide_status"], "LISTA_PARA_CONTEO")
        self.assertIsNotNone(header["count_enabled_at"])
        self.assertEqual(header["count_enabled_by"], "admin.test")
        # La llegada física registra la cantidad y su atención por BL; habilitar
        # conteo solo cambia el estado de la guía.
        rows = self.connection.execute(
            """SELECT app_status, received_packages FROM reception_shipments
                 WHERE truck_guide = ?""",
            (guide,),
        ).fetchall()
        self.assertEqual({tuple(row) for row in rows}, {("ARRIBADO", 3.0)})
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM reception_attentions").fetchone()[0], 2
        )

    def test_start_count_reuses_the_confirmed_truck_arrival_attention(self):
        self._shipment(
            "BL-CERRADA", guide="CAMION-20260922-01", expected_packages=2, app_status="CERRADO"
        )
        self._shipment("BL-CON-RECIBO", expected_packages=2)
        self._shipment("BL-CON-CANTIDAD", expected_packages=2)
        self._shipment("BL-LIMPIA", expected_packages=2, scheduled_date="2026-09-23")
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        closed = self._guide_for("BL-CERRADA")
        received = self._guide_for("BL-CON-RECIBO")
        counted = self._guide_for("BL-CON-CANTIDAD")
        clean = self._guide_for("BL-LIMPIA")
        self.assertNotEqual(closed["truck_guide"], clean["truck_guide"])
        guide = clean["truck_guide"]
        # Este recibo histórico, no asociado a ninguna guía, no debe reiniciarse
        # ni adoptarse por el nuevo flujo de camión.
        self.connection.execute(
            """INSERT INTO reception_receipts
               (shipment_id, sequence_no, received_packages, notes, username, received_at)
               VALUES (?, 1, 1, '', 'admin.test', '2026-09-22T00:00:00')""",
            (received["id"],),
        )
        self.connection.execute(
            "UPDATE reception_shipments SET received_packages = 1 WHERE id = ?", (counted["id"],)
        )
        self.connection.commit()

        with self.assertRaises(ValueError):
            reception.start_truck_guide_bl_counting(
                self.connection, guide, clean["id"], "admin.test", "ADMINISTRADOR"
            )

        self._arrive_and_enable(guide, received=2)
        with self.assertRaises(ValueError):
            reception.start_truck_guide_bl_counting(
                self.connection, guide, closed["id"], "admin.test", "ADMINISTRADOR"
            )
        with self.assertRaises(ValueError):
            reception.start_truck_guide_bl_counting(
                self.connection, guide, received["id"], "admin.test", "ADMINISTRADOR"
            )
        with self.assertRaises(ValueError):
            reception.start_truck_guide_bl_counting(
                self.connection, guide, counted["id"], "admin.test", "ADMINISTRADOR"
            )

        detail = reception.start_truck_guide_bl_counting(
            self.connection, guide, clean["id"], "admin.test", "ADMINISTRADOR"
        )
        self.assertEqual(detail["shipment_id"], clean["id"])
        self.assertTrue(detail["counting_started"])
        self.assertEqual(detail["shipment"]["app_status"], "REVISION SISTEMA")
        attention = self.connection.execute(
            """SELECT a.receipt_id, a.app_status, r.truck_guide
                 FROM reception_attentions a
                 LEFT JOIN reception_receipts r ON r.id = a.receipt_id
                 WHERE a.shipment_id = ?""",
            (clean["id"],),
        ).fetchone()
        self.assertIsNotNone(attention["receipt_id"])
        self.assertEqual(attention["truck_guide"], guide)
        self.assertEqual(attention["app_status"], "REVISION SISTEMA")
        self.assertEqual(self.connection.execute(
            "SELECT received_packages FROM reception_shipments WHERE id = ?", (clean["id"],)
        ).fetchone()[0], 2)

        # Reintentar el botón no duplica recibos ni atenciones.
        before = self.connection.execute(
            "SELECT COUNT(*) FROM reception_receipts WHERE shipment_id = ?", (clean["id"],)
        ).fetchone()[0]
        retry = reception.start_truck_guide_bl_counting(
            self.connection, guide, clean["id"], "admin.test", "ADMINISTRADOR"
        )
        self.assertFalse(retry["counting_started"])
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM reception_receipts WHERE shipment_id = ?", (clean["id"],)
        ).fetchone()[0], before)

    def test_revert_to_transit_returns_only_that_truck_quantity_to_pending_balance(self):
        self._shipment("BL-REVERSA-1", expected_packages=5)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-REVERSA-1")
        guide = shipment["truck_guide"]
        self.connection.execute(
            "UPDATE reception_truck_bl_manifest SET planned_packages=4 WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        )
        self.connection.execute(
            "UPDATE reception_shipments SET received_packages=1 WHERE id=?", (shipment["id"],)
        )
        self.connection.execute(
            """INSERT INTO reception_receipts
               (shipment_id, sequence_no, received_packages, notes, location_text, username, received_at)
               VALUES (?, 1, 1, 'Llegada anterior', '', 'asistente.test', '2026-09-20')""",
            (shipment["id"],),
        )
        self.connection.commit()
        self._arrive_and_enable(guide, received=4)
        before = self.connection.execute(
            "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        ).fetchone()[0]

        result = reception.revert_truck_guide(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )

        self.assertTrue(result["reverted"])
        self.assertEqual(
            self.connection.execute(
                "SELECT guide_status FROM reception_truck_guides WHERE guide_code = ?", (guide,)
            ).fetchone()[0],
            "PENDIENTE",
        )
        self.assertEqual(self.connection.execute(
            "SELECT planned_packages FROM reception_truck_bl_manifest WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        ).fetchone()[0], before)
        current = self.connection.execute(
            "SELECT app_status, received_packages FROM reception_shipments WHERE id=?", (shipment["id"],)
        ).fetchone()
        self.assertEqual(tuple(current), ("PROGRAMADO", 1))
        balance = reception.truck_bl_package_balance(self.connection, shipment["id"])
        self.assertEqual(balance["received_packages"], 1)
        self.assertEqual(balance["pending_packages"], 4)
        self.assertEqual(balance["planned_unarrived_packages"], 4)
        truck_receipt = self.connection.execute(
            "SELECT received_packages FROM reception_receipts WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        ).fetchone()
        self.assertEqual(truck_receipt["received_packages"], 0)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?)", (guide,)
        ).fetchone()[0], 0)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_truck_arrivals WHERE truck_guide = ?", (guide,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_truck_locations WHERE truck_guide = ?", (guide,)
            ).fetchone()[0],
            0,
        )

    def test_revert_to_arrival_stage_keeps_truck_arrival_and_locations(self):
        self._shipment("BL-ETAPA-1", expected_packages=3)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        guide = self._guide_for("BL-ETAPA-1")["truck_guide"]
        self._arrive_and_enable(guide, received=3)

        result = reception.revert_truck_guide(
            self.connection, guide, "admin.test", "ADMINISTRADOR", "EN_CURSO"
        )

        self.assertEqual(result["reverted_to"], "EN_CURSO")
        self.assertEqual(
            self.connection.execute(
                "SELECT guide_status FROM reception_truck_guides WHERE guide_code = ?", (guide,)
            ).fetchone()[0],
            "EN_CURSO",
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT SUM(received_packages) FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?)", (guide,)
            ).fetchone()[0], 3,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT SUM(l.package_count) FROM reception_truck_bl_locations l JOIN reception_truck_bl_arrivals a ON a.id=l.arrival_id WHERE lower(a.truck_guide)=lower(?)", (guide,)
            ).fetchone()[0], 3,
        )

    def test_reopened_transit_records_a_new_arrival_without_double_counting(self):
        self._shipment("BL-CORRIGE-ARRIBO", expected_packages=5)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-CORRIGE-ARRIBO")
        guide = shipment["truck_guide"]
        self._arrive_and_enable(guide, received=3)
        reception.revert_truck_guide(
            self.connection, guide, "admin.test", "ADMINISTRADOR", "PENDIENTE"
        )
        result = reception.process_truck_guide_arrivals(
            self.connection,
            guide,
            [{"shipment_id": shipment["id"], "received_packages": 2, "locations": []}],
            f"corrected-{guide}",
            "Corrección de cantidad llegada",
            "admin.test",
            "ADMINISTRADOR",
        )

        arrival = self.connection.execute(
            "SELECT id, received_packages FROM reception_truck_bl_arrivals WHERE shipment_id = ? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        ).fetchone()
        receipt = self.connection.execute(
            "SELECT received_packages, location_text FROM reception_receipts WHERE shipment_id = ? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        ).fetchone()
        self.assertEqual(arrival["received_packages"], 2)
        self.assertEqual(tuple(receipt), (2, ""))
        self.assertEqual(
            self.connection.execute(
                "SELECT received_packages, app_status FROM reception_shipments WHERE id = ?",
                (shipment["id"],),
            ).fetchone()["app_status"],
            "ARRIBADO",
        )
        self.assertEqual(result["guide_status"], "ZONA_RECEPCION")
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_history WHERE shipment_id = ? AND event_type = 'ARRIBO CAMION'",
                (shipment["id"],),
            ).fetchone()[0],
            2,
        )

    def test_reversing_later_truck_keeps_the_first_truck_arrival(self):
        self._shipment("BL-DOS-CAMIONES-REV", expected_packages=5)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-DOS-CAMIONES-REV")
        first_guide = shipment["truck_guide"]
        self.connection.execute(
            "UPDATE reception_truck_bl_manifest SET planned_packages=1 WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], first_guide),
        )
        self._arrive_and_enable(first_guide, received=1)

        second_guide = reception.create_truck_guide(
            self.connection, "2026-09-22", "admin.test", "ADMINISTRADOR"
        )["truck_guide"]
        reception.plan_truck_bl_packages(
            self.connection, second_guide, shipment["id"], 4, "admin.test", "ADMINISTRADOR"
        )
        self._arrive_and_enable(second_guide, received=4)
        self.assertEqual(
            reception.truck_bl_package_balance(self.connection, shipment["id"])["received_packages"],
            5,
        )

        reception.revert_truck_guide(
            self.connection, second_guide, "admin.test", "ADMINISTRADOR", "PENDIENTE"
        )
        remaining = reception.truck_bl_package_balance(self.connection, shipment["id"])
        self.assertEqual(remaining["received_packages"], 1)
        self.assertEqual(remaining["pending_packages"], 4)
        self.assertEqual(
            self.connection.execute(
                "SELECT received_packages FROM reception_truck_bl_arrivals WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
                (shipment["id"], first_guide),
            ).fetchone()[0],
            1,
        )
        self.assertIsNone(self.connection.execute(
            "SELECT 1 FROM reception_truck_bl_arrivals WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], second_guide),
        ).fetchone())

    def test_arrival_correction_requires_bl_to_remain_before_count(self):
        self._shipment("BL-CORRIGE-AVANZADA", expected_packages=5)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-CORRIGE-AVANZADA")
        guide = shipment["truck_guide"]
        self._arrive_and_enable(guide, received=3)
        reception.start_truck_guide_bl_counting(
            self.connection, guide, shipment["id"], "admin.test", "ADMINISTRADOR"
        )
        with self.assertRaisesRegex(PermissionError, "ya inició su conteo"):
            reception.revert_truck_guide(
                self.connection, guide, "admin.test", "ADMINISTRADOR", "PENDIENTE"
            )
        self.assertEqual(self.connection.execute(
            "SELECT received_packages FROM reception_shipments WHERE id=?", (shipment["id"],)
        ).fetchone()[0], 3)

    def test_revert_completed_truck_to_zone_stage_preserves_bl_and_arrival(self):
        self._shipment("BL-REVERSA-ZONA", expected_packages=3)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-REVERSA-ZONA")
        guide = shipment["truck_guide"]
        self._arrive_and_enable(guide, received=3)
        before_bl = self.connection.execute(
            "SELECT app_status, received_packages FROM reception_shipments WHERE id = ?",
            (shipment["id"],),
        ).fetchone()

        result = reception.revert_truck_guide(
            self.connection, guide, "admin.test", "ADMINISTRADOR", "ZONA_RECEPCION"
        )

        self.assertEqual(result["reverted_to"], "ZONA_RECEPCION")
        self.assertEqual(
            self.connection.execute(
                "SELECT guide_status FROM reception_truck_guides WHERE guide_code = ?", (guide,)
            ).fetchone()[0],
            "ZONA_RECEPCION",
        )
        after_bl = self.connection.execute(
            "SELECT app_status, received_packages FROM reception_shipments WHERE id = ?",
            (shipment["id"],),
        ).fetchone()
        self.assertEqual(tuple(after_bl), tuple(before_bl))
        self.assertEqual(
            self.connection.execute(
                "SELECT SUM(received_packages) FROM reception_truck_bl_arrivals WHERE lower(truck_guide)=lower(?)",
                (guide,),
            ).fetchone()[0],
            3,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT SUM(l.package_count) FROM reception_truck_bl_locations l JOIN reception_truck_bl_arrivals a ON a.id=l.arrival_id WHERE lower(a.truck_guide)=lower(?)",
                (guide,),
            ).fetchone()[0],
            3,
        )

    def test_guide_search_accepts_guide_bl_and_last_four_characters(self):
        self._shipment("DHL-AWB-1234-ABCD", expected_packages=2, scheduled_date="2026-09-22")
        self._shipment("DHL-AWB-9999-WXYZ", expected_packages=2, scheduled_date="2026-09-23")
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        first_guide = self._guide_for("DHL-AWB-1234-ABCD")["truck_guide"]
        second_guide = self._guide_for("DHL-AWB-9999-WXYZ")["truck_guide"]

        self.assertEqual(
            [row["truck_guide"] for row in reception.list_truck_guides(self.connection, first_guide)],
            [first_guide],
        )
        self.assertEqual(
            [row["truck_guide"] for row in reception.list_truck_guides(self.connection, "1234-ABCD")],
            [first_guide],
        )
        self.assertEqual(
            [row["truck_guide"] for row in reception.list_truck_guides(self.connection, "ABCD")],
            [first_guide],
        )
        self.assertEqual(
            [row["truck_guide"] for row in reception.list_truck_guides(self.connection, "0923")],
            [second_guide],
        )

    def test_dhl_manifest_quantity_is_exposed_on_the_bl_in_reception(self):
        self._shipment("BL-DHL-ESPERADA", expected_packages=0)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-DHL-ESPERADA")
        guide = shipment["truck_guide"]
        expected = self.connection.execute(
            "SELECT expected_packages FROM reception_truck_manifest WHERE shipment_id = ?",
            (shipment["id"],),
        ).fetchone()[0]
        self.connection.execute(
            "UPDATE reception_truck_guides SET guide_status = 'LISTA_PARA_CONTEO' WHERE guide_code = ?",
            (guide,),
        )
        self.connection.commit()

        listed = reception.list_receptions(self.connection, truck_guide=guide)
        detail = reception.reception_detail(self.connection, shipment["id"])

        self.assertEqual(listed[0]["expected_packages"], expected)
        self.assertEqual(detail["expected_packages"], expected)

    def test_truck_expected_total_is_the_sum_of_open_bl_dhl_quantities(self):
        self._shipment("BL-SUMA-1", expected_packages=4)
        self._shipment("BL-SUMA-2", expected_packages=7)
        self._shipment("BL-CERRADA", expected_packages=9, app_status="CERRADO")
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)

        guide = self._guide_for("BL-SUMA-1")["truck_guide"]
        summary = reception.truck_guide_summary(
            self.connection, guide, "admin.test", "ADMINISTRADOR"
        )

        self.assertEqual(summary["expected_packages"], 11)
        self.assertEqual(summary["open_expected_packages"], 11)
        self.assertEqual(summary["closed_expected_packages"], 0)
        self.assertEqual(summary["remaining_packages"], 11)
        self.assertEqual(
            self.connection.execute(
                "SELECT planned_packages FROM reception_truck_guides WHERE guide_code = ?", (guide,)
            ).fetchone()[0],
            11,
        )

    def test_auto_generation_only_assigns_open_air_or_courier_parts(self):
        self._shipment("BL-AEREA", expected_packages=2, transport_type="AEREO")
        self._shipment("BL-COURIER", expected_packages=2, transport_type="COURIER")
        self._shipment("BL-MARITIMA", expected_packages=2, transport_type="MARITIMO")
        self._shipment("BL-CERRADA-NUEVA", expected_packages=2, app_status="CERRADO")
        self._shipment("BL-SERVICIO", expected_packages=2, transport_type="AEREO")
        service_id = self._guide_for("BL-SERVICIO")["id"]
        self.connection.execute("UPDATE reception_lines SET np_code='' WHERE shipment_id=?", (service_id,))
        reception.assign_demo_truck_guides(self.connection)

        assigned = {
            row["bl_awb"] for row in self.connection.execute(
                "SELECT bl_awb FROM reception_shipments WHERE TRIM(COALESCE(truck_guide,''))<>''"
            ).fetchall()
        }
        self.assertEqual(assigned, {"BL-AEREA", "BL-COURIER"})

    def test_proposal_requires_admin_confirmation_and_common_assistant_can_close_arrival(self):
        self._shipment("BL-RESP-1", expected_packages=1)
        self._shipment("BL-RESP-2", expected_packages=1)
        self.connection.execute(
            "UPDATE reception_shipments SET current_assistant='otro.usuario' WHERE bl_awb='BL-RESP-2'"
        )
        reception.assign_demo_truck_guides(self.connection)
        guide = self._guide_for("BL-RESP-1")["truck_guide"]
        summary = reception.truck_guide_summary(self.connection, guide)
        payload = [
            {"shipment_id": row["id"], "received_packages": 0, "locations": []}
            for row in summary["bls"] if row["app_status"] != "CERRADO"
        ]
        with self.assertRaises(PermissionError):
            reception.process_truck_guide_arrivals(
                self.connection, guide, payload, "proposal-attempt", "",
                "asistente.test", "ASISTENTE_RECEPCION",
            )
        reception.confirm_truck_guide(
            self.connection, guide, "GR-REAL-001", "admin.test", "ADMINISTRADOR"
        )
        result = reception.process_truck_guide_arrivals(
            self.connection, guide, payload, "confirmed-arrival", "",
            "asistente.test", "ASISTENTE_RECEPCION",
        )
        self.assertEqual(result["guide_status"], "ZONA_RECEPCION")
        self.assertEqual(result["received_packages"], 0)

    def test_missing_expected_is_visible_and_admin_correction_is_audited(self):
        self._shipment("BL-SIN-ESPERADO", expected_packages=0)
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-SIN-ESPERADO")
        guide = shipment["truck_guide"]
        queued = reception.list_truck_guides(self.connection)
        self.assertEqual(queued[0]["data_pending_count"], 1)
        reception.confirm_truck_guide(
            self.connection, guide, "GR-REAL-002", "admin.test", "ADMINISTRADOR"
        )
        corrected = reception.update_truck_bl_expected_packages(
            self.connection, guide, shipment["id"], 3,
            "Confirmado en guía física", "admin.test", "ADMINISTRADOR",
        )
        line = next(row for row in corrected["bls"] if row["id"] == shipment["id"])
        self.assertEqual(line["expected_packages"], 3)
        self.assertEqual(line["planned_packages"], 3)
        self.assertTrue(self.connection.execute(
            "SELECT 1 FROM reception_history WHERE shipment_id=? AND event_type='CORRECCION CAMION'",
            (shipment["id"],),
        ).fetchone())

    def test_admin_can_remove_bl_from_proposal_without_it_being_generated_again(self):
        self._shipment("BL-PROPUESTA-ERRONEA", expected_packages=2)
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-PROPUESTA-ERRONEA")
        guide = shipment["truck_guide"]

        reception.remove_truck_bl_from_proposal(
            self.connection, guide, shipment["id"],
            "No pertenece al transporte confirmado", "admin.test", "ADMINISTRADOR",
        )
        reception.assign_demo_truck_guides(self.connection)

        current = self.connection.execute(
            "SELECT truck_guide FROM reception_shipments WHERE id=?", (shipment["id"],)
        ).fetchone()
        self.assertIsNone(current["truck_guide"])
        archived = self.connection.execute(
            "SELECT operational_active FROM reception_truck_bl_manifest WHERE shipment_id=?",
            (shipment["id"],),
        ).fetchone()
        self.assertIsNotNone(archived)
        self.assertEqual(archived["operational_active"], 0)
        self.assertTrue(self.connection.execute(
            """SELECT 1 FROM reception_history
                 WHERE shipment_id=? AND event_type='CORRECCION CAMION'
                   AND field_name='truck_auto_excluded'""",
            (shipment["id"],),
        ).fetchone())

    def test_legacy_received_packages_reduce_new_truck_planning_balance(self):
        self._shipment("BL-LEGACY-SALDO", expected_packages=5)
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-LEGACY-SALDO")
        original = shipment["truck_guide"]
        self.connection.execute(
            "UPDATE reception_shipments SET received_packages=3 WHERE id=?", (shipment["id"],)
        )
        self.connection.execute(
            "DELETE FROM reception_truck_bl_manifest WHERE shipment_id=?", (shipment["id"],)
        )
        second = reception.create_truck_guide(
            self.connection, "2026-09-23", "admin.test", "ADMINISTRADOR"
        )["truck_guide"]
        with self.assertRaises(ValueError):
            reception.plan_truck_bl_packages(
                self.connection, second, shipment["id"], 3, "admin.test", "ADMINISTRADOR"
            )
        planned = reception.plan_truck_bl_packages(
            self.connection, second, shipment["id"], 2, "admin.test", "ADMINISTRADOR"
        )
        self.assertEqual(planned["planned_packages"], 2)

    def test_legacy_bl_receipt_does_not_block_remaining_packages_on_a_truck(self):
        self._shipment("BL-SALDO-HISTORICO", expected_packages=5)
        self.connection.commit()
        reception.assign_demo_truck_guides(self.connection)
        shipment = self._guide_for("BL-SALDO-HISTORICO")
        guide = shipment["truck_guide"]
        self.connection.execute(
            "UPDATE reception_truck_bl_manifest SET planned_packages=4 WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
            (shipment["id"], guide),
        )
        self.connection.execute(
            "UPDATE reception_shipments SET received_packages=1 WHERE id=?", (shipment["id"],)
        )
        self.connection.execute(
            """INSERT INTO reception_receipts
               (shipment_id, sequence_no, received_packages, notes, location_text, username, received_at)
               VALUES (?, 1, 1, 'Recepción histórica', '', 'asistente.test', '2026-09-22T09:00:00')""",
            (shipment["id"],),
        )
        reception.confirm_truck_guide(
            self.connection, guide, f"REAL-{guide}", "admin.test", "ADMINISTRADOR"
        )

        reception.process_truck_guide_arrivals(
            self.connection,
            guide,
            [{"shipment_id": shipment["id"], "received_packages": 4, "locations": []}],
            f"arrival-historic-{guide}",
            "Llegó el saldo pendiente",
            "admin.test",
            "ADMINISTRADOR",
        )

        total = self.connection.execute(
            "SELECT received_packages FROM reception_shipments WHERE id=?", (shipment["id"],)
        ).fetchone()[0]
        self.assertEqual(total, 5)
        self.assertEqual(
            self.connection.execute(
                "SELECT received_packages FROM reception_truck_bl_arrivals WHERE shipment_id=? AND lower(truck_guide)=lower(?)",
                (shipment["id"], guide),
            ).fetchone()[0],
            4,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM reception_receipts WHERE shipment_id=?", (shipment["id"],)
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
