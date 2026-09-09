"""Queue caps and filtering against disposable data, never the operational DB."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from backend import app
from backend.services.reception import create_reception, list_receptions


class WorkspaceQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle, name = tempfile.mkstemp(prefix='wms-navigation-', suffix='.db')
        os.close(handle)
        cls.path = Path(name)
        cls.env = patch.dict(os.environ, {'TRITON_AUTH_MODE': 'demo'})
        cls.env.start()
        cls.db_patch = patch.object(app, 'DB_PATH', cls.path)
        cls.db_patch.start()
        app.init_db()
        with app.db() as connection:
            for i in range(30):
                day = '2026-09-08' if i < 20 else '2026-09-09'
                record = create_reception(connection, {
                    'bl_awb': f'TEST-BL-{9000+i}', 'scheduled_date': day,
                    'transport_type': 'AEREO', 'supplier': 'Proveedor de prueba',
                    'current_assistant': 'test.assistant' if i < 25 else 'other.assistant',
                    'current_auxiliary': 'test.auxiliary',
                }, 'demo.admin', 'ADMINISTRADOR')
                if i >= 25:
                    connection.execute("UPDATE reception_shipments SET app_status='ARRIBADO' WHERE id=?", (record['id'],))
                stamp = f'2026-09-08T08:{i:02d}:00'
                connection.execute('INSERT INTO orders (sap_ov,customer_name,source_order_date,created_at,updated_at) VALUES (?,?,?,?,?)',
                    (str(800000+i), 'Cliente de prueba', stamp, stamp, stamp))
                connection.execute('INSERT INTO order_lines(sap_ov,source_row,item_code,pending_qty,required_qty,available_qty,warehouse) VALUES (?,?,?,?,?,?,?)',
                    (str(800000+i), i+1, f'TEST-NP-{i}', 1, 1, 5, '1'))
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.db_patch.stop()
        cls.env.stop()
        for suffix in ('', '-wal', '-shm'):
            Path(str(cls.path)+suffix).unlink(missing_ok=True)

    def get(self, path, role='ADMINISTRADOR', username='demo.admin'):
        request = Request(self.base+path, headers={'X-Role':role,'X-User':username})
        with urlopen(request) as response:
            return json.load(response)

    def test_reception_capped_for_admin_and_worker(self):
        self.assertEqual(len(self.get('/api/receptions')), 10)
        rows = self.get('/api/receptions', 'ASISTENTE_RECEPCION', 'test.assistant')
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row['current_assistant']=='test.assistant' for row in rows))

    def test_filters_run_before_limit(self):
        rows = self.get('/api/receptions?date=2026-09-09&state=ARRIBADO')
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row['scheduled_date']=='2026-09-09' and row['app_status']=='ARRIBADO' for row in rows))
        rows = self.get('/api/receptions?search=9029')
        self.assertEqual([row['bl_awb'] for row in rows], ['TEST-BL-9029'])
        self.assertEqual(self.get('/api/receptions?search=9029', 'ASISTENTE_RECEPCION', 'test.assistant'), [])

    def test_invalid_date_returns_400(self):
        with self.assertRaises(HTTPError) as error:
            self.get('/api/receptions?date=2026-02-31')
        self.assertEqual(error.exception.code, 400)

    def test_dispatch_latest_twenty_and_search_outside_page(self):
        rows = self.get('/api/orders')
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]['sap_ov'], '800029')
        self.assertEqual(rows[-1]['sap_ov'], '800010')
        self.assertEqual(self.get('/api/orders?search=800000')[0]['sap_ov'], '800000')

    def test_date_range_and_global_work_summary(self):
        rows = self.get('/api/receptions?date=2026-09-08&date_end=2026-09-09')
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row['scheduled_date'] in {'2026-09-08', '2026-09-09'} for row in rows))
        dispatch = self.get('/api/work-summary?module=dispatch')
        self.assertEqual(dispatch['total'], 30)
        self.assertEqual(dispatch['by_status']['PENDIENTE'], 30)
        reception = self.get('/api/work-summary?module=reception')
        self.assertEqual(reception['total'], 30)
        self.assertEqual(reception['by_status']['PROGRAMADO'], 25)
        self.assertEqual(reception['by_status']['ARRIBADO'], 5)

    def test_service_caps_cannot_be_bypassed(self):
        with app.db() as connection:
            self.assertEqual(len(list_receptions(connection, limit=1000)), 10)
        self.assertEqual(len(app.orders_payload(limit=1000)), 20)


if __name__ == '__main__':
    if '--serve' in sys.argv:
        WorkspaceQueueTests.setUpClass()
        print('BROWSER_TEST_URL='+WorkspaceQueueTests.base, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            WorkspaceQueueTests.tearDownClass()
    else:
        unittest.main()
