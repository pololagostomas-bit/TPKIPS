"""Exact label wrappers and physical receipt evidence on disposable SQLite."""
import unittest

from backend.services import dhl_tracking as dhl, reception
from tests import test_package_intake as fixtures


SSCC = '123456789012345675'
OTHER_SSCC = '123456789012345682'


class PieceFormatTests(unittest.TestCase):
    setUp = fixtures.PackageIntakeTests.setUp
    scan = fixtures.PackageIntakeTests.scan
    snapshot = fixtures.PackageIntakeTests.snapshot

    def add_sscc(self, code=SSCC, awb='1234567890'):
        self.db.execute('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)', (code, awb))

    def test_ai00_and_aim_carriers_preserve_the_full_18_digit_identity(self):
        for code in (SSCC, '(00) ' + SSCC, '00' + SSCC, ']C100' + SSCC,
                     ']d200' + SSCC, ']Q300' + SSCC):
            with self.subTest(code=code):
                self.assertEqual(dhl.piece_code(code), SSCC)
        leading_zero = '001234567890123456'
        self.assertEqual(dhl.piece_code(leading_zero), leading_zero)
        self.assertNotEqual(dhl.piece_code(SSCC), dhl.piece_code(OTHER_SSCC))

    def test_only_complete_recognized_wrappers_are_removed(self):
        for code in ('*JD000001*', '*JJD000001*', ' *(J)JD000001* '):
            self.assertEqual(dhl.piece_code(code), 'JD000001')
        for code in ('*BOX-A*', '*JD000001', 'JD000001*', 'JD*000001',
                     '(00)123', '001234', '(00)' + SSCC + '99', ']C1' + SSCC):
            self.assertEqual(dhl.piece_code(code), code.upper())

    def test_ai00_intake_is_one_piece_and_keeps_original_audit(self):
        self.add_sscc()
        raw = '(00) ' + SSCC
        try:
            first = self.scan(raw)
        except ValueError as error:
            self.fail('A complete cached AI00 label must resolve: ' + str(error))
        self.assertEqual((first['count'], first['bl_awb']), (1, '1234567890'))
        row = self.db.execute('SELECT package_code,normalized_code FROM reception_truck_package_scans').fetchone()
        self.assertEqual(tuple(row), (raw, SSCC))
        before = self.snapshot()
        for code in (SSCC, '00' + SSCC, ']C100' + SSCC):
            self.assertTrue(self.scan(code)['duplicate'])
            self.assertEqual(self.snapshot(), before)

    def test_star_jd_retry_keeps_one_physical_read(self):
        self.scan('JD000001')
        before = self.snapshot()
        try:
            result = self.scan('*JJD000001*')
        except ValueError as error:
            self.fail('SAP wrapper must retry the same exact piece: ' + str(error))
        self.assertTrue(result['duplicate'])
        self.assertEqual(result['count'], 1)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_ai00_scan_deduplicates_even_after_cache_expiry(self):
        self.add_sscc()
        self.scan(SSCC)
        self.db.execute('UPDATE reception_truck_package_scans SET normalized_code=?', ('00' + SSCC,))
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        before = self.snapshot()
        try:
            result = self.scan(SSCC)
        except ValueError as error:
            self.fail('A saved AI00 alias must remain idempotent: ' + str(error))
        self.assertTrue(result['duplicate'])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_wrapper_never_assigns_another_cached_piece(self):
        self.add_sscc()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.scan('(00)' + OTHER_SSCC)
        self.assertEqual(self.snapshot(), before)

    def test_every_supported_legacy_aim_parenthesized_alias_deduplicates(self):
        self.add_sscc()
        self.scan(SSCC)
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        for prefix in (']C1', ']D2', ']Q3'):
            with self.subTest(prefix=prefix):
                self.db.execute('UPDATE reception_truck_package_scans SET normalized_code=?',
                    (prefix + '(00)' + SSCC,))
                before = self.snapshot()
                try:
                    result = self.scan(SSCC)
                except ValueError as error:
                    self.fail('Supported saved AIM format must deduplicate: ' + str(error))
                self.assertTrue(result['duplicate'])
                self.assertEqual(self.snapshot(), before)

    def test_documentary_total_is_not_a_physical_receipt(self):
        self.db.execute('UPDATE dhl_tracking_cache SET total_pieces=3')
        self.db.execute("INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES ('JD000004','1234567890')")
        self.scan('JD000001')
        for role in ('ADMINISTRADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION'):
            status = dhl.shipment_status(self.db, self.ids['1234567890'], role=role)
            self.assertEqual(status.get('received_pieces'), 1)
            self.assertEqual(status.get('pending_arrival_pieces'), 2)
            self.assertEqual(status['total_pieces'], 3)
            if role == 'ADMINISTRADOR':
                self.assertEqual(status.get('received_piece_ids'), ['JD000001'])
            else:
                self.assertNotIn('received_piece_ids', status)
                self.assertNotIn('pending_piece_ids', status)
        summary = reception.truck_guide_summary(self.db, self.guide, 'qa', 'ADMINISTRADOR')
        self.assertEqual(summary['bls'][0]['package_scan_count'], 1)

    def test_voided_piece_is_never_listed_as_received(self):
        self.scan('JD000001')
        self.db.execute("UPDATE reception_truck_package_scans SET scan_status='ANULADO'")
        status = dhl.shipment_status(self.db, self.ids['1234567890'], role='ADMINISTRADOR')
        self.assertEqual(status.get('received_pieces'), 0)
        self.assertEqual(status.get('received_piece_ids'), [])

    def test_expired_or_disabled_tracking_does_not_erase_physical_evidence(self):
        from unittest.mock import patch
        self.scan('JD000001')
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        for enabled in ('1', '0'):
            with patch.dict('os.environ', {'WMS_DHL_ENABLED': enabled}):
                status = dhl.shipment_status(self.db, self.ids['1234567890'], role='ADMINISTRADOR')
            self.assertEqual(status['received_pieces'], 1)
            self.assertEqual(status['received_piece_ids'], ['JD000001'])
            self.assertIsNone(status['total_pieces'])
            self.assertIsNone(status['pending_arrival_pieces'])

    def test_complete_format_cannot_move_a_piece_to_a_different_bl(self):
        self.add_sscc()
        reception.add_scanned_truck_bl(self.db, self.guide, '1234567891', 'qa', 'ADMINISTRADOR')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            reception.scan_truck_package(self.db, self.guide, self.ids['1234567891'],
                '(00)' + SSCC, 'qa', 'ASISTENTE_RECEPCION')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
