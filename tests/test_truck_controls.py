import sqlite3
import unittest
from backend.services import reception
from backend.services.truck_controls import cancel_truck_guide
from backend.services.traceability import init_traceability_schema


class TruckControlsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute("CREATE TABLE order_importation_refs (bl_awb TEXT, sap_ov TEXT, transport_type TEXT, ip_reference TEXT, oc_number TEXT)")
        self.sid = self.db.execute(
            """INSERT INTO reception_shipments
               (bl_awb,expected_packages,current_assistant,current_auxiliary,created_at,updated_at)
               VALUES ('BL-CONTROLS',5,'operator','aux','2026-10-07','2026-10-07')"""
        ).lastrowid
        self.db.execute("INSERT INTO reception_lines (shipment_id,np_code,expected_qty) VALUES (?,'NP-CONTROLS',8)", (self.sid,))
        self.guide = "TRUCK-CONTROLS"
        reception.plan_truck_bl_packages(self.db, self.guide, self.sid, 2, "operator", "ADMINISTRADOR")
        reception.confirm_truck_guide(self.db, self.guide, self.guide, "operator", "ADMINISTRADOR")

    def tearDown(self):
        self.db.close()

    def arrive(self, guide=None, quantity=2):
        reception.process_truck_guide_arrivals(
            self.db, guide or self.guide, [{"shipment_id":self.sid,"received_packages":quantity}],
            "qa-" + (guide or self.guide), "", "operator", "ADMINISTRADOR"
        )

    def test_cancel_before_arrival_preserves_documents_and_is_idempotent(self):
        result = cancel_truck_guide(self.db,self.guide,"operator","ASISTENTE_RECEPCION")
        self.assertEqual(result["guide_status"],"CANCELADA")
        self.assertEqual(self.db.execute("SELECT operational_active FROM reception_truck_bl_manifest").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT expected_packages FROM reception_shipments").fetchone()[0],5)
        self.assertEqual(self.db.execute("SELECT expected_qty FROM reception_lines").fetchone()[0],8)
        before=list(self.db.iterdump())
        cancel_truck_guide(self.db,self.guide,"operator","ADMINISTRADOR")
        self.assertEqual(before,list(self.db.iterdump()))

    def test_arrived_cancel_requires_admin_without_changes(self):
        self.arrive()
        before=list(self.db.iterdump())
        with self.assertRaises(PermissionError):
            cancel_truck_guide(self.db,self.guide,"operator","ASISTENTE_RECEPCION")
        self.assertEqual(before,list(self.db.iterdump()))

    def test_other_assistant_cannot_cancel_assigned_truck(self):
        before=list(self.db.iterdump())
        with self.assertRaises(PermissionError):
            cancel_truck_guide(self.db,self.guide,"different.operator","ASISTENTE_RECEPCION")
        self.assertEqual(before,list(self.db.iterdump()))

    def test_cancel_after_arrival_only_annuls_this_truck(self):
        other="OTHER-TRUCK"
        reception.plan_truck_bl_packages(self.db,other,self.sid,1,"operator","ADMINISTRADOR")
        reception.confirm_truck_guide(self.db,other,other,"operator","ADMINISTRADOR")
        self.arrive(other,1)
        self.arrive()
        cancel_truck_guide(self.db,self.guide,"operator","ADMINISTRADOR")
        self.assertEqual(self.db.execute("SELECT received_packages FROM reception_shipments").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT truck_guide FROM reception_truck_bl_arrivals").fetchone()[0],other)
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CANCELACION CAMION'").fetchone()[0],0)

    def test_completed_back_to_location_keeps_receipts(self):
        self.arrive()
        reception.process_truck_guide_locations(
            self.db,self.guide,[{"shipment_id":self.sid,"locations":[{"location":"TEMP-A","package_count":2}]}],
            "operator","ADMINISTRADOR")
        before=[tuple(row) for row in self.db.execute("SELECT * FROM reception_truck_bl_arrivals")]
        reception.revert_truck_guide(self.db,self.guide,"operator","ADMINISTRADOR","ZONA_RECEPCION")
        self.assertEqual(before,[tuple(row) for row in self.db.execute("SELECT * FROM reception_truck_bl_arrivals")])
        self.assertEqual(self.db.execute("SELECT location_text FROM reception_truck_bl_locations").fetchone()[0],"TEMP-A")

    def test_counted_bl_blocks_cancellation_atomically(self):
        self.arrive()
        self.db.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA'")
        before=list(self.db.iterdump())
        with self.assertRaises(PermissionError):
            cancel_truck_guide(self.db,self.guide,"operator","ADMINISTRADOR")
        self.assertEqual(before,list(self.db.iterdump()))

    def test_auxiliary_cannot_cancel(self):
        before=list(self.db.iterdump())
        with self.assertRaises(PermissionError):
            cancel_truck_guide(self.db,self.guide,"aux","AUXILIAR_RECEPCION")
        self.assertEqual(before,list(self.db.iterdump()))

    def test_cancelled_guide_stays_cancelled_after_schema_initialization(self):
        cancel_truck_guide(self.db,self.guide,"operator","ADMINISTRADOR")
        reception.init_reception_schema(self.db)
        self.assertEqual(self.db.execute("SELECT guide_status FROM reception_truck_guides WHERE guide_code=?", (self.guide,)).fetchone()[0],"CANCELADA")
        self.assertEqual(self.db.execute("SELECT operational_active FROM reception_truck_bl_manifest WHERE truck_guide=?", (self.guide,)).fetchone()[0],0)

    @unittest.skipUnless(hasattr(reception,"create_scanner_truck_guide"),"Manual variant has no scanner")
    def test_scanner_cancel_after_arrival_voids_scans_not_documents(self):
        guide=reception.create_scanner_truck_guide(self.db,"operator","ADMINISTRADOR")["truck_guide"]
        reception.add_scanned_truck_bl(self.db,guide,"BL-CONTROLS","operator","ADMINISTRADOR")
        reception.scan_truck_package(self.db,guide,self.sid,"PKG-CONTROLS","operator","ADMINISTRADOR")
        reception.finalize_scanned_truck_arrival(self.db,guide,"","operator","ADMINISTRADOR")
        cancel_truck_guide(self.db,guide,"operator","ADMINISTRADOR")
        self.assertEqual(self.db.execute("SELECT scan_status FROM reception_truck_package_scans").fetchone()[0],"ANULADO")
        self.assertEqual(self.db.execute("SELECT expected_qty FROM reception_lines").fetchone()[0],8)


if __name__ == "__main__":
    unittest.main()
