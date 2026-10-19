"""Role privacy and intake bypass checks against disposable WSGI/SQLite only."""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import app, wsgi
from backend.services import dhl_tracking as dhl, reception


class PackageAccessTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        for setting in [patch.object(app, 'DB_PATH', Path(scratch.name) / 'qa.sqlite'),
                        patch.dict(os.environ, {'TRITON_AUTH_MODE': 'demo', 'WMS_DHL_ENABLED': '1'})]:
            setting.start()
            self.addCleanup(setting.stop)
        network = patch.object(dhl, 'fetch_tracking', side_effect=AssertionError('No DHL network'))
        network.start()
        self.addCleanup(network.stop)
        app.init_db()
        with app.db() as db:
            self.sid = db.execute('''INSERT INTO reception_shipments
                (bl_awb,transport_type,created_at,updated_at)
                VALUES ('1234567890','COURIER','2026-10-18','2026-10-18')''').lastrowid
            db.execute('''INSERT INTO reception_shipments
                (bl_awb,transport_type,created_at,updated_at)
                VALUES ('1234567891','COURIER','2026-10-18','2026-10-18')''')
            for awb in ['1234567890', '1234567891']:
                db.execute('''INSERT INTO dhl_tracking_cache
                    (awb,status_code,total_pieces,checked_at,expires_at) VALUES (?,'transit',3,?,?)''',
                    (awb, time.time(), time.time() + 86400))
            db.executemany('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)',
                [('JD000001', '1234567890'), ('JD000002', '1234567890'),
                 ('JD000003', '1234567890'), ('JD999999', '1234567891')])
            self.guide = reception.create_scanner_truck_guide(db, 'qa', 'ADMINISTRADOR')['truck_guide']
            reception.add_scanned_truck_bl(db, self.guide, '1234567890', 'qa', 'ADMINISTRADOR')

    def request(self, path, method='GET', role='ASISTENTE_RECEPCION', data=None):
        raw_path, _, query = path.partition('?')
        body = json.dumps(data or {}).encode()
        env = {'PATH_INFO': raw_path, 'QUERY_STRING': query, 'REQUEST_METHOD': method,
               'wsgi.input': io.BytesIO(body), 'CONTENT_LENGTH': str(len(body)),
               'HTTP_X_ROLE': role, 'HTTP_X_USER': 'qa', 'HTTP_X_WMS_REQUEST': '1'}
        captured = {}
        raw = b''.join(wsgi.application(env, lambda status, headers: captured.update(status=status)))
        return int(captured['status'][:3]), json.loads(raw)

    def snapshot(self):
        with app.db() as db:
            return list(db.iterdump())

    def package(self, code, **overrides):
        return dict(truck_guide=self.guide, shipment_id=self.sid, package_code=code, **overrides)

    def test_get_and_post_status_never_send_expected_codes_to_non_admins(self):
        for role in ['ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION']:
            for method in ['GET', 'POST']:
                status, data = self.request('/api/dhl-tracking/shipment?shipment_id=' + str(self.sid)
                    + '&role=ADMINISTRADOR', method, role, {'shipment_id': self.sid, 'role': 'ADMINISTRADOR'})
                self.assertEqual(status, 200)
                self.assertEqual((data['total_pieces'], data['pending_pieces']), (3, 3))
                self.assertFalse(data['can_view_piece_codes'])
                self.assertNotIn('pending_piece_ids', data)
                self.assertNotIn('JD000001', json.dumps(data))
        for method in ['GET', 'POST']:
            status, data = self.request('/api/dhl-tracking/shipment?shipment_id=' + str(self.sid),
                method, 'ADMINISTRADOR', {'shipment_id': self.sid})
            self.assertEqual(status, 200)
            self.assertTrue(data['can_view_piece_codes'])
            self.assertEqual(data['pending_piece_ids'], ['JD000001', 'JD000002', 'JD000003'])
        with app.db() as db:
            self.assertNotIn('pending_piece_ids', dhl.shipment_status(db, self.sid))

    def test_worker_cannot_fetch_or_select_expected_code_even_with_forged_body(self):
        for role in ['ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION']:
            before = self.snapshot()
            status, data = self.request('/api/receptions/truck-guide/manual-pieces?truck_guide='
                + self.guide + '&shipment_id=' + str(self.sid) + '&role=ADMINISTRADOR', role=role)
            self.assertEqual(status, 403)
            self.assertNotIn('JD000001', json.dumps(data))
            status, _ = self.request('/api/receptions/truck-guide/manual-package', 'POST', role,
                self.package('JD000001', source='cache', reason='QA physical evidence', confirmed=True,
                             role='ADMINISTRADOR'))
            self.assertEqual(status, 403)
            self.assertEqual(before, self.snapshot())

    def test_unknown_wrong_bl_and_confirmation_bypass_never_increment_counts(self):
        for role in ['ADMINISTRADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION']:
            for code in ['WRONG-CODE', 'JD00001', 'JD999999', '1234567890']:
                before = self.snapshot()
                for route, extra in [('scan-package', {}),
                    ('manual-package', {'source': 'known_code', 'reason': 'QA physical evidence', 'confirmed': True})]:
                    status, _ = self.request('/api/receptions/truck-guide/' + route, 'POST', role,
                                             self.package(code, **extra))
                    self.assertEqual(status, 400)
                    self.assertEqual(before, self.snapshot())
            before = self.snapshot()
            status, _ = self.request('/api/receptions/truck-guide/scan-piece', 'POST', role,
                self.package('WRONG-CODE', bl_code='1234567890', confirm_unverified=True))
            self.assertIn(status, [400, 403])
            self.assertEqual(before, self.snapshot())
            status, data = self.request('/api/receptions/truck-guide/scan-piece', 'POST', role,
                                       self.package('WRONG-CODE'))
            self.assertEqual(status, 409)
            self.assertEqual(data['can_identify'], role == 'ADMINISTRADOR')

    def test_worker_known_code_and_aliases_are_exact_and_idempotent(self):
        for index, role in enumerate(['ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION'], 1):
            code = 'JD00000' + str(index)
            data = self.package(code, source='known_code', reason='Codigo leido de copia fisica', confirmed=True)
            status, result = self.request('/api/receptions/truck-guide/manual-package', 'POST', role, data)
            self.assertEqual((status, result['count'], result['dhl_verification']), (200, index, 'verified'))
            status, result = self.request('/api/receptions/truck-guide/scan-package', 'POST', role,
                                         self.package('J' + code))
            self.assertEqual((status, result['duplicate'], result['count']), (200, True, index))

    def test_stale_partial_and_disabled_cache_require_review_not_unknown_receipt(self):
        for change in ['partial', 'expired', 'disabled']:
            with app.db() as db:
                if change == 'partial':
                    db.execute("DELETE FROM dhl_tracking_pieces WHERE piece_id='JD000003'")
                elif change == 'expired':
                    db.execute('UPDATE dhl_tracking_cache SET expires_at=1')
            with patch.dict(os.environ, {'WMS_DHL_ENABLED': '0' if change == 'disabled' else '1'}):
                before = self.snapshot()
                status, data = self.request('/api/receptions/truck-guide/scan-package', 'POST',
                    data=self.package('JD000003'))
                self.assertEqual(status, 400)
                self.assertIn('error', data)
                self.assertEqual(before, self.snapshot())

    def test_worker_cannot_replace_scans_with_a_quantity_on_close(self):
        self.request('/api/receptions/truck-guide/scan-package', 'POST', data=self.package('JD000001'))
        before = self.snapshot()
        status, _ = self.request('/api/receptions/truck-arrival', 'POST', data={
            'truck_guide': self.guide, 'arrival_key': 'QA-FORGED-COUNT',
            'bls': [{'shipment_id': self.sid, 'received_packages': 3, 'excess_reason': 'QA forged reason'}]})
        self.assertEqual(status, 400)
        self.assertEqual(before, self.snapshot())
        with app.db() as db:
            with self.assertRaisesRegex(ValueError, 'escaneados'):
                reception.confirm_truck_bl_arrival(db, self.guide, self.sid, 3,
                    'QA-DIRECT', 'qa', 'ASISTENTE_RECEPCION', excess_reason='QA forged reason')
        status, result = self.request('/api/receptions/truck-guide/scan-finalize', 'POST',
                                     data={'truck_guide': self.guide})
        self.assertEqual((status, result['received_packages']), (200, 1))


if __name__ == '__main__':
    unittest.main()
