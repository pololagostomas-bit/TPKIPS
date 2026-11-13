"""Public truck numbers belong to confirmed physical arrivals, not drafts."""
import sqlite3
import unittest
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from unittest.mock import patch
from backend.services import reception


class TruckOperationalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        self.db.execute("""CREATE TABLE order_importation_refs
            (bl_awb TEXT,sap_ov TEXT,transport_type TEXT,ip_reference TEXT,oc_number TEXT)""")
        self.sid = self.db.execute("""INSERT INTO reception_shipments
            (bl_awb,transport_type,expected_packages,app_status,current_assistant,created_at,updated_at)
            VALUES ('QA-SEA-ONE','MARITIMO',3,'PROGRAMADO','qa.worker','2026-11-13','2026-11-13')""").lastrowid

    def draft(self):
        with patch.object(reception, "reception_now", return_value="2026-11-13 09:00:00"):
            return reception.create_scanner_truck_guide(self.db, "qa.worker", "ASISTENTE_RECEPCION")["truck_guide"]

    def receive(self, guide, code):
        reception.add_scanned_truck_bl(self.db, guide, "QA-SEA-ONE", "qa.worker", "ASISTENTE_RECEPCION")
        reception.scan_truck_package(self.db, guide, self.sid, code, "qa.worker", "ASISTENTE_RECEPCION")
        with patch.object(reception, "reception_now", return_value="2026-11-13 09:10:00"):
            return reception.finalize_scanned_truck_arrival(self.db, guide, "", "qa.worker", "ASISTENTE_RECEPCION")

    def test_opening_and_cancelling_drafts_does_not_allocate_a_number(self):
        first = self.draft()
        summary = reception.truck_guide_summary(self.db, first, "qa.worker", "ASISTENTE_RECEPCION")
        self.assertTrue(summary.get("is_draft"))
        self.assertEqual(summary["truck_label"], "Camión en preparación")
        reception.cancel_scanned_truck_arrival(self.db, first, "qa.worker", "ASISTENTE_RECEPCION")
        second = self.draft()
        confirmed = self.receive(second, "QA-BOX-ONE")
        self.assertEqual(confirmed["truck_label"], "CAMION-261113-01")
        self.assertFalse(confirmed["is_draft"])
        self.assertEqual(confirmed["truck_guide"], second)
        self.assertNotEqual(first, second)
        found=reception.list_truck_guides(self.db,search="CAMION-261113-01",role="ASISTENTE_RECEPCION",username="qa.worker",include_completed=True)
        self.assertEqual([row['truck_guide'] for row in found],[second])

    def test_partial_confirmation_and_retry_keep_the_same_public_number(self):
        guide = self.draft()
        confirmed = self.receive(guide, "QA-BOX-ONE")
        try:
            again = reception.finalize_scanned_truck_arrival(
                self.db, guide, "", "qa.worker", "ASISTENTE_RECEPCION")
        except ValueError as error:
            self.fail("Retry of a saved arrival must be idempotent: " + str(error))
        self.assertEqual(again["truck_label"], confirmed["truck_label"])
        self.assertEqual(again["received_packages"], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM reception_receipts").fetchone()[0], 1)
        self.assertEqual(again["bls"][0]["package_progress"]["expected"], 3)

    def test_historical_scan_identifiers_and_relationships_stay_unchanged(self):
        guide = self.draft()
        self.db.execute("UPDATE reception_truck_guides SET guide_code='SCAN-20261001-01' WHERE guide_code=?", (guide,))
        reception.init_reception_schema(self.db)
        summary = reception.truck_guide_summary(self.db, "SCAN-20261001-01", "qa.worker", "ASISTENTE_RECEPCION")
        self.assertEqual(summary["truck_guide"], "SCAN-20261001-01")
        self.assertEqual(summary.get("truck_label"), "SCAN-20261001-01")
        self.assertFalse(summary["is_draft"])

    def test_empty_confirmation_cannot_allocate_a_number(self):
        guide = self.draft()
        with self.assertRaises(ValueError):
            reception.finalize_scanned_truck_arrival(self.db, guide, "", "qa.worker", "ASISTENTE_RECEPCION")
        self.assertTrue(reception.truck_guide_summary(self.db, guide, "qa.worker", "ASISTENTE_RECEPCION").get("is_draft"))

    def test_confirmed_arrival_keeps_its_documented_total_when_source_is_missing(self):
        guide=self.draft();self.receive(guide,"QA-TOTAL")
        self.db.execute("UPDATE reception_shipments SET expected_packages=0 WHERE id=?",(self.sid,))
        report=reception.reception_report(self.db)
        self.assertEqual(report['filtered_summary']['partial_bl'],1)
        summary=reception.truck_guide_summary(self.db,guide,"qa.worker","ASISTENTE_RECEPCION")
        self.assertEqual(summary['bls'][0]['package_progress']['expected'],3)

    def test_two_partial_trucks_get_consecutive_numbers_without_changing_internal_keys(self):
        first=self.draft();second=self.draft()
        self.assertEqual(self.receive(first,"QA-A")["truck_label"],"CAMION-261113-01")
        self.assertEqual(self.receive(second,"QA-B")["truck_label"],"CAMION-261113-02")
        codes=[r[0] for r in self.db.execute("SELECT truck_guide FROM reception_receipts")]
        self.assertEqual(codes,[first,second])

    def test_rolled_back_confirmation_does_not_consume_the_number(self):
        guide=self.draft()
        self.db.execute("SAVEPOINT qa")
        self.receive(guide,"QA-ROLLBACK")
        self.db.execute("ROLLBACK TO qa");self.db.execute("RELEASE qa")
        self.assertEqual(self.receive(guide,"QA-REAL")["truck_label"],"CAMION-261113-01")

    def test_simultaneous_confirmations_get_unique_numbers(self):
        first=self.draft();second=self.draft()
        other=self.db.execute("""INSERT INTO reception_shipments
            (bl_awb,transport_type,expected_packages,app_status,current_assistant,created_at,updated_at)
            VALUES ('QA-SEA-TWO','MARITIMO',1,'PROGRAMADO','qa.worker','2026-11-13','2026-11-13')""").lastrowid
        for guide,sid,bl in [(first,self.sid,"QA-SEA-ONE"),(second,other,"QA-SEA-TWO")]:
            reception.add_scanned_truck_bl(self.db,guide,bl,"qa.worker","ASISTENTE_RECEPCION")
            reception.scan_truck_package(self.db,guide,sid,bl+"-BOX","qa.worker","ASISTENTE_RECEPCION")
        self.db.commit()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"qa.sqlite"
            with closing(sqlite3.connect(path)) as target:self.db.backup(target)
            def finalize(guide):
                connection=sqlite3.connect(path,timeout=10);connection.row_factory=sqlite3.Row
                try:
                    with connection:
                        return reception.finalize_scanned_truck_arrival(
                            connection,guide,"","qa.worker","ASISTENTE_RECEPCION")["truck_label"]
                finally:connection.close()
            with patch.object(reception,"reception_now",return_value="2026-11-13 09:30:00"):
                with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(finalize,[first,second]))
        self.assertEqual(set(codes),{"CAMION-261113-01","CAMION-261113-02"})

    def test_atomic_numbering_without_an_explicit_transaction(self):
        guides=[self.draft() for _ in range(20)]
        self.db.commit()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'qa.sqlite'
            with closing(sqlite3.connect(path)) as target:self.db.backup(target)
            barrier=Barrier(2)
            def number(guide):
                with closing(sqlite3.connect(path,timeout=10,isolation_level=None)) as connection:
                    barrier.wait(timeout=5)
                    reception._number_scanned_truck(connection,guide)
                    return connection.execute('SELECT display_code FROM reception_truck_guides WHERE guide_code=?',(guide,)).fetchone()[0]
            with patch.object(reception,'reception_now',return_value='2026-11-13 09:30:00'):
                with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(number,guides))
        self.assertEqual(set(codes),{f'CAMION-261113-{i:02d}' for i in range(1,21)})
