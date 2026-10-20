import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from backend.services import dhl_tracking as dhl, package_intake as intake, reception


class PackageIntakeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        reception.init_reception_schema(self.db)
        dhl.init_schema(self.db)
        self.env = patch.dict(os.environ, {'WMS_DHL_ENABLED':'1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.db.close)
        self.ids = {}
        for awb in ('1234567890','1234567891'):
            self.ids[awb] = self.db.execute('''INSERT INTO reception_shipments
                (bl_awb,transport_type,scheduled_date,created_at,updated_at)
                VALUES (?,'COURIER','2026-10-13','2026-10-13','2026-10-13')''', (awb,)).lastrowid
            self.db.execute('INSERT INTO dhl_tracking_cache(awb,status_code,total_pieces,checked_at,expires_at) VALUES (?,\'transit\',2,?,?)',
                            (awb,time.time(),time.time()+86400))
        for code,awb in (('JD000001','1234567890'),('JD000002','1234567890'),('JD000003','1234567891')):
            self.db.execute('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)',(code,awb))
        self.guide = reception.create_scanner_truck_guide(self.db,'qa','ADMINISTRADOR')['truck_guide']
        self.network = patch.object(dhl,'fetch_tracking')
        self.http = self.network.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.http.assert_not_called)

    def scan(self, code, guide=None, role='ADMINISTRADOR', **kwargs):
        return intake.scan_piece(self.db, guide or self.guide, code, 'qa', role, **kwargs)

    def snapshot(self):
        return list(self.db.iterdump())

    def test_first_piece_attaches_existing_bl_without_receiving_it_yet(self):
        result = self.scan(' jd000001 ')
        self.assertEqual(result['shipment_id'],self.ids['1234567890'])
        self.assertEqual(result['identification'],'dhl')
        self.assertTrue(result['bl_added'])
        self.assertEqual(result['count'],1)
        row = self.db.execute('SELECT received_packages,first_arrival_at,app_status FROM reception_shipments WHERE id=?',
                              (result['shipment_id'],)).fetchone()
        self.assertEqual(tuple(row),(0,None,'PROGRAMADO'))

    def test_package_first_later_arrival_does_not_wait_for_previous_zone(self):
        self.db.execute('CREATE TABLE order_importation_refs (bl_awb TEXT,sap_ov TEXT,transport_type TEXT)')
        self.db.execute("UPDATE reception_shipments SET current_assistant='qa',current_auxiliary='qa'")
        self.scan('JD000001')
        reception.finalize_scanned_truck_arrival(self.db, self.guide, '', 'qa', 'ADMINISTRADOR')
        other = reception.create_scanner_truck_guide(self.db, 'qa', 'ADMINISTRADOR')['truck_guide']
        try:
            result = self.scan('JD000002', guide=other)
        except intake.IdentificationError as error:
            self.fail('Saved first arrival must not block package-first receipt: ' + str(error))
        self.assertTrue(result['accepted'])
        self.assertEqual(result['shipment_id'], self.ids['1234567890'])

    def test_mixed_bl_packages_resolve_independently(self):
        results = [self.scan(code) for code in ('JD000001','JD000003','JD000002')]
        self.assertEqual([r['bl_awb'] for r in results],['1234567890','1234567891','1234567890'])
        self.assertEqual([r['count'] for r in results],[1,1,2])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_shipments').fetchone()[0],2)

    def test_dhl_label_variants_are_one_piece_and_preserve_original_reading(self):
        first = self.scan('jjd000001')
        self.assertEqual(first['identification'], 'dhl')
        row = self.db.execute('SELECT package_code,normalized_code FROM reception_truck_package_scans').fetchone()
        self.assertEqual(tuple(row), ('jjd000001', 'JD000001'))
        self.assertEqual(self.db.execute("SELECT new_value FROM reception_history WHERE event_type='ESCANEO BULTO'").fetchone()[0],
                         'jjd000001')
        before = self.snapshot()
        for code in ('JD000001', 'JJD000001', '(J)JD000001'):
            with self.subTest(code=code):
                result = self.scan(code)
                self.assertTrue(result['duplicate'])
                self.assertEqual(result['count'], 1)
                self.assertEqual(self.snapshot(), before)

    def test_legacy_prefixed_cache_recognizes_unprefixed_scan(self):
        self.db.execute("UPDATE dhl_tracking_pieces SET piece_id='JJD000001' WHERE piece_id='JD000001'")
        result = self.scan('JD000001')
        self.assertEqual(result['bl_awb'], '1234567890')
        self.assertEqual(result['dhl_verification'], 'verified')

    def test_legacy_prefixed_physical_scan_deduplicates_after_cache_expiry(self):
        self.scan('JJD000001')
        self.db.execute("UPDATE reception_truck_package_scans SET normalized_code='JJD000001'")
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        before = self.snapshot()
        for code in ('JD000001', '(J)JD000001'):
            result = self.scan(code)
            self.assertTrue(result['duplicate'])
            self.assertEqual(result['count'], 1)
            self.assertEqual(self.snapshot(), before)

    def test_legacy_double_scans_need_review_without_changing_counts(self):
        self.scan('JD000001')
        self.db.execute('''INSERT INTO reception_truck_package_scans
            (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
            VALUES (?,?,'JJD000001','JJD000001','qa','2026-10-13')''', (self.guide,self.ids['1234567890']))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'lecturas previas duplicadas'):
            self.scan('JJD000001')
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_cached_aliases_cannot_be_overridden_by_manual_bl(self):
        self.db.execute("INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES ('JJD000001','1234567891')")
        before = self.snapshot()
        for code in ('JD000001', 'JJD000001', '(J)JD000001'):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, 'mas de una guia'):
                self.scan(code, bl_code='1234567890', confirm_unverified=True)
            self.assertEqual(self.snapshot(), before)

    def test_alias_cannot_move_a_piece_to_another_truck_or_bl(self):
        self.scan('JD000001')
        other = reception.create_scanner_truck_guide(self.db,'qa','ADMINISTRADOR')['truck_guide']
        before = self.snapshot()
        with self.assertRaises(intake.IdentificationError) as error:
            self.scan('JJD000001', guide=other)
        self.assertEqual(error.exception.code, 'other_truck')
        with self.assertRaisesRegex(intake.IdentificationError, '1234567890'):
            self.scan('(J)JD000001', bl_code='1234567891', confirm_unverified=True)
        self.assertEqual(self.snapshot(), before)

    def test_similar_codes_and_missing_zero_do_not_match_cached_piece(self):
        before = self.snapshot()
        for code in ('JJD00001', 'JJJD000001', 'JJD000001X', 'JVGL000001'):
            with self.subTest(code=code), self.assertRaises(intake.IdentificationError) as error:
                self.scan(code)
            self.assertEqual(error.exception.code, 'unknown_piece')
            self.assertEqual(self.snapshot(), before)

    def test_unknown_alias_cannot_be_accepted_by_confirming_a_dhl_bl(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'no verificado'):
            self.scan('JJD000009', bl_code='1234567890', confirm_unverified=True)
        self.assertEqual(self.snapshot(), before)

    def test_direct_bl_scan_uses_same_alias_rules(self):
        sid = self.ids['1234567890']
        reception.add_scanned_truck_bl(self.db,self.guide,'1234567890','qa','ADMINISTRADOR')
        result = reception.scan_truck_package(self.db,self.guide,sid,'(J)JD000001','qa','ADMINISTRADOR')
        self.assertEqual(result['dhl_verification'], 'verified')
        before = self.snapshot()
        self.assertTrue(reception.scan_truck_package(self.db,self.guide,sid,'JJD000001','qa','ADMINISTRADOR')['duplicate'])
        self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(ValueError, '1234567891'):
            reception.scan_truck_package(self.db,self.guide,sid,'JJD000003','qa','ADMINISTRADOR')
        self.assertEqual(self.snapshot(), before)

    def test_cancelled_alias_does_not_block_new_physical_scan(self):
        self.scan('JJD000001')
        reception.cancel_scanned_truck_arrival(self.db,self.guide,'qa','ADMINISTRADOR')
        other = reception.create_scanner_truck_guide(self.db,'qa','ADMINISTRADOR')['truck_guide']
        self.assertTrue(self.scan('JD000001', guide=other)['accepted'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_truck_package_scans WHERE scan_status='ACTIVO'").fetchone()[0],1)

    def test_dhl_progress_is_read_only_and_counts_known_pieces_across_trucks(self):
        sid = self.ids['1234567890']
        self.scan('JJD000001')
        before = self.snapshot()
        status = dhl.shipment_status(self.db, sid, role='ADMINISTRADOR')
        self.assertEqual((status['matched_pieces'], status['pending_pieces']), (1, 1))
        self.assertEqual(status['pending_piece_ids'], ['JD000002'])
        self.assertTrue(status['piece_list_complete'])
        self.assertEqual(self.snapshot(), before)
        self.db.execute("UPDATE reception_truck_guides SET guide_status='LISTA_PARA_CONTEO' WHERE guide_code=?", (self.guide,))
        other = reception.create_scanner_truck_guide(self.db,'qa','ADMINISTRADOR')['truck_guide']
        self.scan('JJD000002', guide=other)
        status = dhl.shipment_status(self.db, sid, role='ADMINISTRADOR')
        self.assertEqual((status['matched_pieces'], status['pending_pieces']), (2, 0))
        reception.cancel_scanned_truck_arrival(self.db,other,'qa','ADMINISTRADOR')
        self.assertEqual(dhl.shipment_status(self.db, sid)['pending_pieces'], 1)

    def test_dhl_progress_never_invents_missing_piece_ids_for_incomplete_or_expired_cache(self):
        sid = self.ids['1234567890']
        self.db.execute("DELETE FROM dhl_tracking_pieces WHERE piece_id='JD000002'")
        status = dhl.shipment_status(self.db, sid, role='ADMINISTRADOR')
        self.assertFalse(status['piece_list_complete'])
        self.assertEqual(status['pending_piece_ids'], ['JD000001'])
        self.assertEqual(status['pending_pieces'], 1)
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        self.assertNotIn('pending_pieces', dhl.shipment_status(self.db, sid))
        with patch.dict(os.environ, {'WMS_DHL_ENABLED':'0'}):
            self.assertNotIn('pending_pieces', dhl.shipment_status(self.db, sid))

    def test_retry_is_read_only_even_if_dhl_cache_expired(self):
        self.scan('JD000001')
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        before=self.snapshot()
        result=self.scan('JD000001')
        self.assertTrue(result['duplicate'])
        self.assertEqual(result['count'],1)
        self.assertEqual(self.snapshot(),before)

    def test_unknown_is_not_assigned_to_last_bl(self):
        self.scan('JD000001')
        before=self.snapshot()
        with self.assertRaises(intake.IdentificationError) as error:
            self.scan('UNKNOWN-BOX')
        self.assertTrue(error.exception.can_identify)
        self.assertEqual(error.exception.code,'unknown_piece')
        self.assertEqual(self.snapshot(),before)

    def test_unknown_needs_explicit_confirmation_and_valid_existing_bl(self):
        with self.assertRaises(intake.IdentificationError):
            self.scan('UNKNOWN-BOX',bl_code='1234567891')
        before=self.snapshot()
        with self.assertRaises(intake.IdentificationError) as error:
            self.scan('UNKNOWN-BOX',bl_code='NO-BL',confirm_unverified=True)
        self.assertTrue(error.exception.can_identify)
        self.assertEqual(self.snapshot(),before)
        with self.assertRaisesRegex(ValueError, 'no verificado'):
            self.scan('UNKNOWN-BOX',bl_code='1234567891',confirm_unverified=True)
        self.assertEqual(self.snapshot(),before)

    def test_manual_cannot_override_known_piece(self):
        before=self.snapshot()
        with self.assertRaisesRegex(intake.IdentificationError,'1234567890'):
            self.scan('JD000001',bl_code='1234567891',confirm_unverified=True)
        self.assertEqual(self.snapshot(),before)

    def test_awb_cannot_count_as_one_unique_box(self):
        for code in ('1234567890','123-4567890'):
            with self.assertRaises(intake.IdentificationError) as error:
                self.scan(code,bl_code='1234567891',confirm_unverified=True)
            self.assertEqual(error.exception.code,'awb_not_piece')

    def test_closed_or_ambiguous_bl_does_not_write(self):
        self.db.execute("UPDATE reception_shipments SET app_status='CERRADO' WHERE id=?",(self.ids['1234567890'],))
        before=self.snapshot()
        with self.assertRaises(intake.IdentificationError) as error:
            self.scan('JD000001')
        self.assertEqual(error.exception.code,'closed_bl')
        self.assertEqual(self.snapshot(),before)
        self.db.execute("UPDATE reception_shipments SET app_status='PROGRAMADO'")
        self.db.execute("INSERT INTO reception_shipments(bl_awb,created_at,updated_at) VALUES ('123-4567890','2026-10-13','2026-10-13')")
        with self.assertRaises(intake.IdentificationError) as error:
            self.scan('JD000001')
        self.assertEqual(error.exception.code,'ambiguous_bl')

    def test_other_active_truck_or_reused_piece_cannot_be_moved(self):
        other=reception.create_scanner_truck_guide(self.db,'qa','ADMINISTRADOR')['truck_guide']
        self.scan('JD000001')
        before=self.snapshot()
        for code in ('JD000001','JD000002'):
            with self.assertRaises(intake.IdentificationError) as error:
                self.scan(code,guide=other)
            self.assertEqual(error.exception.code,'other_truck')
            self.assertEqual(self.snapshot(),before)

    def test_finished_truck_allows_another_partial_arrival_with_new_piece(self):
        self.scan('JD000001')
        self.db.execute("UPDATE reception_truck_guides SET guide_status='LISTA_PARA_CONTEO' WHERE guide_code=?",(self.guide,))
        other=reception.create_scanner_truck_guide(self.db,'qa','ADMINISTRADOR')['truck_guide']
        self.assertEqual(self.scan('JD000002',guide=other)['count'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_package_scans').fetchone()[0],2)

    def test_auxiliary_can_scan_known_piece_but_cannot_guess_unknown(self):
        self.assertEqual(self.scan('JD000001',role='AUXILIAR_RECEPCION')['count'],1)
        with self.assertRaises(PermissionError):
            self.scan('UNKNOWN',role='AUXILIAR_RECEPCION',bl_code='1234567891',confirm_unverified=True)
        with self.assertRaises(PermissionError):
            self.scan('JD000003',role='PICKER')

    def test_failed_save_rolls_back_bl_association(self):
        before=self.snapshot()
        with patch.object(reception,'scan_truck_package',side_effect=ValueError('forced failure')):
            with self.assertRaises(ValueError):self.scan('JD000001')
        self.assertEqual(self.snapshot(),before)

    def test_cancel_preserves_bl_and_voids_only_scans(self):
        self.scan('JD000001')
        reception.cancel_scanned_truck_arrival(self.db,self.guide,'qa','ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_shipments').fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_truck_package_scans WHERE scan_status='ACTIVO'").fetchone()[0],0)
        self.assertIsNone(self.db.execute('SELECT truck_guide FROM reception_shipments WHERE id=?',(self.ids['1234567890'],)).fetchone()[0])

    def test_simultaneous_same_piece_creates_one_physical_record(self):
        self.assert_simultaneous_piece_codes(('JD000001', 'JD000001'))

    def test_simultaneous_aliases_create_one_physical_record(self):
        self.assert_simultaneous_piece_codes(('JD000001', 'JJD000001'))

    def assert_simultaneous_piece_codes(self, codes):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'concurrent.sqlite'
            self.db.commit()
            destination=sqlite3.connect(path)
            try:self.db.backup(destination)
            finally:destination.close()
            barrier=Barrier(2)
            def save(code):
                connection=sqlite3.connect(path,timeout=10)
                connection.row_factory=sqlite3.Row
                try:
                    barrier.wait(timeout=5)
                    connection.execute('BEGIN IMMEDIATE')
                    result=intake.scan_piece(connection,self.guide,code,'qa','ADMINISTRADOR')
                    connection.commit()
                    return result
                finally:connection.close()
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,codes))
            self.assertEqual(sum(r['accepted'] for r in results),1)
            self.assertEqual(sum(r['duplicate'] for r in results),1)
            self.assertEqual([r['count'] for r in results],[1,1])

    def test_api_csrf_roles_json_and_ignores_supplied_shipment_id(self):
        from backend import app,wsgi
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'qa.sqlite'
            self.db.commit()
            destination=sqlite3.connect(path)
            try:self.db.backup(destination)
            finally:destination.close()
            def call(headers,role='ADMINISTRADOR',code='JD000001'):
                body=json.dumps({'truck_guide':self.guide,'package_code':code,'shipment_id':self.ids['1234567891']}).encode()
                env={'PATH_INFO':'/api/receptions/truck-guide/scan-piece','REQUEST_METHOD':'POST',
                     'wsgi.input':io.BytesIO(body),'CONTENT_LENGTH':str(len(body)),
                     'HTTP_X_ROLE':role,'HTTP_X_USER':'qa',**headers}
                saved={}
                response=b''.join(wsgi.application(env,lambda status,values:saved.update(status=status)))
                return saved['status'][:3],json.loads(response)
            with patch.object(app,'DB_PATH',path),patch.dict(os.environ,{'TRITON_AUTH_MODE':'demo'}):
                self.assertEqual(call({})[0],'403')
                self.assertEqual(call({'HTTP_X_WMS_REQUEST':'1','HTTP_SEC_FETCH_SITE':'cross-site'})[0],'403')
                self.assertEqual(call({'HTTP_X_WMS_REQUEST':'1'},role='PICKER')[0],'403')
                status,data=call({'HTTP_X_WMS_REQUEST':'1'},code='JJD000001')
                self.assertEqual(status,'200')
                self.assertEqual(data['shipment_id'],self.ids['1234567890'])
                status,data=call({'HTTP_X_WMS_REQUEST':'1'},code='JD000001')
                self.assertEqual(status,'200')
                self.assertTrue(data['duplicate'])
                self.assertEqual(data['count'],1)
                status,data=call({'HTTP_X_WMS_REQUEST':'1'},code='UNKNOWN')
                self.assertEqual(status,'409')
                self.assertTrue(data['can_identify'])
