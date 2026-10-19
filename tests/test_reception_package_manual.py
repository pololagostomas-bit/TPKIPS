"""Synthetic single-piece manual intake; production data and DHL are never used."""
import os
import sqlite3
import time
import unittest
from unittest.mock import patch

from backend.services import dhl_tracking as dhl, reception, reception_package_manual as manual


class ManualPackageTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        reception.init_reception_schema(self.db)
        dhl.init_schema(self.db)
        self.addCleanup(self.db.close)
        env = patch.dict(os.environ, {'WMS_DHL_ENABLED': '1'})
        env.start()
        self.addCleanup(env.stop)
        network = patch.object(dhl, 'fetch_tracking', side_effect=AssertionError('No external calls'))
        network.start()
        self.addCleanup(network.stop)
        self.ids = []
        for index, (awb, transport) in enumerate([
                ('1234567890', 'COURIER'), ('1234567891', 'COURIER'), ('QA-SEA-0001', 'MARITIMO')]):
            sid = self.db.execute('''INSERT INTO reception_shipments
                (bl_awb,transport_type,created_at,updated_at)
                VALUES (?,?,'2026-10-16','2026-10-16')''', (awb, transport)).lastrowid
            self.ids.append(sid)
            if index < 2:
                self.db.execute('''INSERT INTO dhl_tracking_cache
                    (awb,status_code,total_pieces,checked_at,expires_at) VALUES (?,'transit',60,?,?)''',
                    (awb, time.time(), time.time() + 86400))
        self.db.executemany('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)',
                            [('JD' + str(i).zfill(6), '1234567890') for i in range(1, 61)])
        self.db.execute("INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES ('JD999999','1234567891')")
        self.guide = reception.create_scanner_truck_guide(self.db, 'qa', 'ADMINISTRADOR')['truck_guide']
        for bl in ('1234567890', 'QA-SEA-0001'):
            reception.add_scanned_truck_bl(self.db, self.guide, bl, 'qa', 'ADMINISTRADOR')

    def snapshot(self):
        return list(self.db.iterdump())

    def listing(self, sid=None, **kwargs):
        return manual.cached_pieces(self.db, self.guide, sid or self.ids[0], 'ADMINISTRADOR', **kwargs)

    def save(self, code='JJD000001', sid=None, **kwargs):
        options = dict(source='cache', reason='Etiqueta borrosa; identidad verificada con documento de prueba', confirmed=True)
        options.update(kwargs)
        role = options.pop('role', 'ADMINISTRADOR')
        return manual.register_piece(self.db, self.guide, sid or self.ids[0], code,
                                     'qa.admin', role, **options)

    def test_listing_is_read_only_paged_and_normalizes_query(self):
        before = self.snapshot()
        first = self.listing()
        self.assertEqual((len(first['items']), first['total'], first['pages']), (50, 60, 2))
        self.assertTrue(first['list_complete'])
        self.assertEqual(len(self.listing(page=2)['items']), 10)
        self.assertEqual(self.listing(query=' (J)JD000001 ')['items'][0]['code'], 'JD000001')
        self.assertEqual(self.listing(query='no-match')['total'], 0)
        self.assertEqual(self.snapshot(), before)

    def test_single_piece_audited_once_and_alias_retries_are_idempotent(self):
        result = self.save()
        self.assertEqual((result['count'], result['dhl_verification']), (1, 'verified'))
        before = self.snapshot()
        for code in ['JD000001', '(J)JD000001', 'JJD000001']:
            self.assertTrue(self.save(code)['duplicate'])
        self.assertEqual(before, self.snapshot())
        audit = self.db.execute("SELECT username, reason FROM reception_history WHERE event_type='REGISTRO MANUAL BULTO'").fetchall()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]['username'], 'qa.admin')
        self.assertIn('Etiqueta borrosa', audit[0]['reason'])
        item = self.listing()['items'][0]
        self.assertEqual((item['state'], item['can_select'], item['detail']), ('received', False, 'Este camion'))
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_shipments WHERE id=?', (self.ids[0],)).fetchone()[0], 0)

    def test_no_identity_confirmation_evidence_or_valid_source_never_writes(self):
        for code, options in [('', {}), ('1234567890', {}), ('JD000001', {'confirmed':False}),
                              ('JD000001', {'confirmed':'true'}), ('JD000001', {'reason':'corta'}),
                              ('JD000001', {'source':'lost-label'}), ('JD000001', {'source':'batch'})]:
            with self.subTest(code=code, options=options):
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.save(code, **options)
                self.assertEqual(before, self.snapshot())

    def test_workers_cannot_list_or_select_expected_codes_even_by_direct_call(self):
        for role in ['ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION']:
            before = self.snapshot()
            with self.assertRaises(PermissionError):
                manual.cached_pieces(self.db, self.guide, self.ids[0], role)
            with self.assertRaises(PermissionError):
                self.save(role=role)
            self.assertEqual(before, self.snapshot())
            self.assertTrue(self.save(source='known_code', role=role)['count'])

    def test_unknown_dhl_code_cannot_be_regularized_by_typing_or_admin_selection(self):
        for role in ['ADMINISTRADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION']:
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'no verificado'):
                self.save('JD777777', source='known_code', role=role)
            self.assertEqual(before, self.snapshot())

    def test_known_maritime_code_needs_no_dhl_and_no_scanner_hardware(self):
        result = self.save('QA-SEA-BOX-01', sid=self.ids[2], source='known_code')
        self.assertEqual((result['count'], result['dhl_verification']), (1, 'not_applicable'))
        self.assertFalse(self.listing(sid=self.ids[2])['applicable'])
        self.assertTrue(self.save('QA-SEA-BOX-01', sid=self.ids[2], source='known_code')['duplicate'])

    def test_expired_cache_blocks_new_selection_but_preserves_durable_retry(self):
        self.save()
        self.db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
        before = self.snapshot()
        self.assertEqual(self.listing()['items'], [])
        with self.assertRaisesRegex(ValueError, 'vigente'):
            self.save('JD000002')
        self.assertTrue(self.save()['duplicate'])
        self.assertEqual(before, self.snapshot())

    def test_wrong_bl_truck_and_roles_are_rejected(self):
        for code, sid, source in [('JD999999', self.ids[0], 'cache'),
                                  ('JD999999', self.ids[2], 'known_code')]:
            before = self.snapshot()
            with self.assertRaises(ValueError):
                self.save(code, sid=sid, source=source)
            self.assertEqual(before, self.snapshot())
        other = reception.create_scanner_truck_guide(self.db, 'qa', 'ADMINISTRADOR')['truck_guide']
        with self.assertRaises(ValueError):
            manual.cached_pieces(self.db, other, self.ids[0], 'ADMINISTRADOR')
        for role in ['ALMACENERO', 'CONSULTA', 'TRANSPORTISTA']:
            with self.assertRaises(PermissionError):
                manual.cached_pieces(self.db, self.guide, self.ids[0], role)
            with self.assertRaises(PermissionError):
                manual.register_piece(self.db, self.guide, self.ids[0], 'JD000001', 'qa', role,
                                      source='cache', reason='Evidencia sintetica', confirmed=True)

    def test_ambiguous_cache_and_legacy_duplicate_scans_block_selection(self):
        self.db.execute("INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES ('JJD000001','1234567891')")
        self.assertEqual(self.listing()['items'][0]['state'], 'blocked')
        with self.assertRaises(ValueError):
            self.save()
        self.db.execute("DELETE FROM dhl_tracking_pieces WHERE piece_id='JJD000001'")
        self.save()
        self.db.execute('''INSERT INTO reception_truck_package_scans
            (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
            VALUES (?,?,'JJD000001','JJD000001','qa','2026-10-16')''', (self.guide, self.ids[0]))
        self.assertEqual(self.listing()['items'][0]['state'], 'blocked')
        with self.assertRaises(ValueError):
            self.save()

    def test_audit_failure_rolls_back_single_piece_and_counts(self):
        original = reception._write_history
        def fail_manual(*args, **kwargs):
            if args[2] == 'REGISTRO MANUAL BULTO':
                raise RuntimeError('QA audit failure')
            return original(*args, **kwargs)
        before = self.snapshot()
        with patch.object(reception, '_write_history', side_effect=fail_manual):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
