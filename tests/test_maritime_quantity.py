"""Maritime quantity receipt, synthetic in-memory data only."""
import importlib.util
import sqlite3
import unittest
from unittest.mock import patch
from backend.services import reception,dhl_tracking
from tests import test_reception_barcode_scanning as fixtures


class MaritimeQuantityTests(unittest.TestCase):
    tearDown = fixtures.ReceptionBarcodeScanningTests.tearDown

    def setUp(self):
        fixtures.ReceptionBarcodeScanningTests.setUp(self)
        self.db.execute("UPDATE reception_shipments SET transport_type='MARITIMO',expected_packages=0")
        reception.add_scanned_truck_bl(self.db,self.guide,'BL-90001','operator','ASISTENTE_RECEPCION')

    def save(self,quantity=8,version=0,role='ASISTENTE_RECEPCION'):
        self.assertIsNotNone(importlib.util.find_spec('backend.services.maritime_intake'))
        from backend.services import maritime_intake
        return maritime_intake.set_package_count(self.db,self.guide,self.shipment_id,quantity,version,'operator',role)

    def summary(self):
        return reception.truck_guide_summary(self.db,self.guide,'operator','ADMINISTRADOR')

    def test_quantity_needs_no_code_or_dhl_and_does_not_receive_nps(self):
        with patch.object(dhl_tracking,'fetch_tracking') as fetch,patch.object(reception,'lots_for_shipment',return_value=[]):
            saved=self.save()
            self.assertEqual((saved['count'],saved['version']), (8,1))
            row=self.summary()['bls'][0]
            self.assertEqual((row['registered_package_count'],row['package_scan_count'],row['package_count_mode']), (8,0,'QUANTITY'))
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_package_scans').fetchone()[0],0)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)
            self.assertEqual(reception.reception_detail(self.db,self.shipment_id,'ADMINISTRADOR','operator')['package_progress']['received'],8)
            arrived=reception.finalize_scanned_truck_arrival(self.db,self.guide,'','operator','ASISTENTE_RECEPCION')
            self.assertEqual(arrived['bls'][0]['received_this_truck'],8)
            self.assertEqual(arrived['guide_status'],'ZONA_RECEPCION')
            self.assertEqual(reception.reception_detail(self.db,self.shipment_id,'ADMINISTRADOR','operator')['package_progress']['received'],8)
            self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines').fetchone()[0],0)
            fetch.assert_not_called()

    def test_identical_retry_is_idempotent_and_stale_different_save_is_rejected(self):
        self.save()
        before=list(self.db.iterdump())
        self.assertTrue(self.save()['duplicate'])
        self.assertEqual(list(self.db.iterdump()),before)
        with self.assertRaisesRegex(ValueError,'cambi'):
            self.save(9,0)
        self.assertEqual(list(self.db.iterdump()),before)
        self.assertEqual(self.save(9,1)['version'],2)
        self.assertEqual(self.summary()['bls'][0]['registered_package_count'],9)

    def test_invalid_values_roles_transport_and_closed_stage_cannot_write(self):
        for quantity in (None,'',-1,1.5,'NaN','inf',True,{},'1e500'):
            before=list(self.db.iterdump())
            with self.subTest(quantity=quantity),self.assertRaises((ValueError,TypeError)):
                self.save(quantity)
            self.assertEqual(list(self.db.iterdump()),before)
        for role in ('AUXILIAR_RECEPCION','PICKER',''):
            with self.assertRaises(PermissionError):self.save(role=role)
        self.db.execute("UPDATE reception_shipments SET transport_type='COURIER'")
        with self.assertRaises(ValueError):self.save()
        self.db.execute("UPDATE reception_shipments SET transport_type='MARITIMO',app_status='CERRADO'")
        with self.assertRaises(ValueError):self.save()

    def test_quantity_and_unique_scans_cannot_mix_in_either_direction(self):
        self.save()
        with self.assertRaisesRegex(ValueError,'cantidad'):
            reception.scan_truck_package(self.db,self.guide,self.shipment_id,'SEA-BOX','operator','ASISTENTE_RECEPCION')
        self.save(0,1)
        self.db.execute("UPDATE reception_truck_bl_manifest SET package_count_mode='SCAN'")
        reception.scan_truck_package(self.db,self.guide,self.shipment_id,'SEA-BOX','operator','ASISTENTE_RECEPCION')
        with self.assertRaisesRegex(ValueError,'lectur'):
            self.save(8,2)

    def test_zero_clears_pending_quantity_without_creating_a_receipt(self):
        self.save()
        self.save(0,1)
        self.assertEqual(self.summary()['bls'][0]['registered_package_count'],0)
        with self.assertRaises(ValueError):
            reception.finalize_scanned_truck_arrival(self.db,self.guide,'','operator','ASISTENTE_RECEPCION')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)

    def test_cancel_resets_manual_counter_and_preserves_audit(self):
        self.save()
        reception.cancel_scanned_truck_arrival(self.db,self.guide,'operator','ASISTENTE_RECEPCION')
        row=self.db.execute('SELECT planned_packages,package_count_version FROM reception_truck_bl_manifest').fetchone()
        self.assertEqual(tuple(row),(0,2))
        self.assertGreaterEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CONTEO BULTOS'").fetchone()[0],2)
        with self.assertRaises(ValueError):self.save()

    def test_admin_reversal_resets_counter_and_allows_corrected_arrival(self):
        self.save()
        reception.finalize_scanned_truck_arrival(self.db,self.guide,'','operator','ASISTENTE_RECEPCION')
        reception.revert_truck_guide(self.db,self.guide,'admin','ADMINISTRADOR','PENDIENTE','QA quantity correction')
        row=self.summary()['bls'][0]
        self.assertEqual(row['registered_package_count'],0)
        self.save(7,row['package_count_version'])
        result=reception.finalize_scanned_truck_arrival(self.db,self.guide,'','operator','ASISTENTE_RECEPCION')
        self.assertEqual(result['bls'][0]['received_this_truck'],7)
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments').fetchone()[0],7)

    def test_partial_second_arrival_has_independent_quantity_and_location(self):
        self.save(8)
        reception.finalize_scanned_truck_arrival(self.db,self.guide,'','operator','ASISTENTE_RECEPCION')
        reception.process_truck_guide_locations(self.db,self.guide,[{'shipment_id':self.shipment_id,'locations':[{'location':'TEMP-A','package_count':8}]}],'operator','ASISTENTE_RECEPCION')
        first=self.guide
        self.guide=reception.create_scanner_truck_guide(self.db,'operator','ASISTENTE_RECEPCION')['truck_guide']
        reception.add_scanned_truck_bl(self.db,self.guide,'BL-90001','operator','ASISTENTE_RECEPCION')
        self.save(3)
        second=reception.finalize_scanned_truck_arrival(self.db,self.guide,'','operator','ASISTENTE_RECEPCION')
        self.assertEqual(second['bls'][0]['received_this_truck'],3)
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments').fetchone()[0],11)
        first_summary=reception.truck_guide_summary(self.db,first,'operator','ADMINISTRADOR')
        self.assertEqual(first_summary['bls'][0]['locations'][0]['package_count'],8)

    def test_history_write_failure_rolls_back_counter_and_guide(self):
        before=list(self.db.iterdump())
        self.db.set_authorizer(lambda action,table,*args: sqlite3.SQLITE_DENY
            if action==sqlite3.SQLITE_INSERT and table=='reception_history' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):self.save()
        finally:
            self.db.set_authorizer(None)
        self.assertEqual(list(self.db.iterdump()),before)

    def test_finalization_cannot_forge_saved_manual_total_or_bypass_transport(self):
        self.save()
        before=list(self.db.iterdump())
        with self.assertRaises(ValueError):
            reception.process_truck_guide_arrivals(self.db,self.guide,[{'shipment_id':self.shipment_id,'received_packages':7}],
                'forged-arrival','','admin','ADMINISTRADOR')
        self.assertEqual(list(self.db.iterdump()),before)
        self.db.execute("UPDATE reception_shipments SET transport_type='COURIER'")
        before=list(self.db.iterdump())
        with self.assertRaises(ValueError):
            reception.finalize_scanned_truck_arrival(self.db,self.guide,'','admin','ADMINISTRADOR')
        self.assertEqual(list(self.db.iterdump()),before)

    def test_missing_manifest_invalid_id_and_schema_reentry_cannot_change_work(self):
        from backend.services import maritime_intake
        for sid in (None,True,1.5,-1,10**100,999):
            with self.subTest(sid=sid),self.assertRaises(ValueError):
                maritime_intake.set_package_count(self.db,self.guide,sid,8,0,'operator','ASISTENTE_RECEPCION')
        self.save()
        reception.init_reception_schema(self.db)
        self.assertEqual(self.summary()['bls'][0]['registered_package_count'],8)
