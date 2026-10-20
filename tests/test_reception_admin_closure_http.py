"""Admin closure HTTP tests use only a disposable, synthetic local database."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import app
from tests.test_reception_partial_count_http import seed_partial


class AdminClosureHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='wms-admin-closure-http-')
        cls.path = Path(cls.directory.name) / 'qa.sqlite'
        cls.env = patch.dict(os.environ, {'TRITON_AUTH_MODE': 'demo', 'TRITON_MAIL_ENABLED': '0',
            'WMS_CLOUD_AUTO_SYNC': '0', 'WMS_PURCHASE_ALERT_WORKER': '0', 'WMS_TRANSFER_WORKER': '0'})
        cls.database = patch.object(app, 'DB_PATH', cls.path)
        cls.env.start(); cls.database.start(); app.init_db()
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
        cls.database.stop(); cls.env.stop(); cls.directory.cleanup()

    def setUp(self):
        self.bl = 'QA-CLOSURE-' + self._testMethodName
        with app.db() as db:
            self.sid, self.aid, self.ids = seed_partial(db, self.bl)
            rid = db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,received_at,username)
                VALUES (?,1,1,'2026-10-20 08:00:00','receiver')''', (self.sid,)).lastrowid
            db.execute('UPDATE reception_attentions SET receipt_id=? WHERE id=?', (rid, self.aid))

    def request(self, data=None, role='ADMINISTRADOR', suffix='', sid=None):
        headers = {'X-User': 'qa.admin' if role == 'ADMINISTRADOR' else 'receiver', 'X-Role': role}
        encoded = None if data is None else json.dumps(data).encode()
        if encoded is not None:
            headers['Content-Type'] = 'application/json'
        return urlopen(Request(self.base + f'/api/receptions/{sid or self.sid}/admin-closure' + suffix,
                               data=encoded, headers=headers))

    def preview(self):
        with self.request(suffix=f'?attention_id={self.aid}') as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def body(self, action='close_bl'):
        return {'action': action, 'attention_id': self.aid, 'token': self.preview()['token'],
                'reason': 'Explicit administrative regularization of synthetic QA case',
                'confirmed': True, 'acknowledge_unverified': True, 'bl_confirmation': self.bl}

    def dump(self):
        with app.db() as db:
            return list(db.iterdump())

    def test_preview_reports_blocker_without_mutation_or_hidden_role_bypass(self):
        before = self.dump()
        review = self.preview()
        self.assertEqual(review['id'], self.sid)
        self.assertFalse(review['can_reconcile'])
        self.assertTrue(review['reconcile_blocker'])
        self.assertTrue(review['can_close_bl'])
        self.assertEqual(self.dump(), before)
        for role in ('ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION', 'PICKER'):
            with self.subTest(role=role), self.assertRaises(HTTPError) as error:
                self.request(role=role)
            self.assertEqual(error.exception.code, 403)
            self.assertIn('error', json.load(error.exception))

    def test_admin_exception_closes_without_manufacturing_accounting_or_quantities(self):
        body = self.body()
        with app.db() as db:
            lines = [tuple(r) for r in db.execute('SELECT * FROM reception_lines WHERE shipment_id=?', (self.sid,))]
            receipts = [tuple(r) for r in db.execute('SELECT * FROM reception_receipts WHERE shipment_id=?', (self.sid,))]
        with self.request(body) as response:
            result = json.load(response)
        self.assertEqual(result['id'], self.sid)
        self.assertEqual(result['app_status'], 'CERRADO')
        with app.db() as db:
            row = db.execute('SELECT app_status,condition_status,transfer_assistant_checked FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()
            self.assertEqual(tuple(row), ('CERRADO', 'CIERRE ADMINISTRATIVO', 0))
            self.assertEqual(lines, [tuple(r) for r in db.execute('SELECT * FROM reception_lines WHERE shipment_id=?', (self.sid,))])
            self.assertEqual(receipts, [tuple(r) for r in db.execute('SELECT * FROM reception_receipts WHERE shipment_id=?', (self.sid,))])
            history = db.execute('SELECT COUNT(*) FROM reception_history WHERE shipment_id=?', (self.sid,)).fetchone()[0]
        with self.request(body) as response:
            self.assertTrue(json.load(response)['unchanged'])
        with app.db() as db:
            self.assertEqual(history, db.execute('SELECT COUNT(*) FROM reception_history WHERE shipment_id=?', (self.sid,)).fetchone()[0])

    def test_untrusted_role_and_invalid_ack_or_stale_token_never_write(self):
        body = self.body()
        cases = [({**body, 'confirmed': False}, 'ADMINISTRADOR', 400),
                 ({**body, 'acknowledge_unverified': False}, 'ADMINISTRADOR', 400),
                 ({**body, 'bl_confirmation': 'QA-WRONG'}, 'ADMINISTRADOR', 400),
                 ({**body, 'token': 'outdated'}, 'ADMINISTRADOR', 400),
                 (body, 'ASISTENTE_RECEPCION', 403)]
        for data, role, status in cases:
            before = self.dump()
            with self.subTest(role=role, data=data), self.assertRaises(HTTPError) as error:
                self.request(data, role=role)
            self.assertEqual(error.exception.code, status)
            self.assertIn('error', json.load(error.exception))
            self.assertEqual(self.dump(), before)

    def test_partial_attention_close_never_closes_master_or_overwrites_np_balance(self):
        with app.db() as db:
            db.execute('''UPDATE reception_attention_lines SET verified_qty=0,
                np_unreceived_reason='Not received in this arrival' WHERE attention_id=? AND reception_line_id=?''',
                (self.aid, self.ids[-1]))
        with self.request(self.body('close_attention')) as response:
            json.load(response)
        with app.db() as db:
            self.assertNotEqual(db.execute('SELECT app_status FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()[0], 'CERRADO')
            self.assertEqual(db.execute('SELECT app_status FROM reception_attentions WHERE id=?', (self.aid,)).fetchone()[0], 'CERRADO')
            self.assertEqual(db.execute('SELECT verified_qty FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',
                (self.aid, self.ids[-1])).fetchone()[0], 0)

    def test_audio_and_new_admin_assets_have_safe_mime_and_cache(self):
        for name, mime in [('reception-admin-closure.js', 'javascript'), ('reception-admin-closure.css', 'text/css')]:
            with urlopen(self.base + '/assets/' + name + '?v=20261020') as response:
                self.assertEqual(response.status, 200)
                self.assertIn(mime, response.headers['Content-Type'])
                self.assertIn('no-cache', response.headers['Cache-Control'])


if __name__ == '__main__':
    unittest.main()
