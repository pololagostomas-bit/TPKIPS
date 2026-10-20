"""Corrections target physical package reads, never NP count rows."""
import importlib.util
import unittest

from backend.services import reception
from tests import test_reception_independent_arrivals as fixtures


class PackageCorrectionTests(unittest.TestCase):
    setUp = fixtures.IndependentArrivalTests.setUp
    tearDown = fixtures.IndependentArrivalTests.tearDown

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.services.reception_package_corrections'),
                             'Missing package correction service')
        from backend.services import reception_package_corrections
        return reception_package_corrections

    def prepare(self, finalize=True):
        self.guide = reception.create_scanner_truck_guide(self.db, 'operator', 'ADMINISTRADOR')['truck_guide']
        reception.add_scanned_truck_bl(self.db, self.guide, 'QA-INDEPENDENT', 'operator', 'ADMINISTRADOR')
        for code in ('QA-PIECE-A', 'QA-PIECE-B'):
            reception.scan_truck_package(self.db, self.guide, self.sid, code, 'operator', 'ADMINISTRADOR')
        if finalize:
            reception.finalize_scanned_truck_arrival(self.db, self.guide, '', 'operator', 'ADMINISTRADOR')
        return self.review()

    def review(self, **values):
        return self.api().review_packages(self.db, self.sid, 'ADMINISTRADOR', truck_guide=self.guide, **values)

    def correct(self, review, **values):
        body = {'truck_guide': self.guide, 'scan_id': review['items'][0]['id'], 'action': 'remove',
                'token': review['token'], 'reason': 'Incorrect physical receipt verified in QA', 'confirmed': True}
        body.update(values)
        return self.api().correct_package(self.db, self.sid, body, 'admin.qa', 'ADMINISTRADOR')

    def test_remove_saved_piece_updates_only_its_receipt_and_preserves_evidence(self):
        before = self.prepare()
        old_id = before['items'][0]['id']
        result = self.correct(before)
        self.assertEqual(result['received_this_arrival'], 1)
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()[0], 1)
        row = self.db.execute('SELECT * FROM reception_truck_package_scans WHERE id=?', (old_id,)).fetchone()
        self.assertEqual(row['scan_status'], 'ANULADO')
        self.assertEqual(row['voided_by'], 'admin.qa')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_lines').fetchone()[0], 1)
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CORRECCION BULTO ADMIN'").fetchone()[0], 0)

    def test_replace_records_new_code_without_changing_physical_quantity(self):
        review = self.prepare()
        result = self.correct(review, action='replace', package_code='QA-PIECE-C')
        self.assertEqual(result['received_this_arrival'], 2)
        self.assertEqual({row['code'] for row in result['items']}, {'QA-PIECE-B', 'QA-PIECE-C'})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_package_scans').fetchone()[0], 3)

    def test_stale_correction_and_worker_access_are_denied_without_writes(self):
        review = self.prepare()
        self.correct(review)
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, 'cambio|recarga'):
            self.correct(review)
        with self.assertRaises(PermissionError):
            self.api().review_packages(self.db, self.sid, 'ASISTENTE_RECEPCION', truck_guide=self.guide)
        with self.assertRaises(PermissionError):
            self.api().correct_package(self.db, self.sid, {}, 'operator', 'ASISTENTE_RECEPCION')
        self.assertEqual(before, list(self.db.iterdump()))

    def test_removed_unconfirmed_piece_cannot_be_restored_by_old_scanner_retry(self):
        review = self.prepare(finalize=False)
        code = review['items'][0]['code']
        self.correct(review)
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, 'anulad|administrador'):
            reception.scan_truck_package(self.db, self.guide, self.sid, code, 'operator', 'ADMINISTRADOR')
        self.assertEqual(before, list(self.db.iterdump()))

    def test_scanned_or_counted_attention_requires_explicit_reopening(self):
        review = self.prepare()
        self.db.execute("UPDATE reception_attentions SET app_status='REVISION SISTEMA'")
        review = self.review()
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(PermissionError, 'reabre|Reabre'):
            self.correct(review)
        self.assertEqual(before, list(self.db.iterdump()))

    def test_last_removed_piece_annuls_only_that_attention(self):
        review = self.prepare()
        self.correct(review)
        self.correct(self.review())
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_receipts').fetchone()[0], 0)
        attention = self.db.execute('SELECT * FROM reception_attentions').fetchone()
        self.assertTrue(attention['condition_status'].startswith('ANULADA'))
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()[0], 0)
        detail = reception.reception_detail(self.db, self.sid)
        self.assertTrue(detail['awaiting_arrival'])
        self.assertIsNone(detail['physical_started_at'])

    def test_already_annulled_zero_arrival_does_not_block_truck_reversal(self):
        review = self.prepare()
        self.correct(review)
        self.correct(self.review())
        try:
            result = reception.revert_truck_guide(self.db, self.guide, 'admin.qa', 'ADMINISTRADOR',
                                                 reason='Reopen an already zeroed arrival QA')
        except PermissionError as error:
            self.fail('An annulled zero arrival cannot block truck reversal: ' + str(error))
        self.assertTrue(result['reverted'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_truck_package_scans WHERE scan_status='ANULADO'").fetchone()[0], 2)

    def test_orphan_receipt_regularizes_quantity_without_inventing_barcodes(self):
        detail = reception.add_physical_receipt(self.db, self.sid, {'received_packages': 2}, 'operator', 'ADMINISTRADOR')
        aid = detail['attention_id']
        module = self.api()
        review = module.review_packages(self.db, self.sid, 'ADMINISTRADOR', attention_id=aid)
        result = module.correct_package(self.db, self.sid,
            {'attention_id': aid, 'action': 'receipt_quantity', 'received_packages': 1,
             'token': review['token'], 'reason': 'Orphan receipt count corrected in QA', 'confirmed': True},
            'admin.qa', 'ADMINISTRADOR')
        self.assertEqual(result['received_this_arrival'], 1)
        self.assertEqual(result['items'], [])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_package_scans').fetchone()[0], 0)

    def test_invalid_input_keeps_database_unchanged(self):
        review = self.prepare()
        for values in ({'confirmed': False}, {'reason': ''}, {'scan_id': 9999},
                       {'action': 'replace', 'package_code': 'QA-PIECE-B'}):
            before = list(self.db.iterdump())
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.correct(review, **values)
            self.assertEqual(before, list(self.db.iterdump()))

    def test_quantity_change_preserves_earlier_orphan_receipt(self):
        first = reception.add_physical_receipt(self.db, self.sid,
            {'received_packages': 1, 'location': 'OLD-ZONE'}, 'operator', 'ADMINISTRADOR')
        receipt_id = first['receipts'][0]['id']
        review = self.prepare()
        self.correct(review)
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()[0], 2)
        old = self.db.execute('SELECT * FROM reception_receipts WHERE id=?', (receipt_id,)).fetchone()
        self.assertEqual(old['received_packages'], 1)
        self.assertEqual(old['location_text'], 'OLD-ZONE')

    def test_cleared_locations_remain_in_before_snapshot(self):
        self.prepare()
        reception.process_truck_guide_locations(self.db, self.guide,
            [{'shipment_id': self.sid, 'locations': [{'location': 'TEMP-QA', 'package_count': 2}]}],
            'operator', 'ADMINISTRADOR')
        self.correct(self.review())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_bl_locations').fetchone()[0], 0)
        history = self.db.execute("SELECT old_value FROM reception_history WHERE event_type='CORRECCION BULTO ADMIN'").fetchone()[0]
        self.assertIn('TEMP-QA', history)
        self.assertEqual(self.db.execute('SELECT guide_status FROM reception_truck_guides WHERE guide_code=?', (self.guide,)).fetchone()[0], 'ZONA_RECEPCION')

    def test_code_alias_cannot_bypass_administrative_void(self):
        review = self.prepare(finalize=False)
        review = self.correct(review, action='replace', package_code='JD0000123456')
        row = next(row for row in review['items'] if row['code']=='JD0000123456')
        self.correct(review, scan_id=row['id'])
        for code in ('JD0000123456', '*JJD0000123456*', '(J)JD0000123456'):
            before = list(self.db.iterdump())
            with self.assertRaisesRegex(ValueError, 'anulad|administrador'):
                reception.scan_truck_package(self.db, self.guide, self.sid, code, 'operator', 'ADMINISTRADOR')
            self.assertEqual(before, list(self.db.iterdump()))


if __name__ == '__main__':
    unittest.main()
