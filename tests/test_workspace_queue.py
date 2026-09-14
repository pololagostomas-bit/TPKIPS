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

<<<<<<< HEAD
    def post(self, path, payload, role='ADMINISTRADOR', username='demo.admin'):
        request = Request(
            self.base+path, data=json.dumps(payload).encode('utf-8'), method='POST',
            headers={'Content-Type': 'application/json', 'X-Role': role, 'X-User': username},
        )
        with urlopen(request) as response:
            return json.load(response)

    def get_bytes(self, path, role='ADMINISTRADOR', username='demo.admin'):
        request = Request(self.base+path, headers={'X-Role':role,'X-User':username})
        with urlopen(request) as response:
            return response.status, response.headers, response.read()

=======
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
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
<<<<<<< HEAD
        # Other tests can assign an OV; the summary must still account for all OVs.
        self.assertEqual(sum(dispatch['by_status'].values()), 30)
=======
        self.assertEqual(dispatch['by_status']['PENDIENTE'], 30)
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312
        reception = self.get('/api/work-summary?module=reception')
        self.assertEqual(reception['total'], 30)
        self.assertEqual(reception['by_status']['PROGRAMADO'], 25)
        self.assertEqual(reception['by_status']['ARRIBADO'], 5)

    def test_service_caps_cannot_be_bypassed(self):
        with app.db() as connection:
            self.assertEqual(len(list_receptions(connection, limit=1000)), 10)
        self.assertEqual(len(app.orders_payload(limit=1000)), 20)

<<<<<<< HEAD
    def test_assigned_picker_and_guide_see_an_assigned_attention(self):
        with app.db() as connection:
            timestamp = '2026-09-09T12:00:00'
            connection.execute(
                """INSERT INTO attentions
                   (sap_ov, sequence_no, attention_type, app_status, current_picker,
                    current_guide, created_at, updated_at)
                   VALUES (?, 1, 'SELECCIONAR', 'ASIGNADO', ?, ?, ?, ?)""",
                ('800000', 'picker.work', 'guide.work', timestamp, timestamp),
            )
        picker_rows = app.orders_payload(username='picker.work', role='PICKER')
        guide_rows = app.orders_payload(username='guide.work', role='GUIADOR')
        self.assertEqual([row['sap_ov'] for row in picker_rows], ['800000'])
        self.assertEqual([row['sap_ov'] for row in guide_rows], ['800000'])
        self.assertTrue(app.can_view_order('800000', 'guide.work', 'GUIADOR'))

    def test_combined_assignment_exposes_quantities_and_completes_flow(self):
        """One hybrid worker can complete picker and guide work from one assignment."""
        with app.db() as connection:
            stamp = '2026-09-11T18:00:00'
            connection.execute(
                "INSERT INTO users (username, display_name, role, shift, active, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                ('hybrid.flow', 'Responsable híbrido', 'PICKER_GUIADOR', 'DÍA', 1, stamp, stamp),
            )
            connection.execute(
                "INSERT INTO users (username, display_name, role, shift, active, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                ('reception.flow', 'Recepción excepcional', 'ASISTENTE_RECEPCION', 'DÍA', 1, stamp, stamp),
            )
        self.assertEqual([row['username'] for row in app.list_assignees('PICKER_GUIADOR')], ['hybrid.flow'])
        self.assertEqual(
            {row['username'] for row in app.list_assignees('PICKER_GUIADOR', include_reception=True)},
            {'hybrid.flow', 'reception.flow'},
        )
        attention = app.create_attention('800004', 'demo.admin', 'ADMINISTRADOR')
        attention_id = attention['id']
        assigned_order = self.post(
            '/api/orders/800004/assign',
            {'field': 'responsibles', 'picker': 'hybrid.flow', 'guide': 'hybrid.flow'},
        )
        assigned = assigned_order['attentions'][0]
        self.assertEqual(assigned['app_status'], 'ASIGNADO')
        self.assertEqual(assigned['current_picker'], 'hybrid.flow')
        self.assertEqual(assigned['current_guide'], 'hybrid.flow')
        self.assertEqual(len(assigned['assignments']), 2)

        started = app.change_attention_status(
            attention_id, 'EN PICKING', 'hybrid.flow', 'PICKER_GUIADOR'
        )
        line = started['lines'][0]
        self.assertGreater(line['planned_qty'], 0)
        self.assertGreater(line['picked_qty'], 0)
        self.assertEqual(
            app.orders_payload(username='hybrid.flow', role='PICKER_GUIADOR')[0]['sap_ov'],
            '800004',
        )
        app.update_attention_line(
            attention_id, line['id'], 'picked_qty', line['planned_qty'],
            'hybrid.flow', 'PICKER_GUIADOR',
        )
        picked = app.change_attention_status(
            attention_id, 'PICKING FINALIZADO', 'hybrid.flow', 'PICKER_GUIADOR'
        )
        self.assertEqual(picked['app_status'], 'POR GUIAR')
        guided = app.change_attention_status(
            attention_id, 'EN GUIADO', 'hybrid.flow', 'PICKER_GUIADOR'
        )
        self.assertEqual(guided['lines'][0]['delivered_qty'], line['planned_qty'])
        app.change_attention_status(
            attention_id, 'GUIADO FINALIZADO', 'hybrid.flow', 'PICKER_GUIADOR'
        )
        with app.db() as connection:
            app.save_delivery_evidence(connection, attention_id, {
                'file_name': 'guia-prueba.png', 'mime_type': 'image/png',
                'image_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL4ggAAAABJRU5ErkJggg==',
            }, 'hybrid.flow', 'PICKER_GUIADOR')
        delivered = app.change_attention_status(
            attention_id, 'ENTREGADO', 'hybrid.flow', 'PICKER_GUIADOR'
        )
        self.assertEqual(delivered['app_status'], 'ENTREGADO')
        status, headers, body = self.get_bytes('/api/reports/operational/export')
        self.assertEqual(status, 200)
        self.assertIn('spreadsheetml.sheet', headers.get_content_type() + ';' + headers.get('Content-Type', ''))
        self.assertTrue(body.startswith(b'PK'))
        workbook = app.load_workbook(__import__('io').BytesIO(body), read_only=True)
        self.assertEqual(workbook.sheetnames, ['Reporte tiempos'])
        self.assertIn('Minutos picking', next(workbook['Reporte tiempos'].iter_rows(values_only=True)))
        workbook.close()

    def test_picker_guiador_sees_picker_and_guide_assignments(self):
        """The hybrid role receives work whether it is assigned as picker or guide."""
        with app.db() as connection:
            timestamp = '2026-09-09T12:10:00'
            for ov, picker, guide in (
                ('800001', 'hybrid.work', None),
                ('800002', None, 'hybrid.work'),
                ('800003', 'hybrid.work', 'hybrid.work'),
            ):
                connection.execute(
                    """INSERT INTO attentions
                       (sap_ov, sequence_no, attention_type, app_status, current_picker,
                        current_guide, created_at, updated_at)
                       VALUES (?, 1, 'SELECCIONAR', 'ASIGNADO', ?, ?, ?, ?)""",
                    (ov, picker, guide, timestamp, timestamp),
                )
        rows = app.orders_payload(username='hybrid.work', role='PICKER_GUIADOR', limit=20)
        self.assertEqual({row['sap_ov'] for row in rows}, {'800001', '800002', '800003'})
        self.assertTrue(app.can_view_order('800001', 'hybrid.work', 'PICKER_GUIADOR'))
        self.assertTrue(app.can_view_order('800002', 'hybrid.work', 'PICKER_GUIADOR'))

=======
>>>>>>> 3b9f04f67883bd897fae4700181dda909c5f0312

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
