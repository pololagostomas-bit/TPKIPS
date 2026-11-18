import tempfile
import unittest
from pathlib import Path

from backend import app
from backend.services import dispatch_operations as ops


PHOTO = {'mime_type': 'image/png', 'file_name': 'guia.png',
         'image_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=',
         'recipient_signed': True, 'warehouse_signed': True}


class DispatchSTSTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.previous = app.DB_PATH
        app.DB_PATH = Path(self.folder.name) / 'test.sqlite3'
        app.init_db()
        with app.db() as db:
            stamp = app.now()
            db.execute("INSERT INTO users(username,display_name,role,active,created_at,updated_at) VALUES('picker','Picker','PICKER_GUIADOR',1,?,?)", (stamp, stamp))
            db.execute("INSERT INTO inventory_stock(item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,snapshot_at,is_current,updated_at) VALUES('NP01','1','NP-01','1',10,?,?,1,?)", (stamp[:10], stamp, stamp))
            ops.save_branch(db, {'code': 'NORTE', 'name': 'Sucursal Norte'}, 'admin', 'ADMINISTRADOR')

    def tearDown(self):
        app.DB_PATH = self.previous
        self.folder.cleanup()

    def request(self, key='request-1', quantity=3):
        return ops.create_request(app, {'request_key': key, 'kind': 'STS', 'destination': 'NORTE',
            'due_date': '2026-12-01', 'lines': [{'item_code': 'NP-01', 'quantity': quantity}]}, 'admin', 'ADMINISTRADOR')

    def begin(self):
        code = self.request()['sap_ov']
        aid = app.create_attention(code, 'admin', 'ADMINISTRADOR')['id']
        app.assign_attention_responsibles(aid, 'picker', 'picker', 'admin', 'ADMINISTRADOR')
        app.change_attention_status(aid, 'EN PICKING', 'picker', 'PICKER_GUIADOR')
        return code, aid

    def guided(self):
        code, aid = self.begin()
        ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')
        ops.finish_picking(app, aid, 'picker', 'PICKER_GUIADOR')
        app.change_attention_status(aid, 'EN GUIADO', 'picker', 'PICKER_GUIADOR')
        app.change_attention_status(aid, 'GUIADO FINALIZADO', 'picker', 'PICKER_GUIADOR')
        return code, aid

    def test_request_retry_stock_pool_and_bad_values(self):
        first = self.request()
        self.assertEqual(first['sap_ov'], self.request()['sap_ov'])
        with self.assertRaises(ValueError): self.request(quantity=float('nan'))
        with self.assertRaises(ValueError): self.request(quantity=4)
        with self.assertRaises(PermissionError): ops.create_request(app, {}, 'picker', 'PICKER')

    def test_next_sap_ov_cut_keeps_the_local_sts(self):
        from tests.test_daily_operations import dispatch
        code = self.request()['sap_ov']
        app.import_daily_excel(dispatch([('QA-OV', 1, 'NP-02', 2, 5, 'ABIERTO')]),
            'qa.xlsx', 'dispatch', '2026-11-18T08:00:00', 'admin', 'ADMINISTRADOR')
        with app.db() as db:
            self.assertEqual(db.execute('SELECT source_present FROM orders WHERE sap_ov=?', (code,)).fetchone()[0], 1)
        self.assertEqual([row['sap_ov'] for row in app.orders_payload(document_kind='STS')], [code])

    def test_matrix_scan_rejects_wrong_np_and_operator_without_duplicating(self):
        _, aid = self.begin()
        with self.assertRaises(ValueError): ops.scan(app, aid, 'OTHER', 'picker', 'PICKER_GUIADOR')
        with self.assertRaises(PermissionError): ops.scan(app, aid, 'NP-01', 'another', 'PICKER_GUIADOR')
        with self.assertRaises(ValueError): ops.finish_picking(app, aid, 'picker', 'PICKER_GUIADOR')
        first = ops.scan(app, aid, '*NP-01*\r\n', 'picker', 'PICKER_GUIADOR')
        self.assertEqual(first['line_id'], ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')['line_id'])
        with app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dispatch_reads').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT picked_qty FROM attention_lines').fetchone()[0], 3)

    def test_delivery_requires_both_signature_confirmations(self):
        _, aid = self.guided()
        with self.assertRaises(ValueError): app.change_attention_status(aid, 'ENTREGADO', 'picker', 'PICKER_GUIADOR')
        for field in ('recipient_signed', 'warehouse_signed'):
            with self.subTest(field=field), app.db() as db, self.assertRaises(ValueError):
                app.save_delivery_evidence(db, aid, dict(PHOTO, **{field: False}), 'picker', 'PICKER_GUIADOR')
        with app.db() as db:
            app.save_delivery_evidence(db, aid, PHOTO, 'picker', 'PICKER_GUIADOR')
            metadata = app.delivery_evidence_metadata(db, aid)
            self.assertTrue(metadata['recipient_signed'] and metadata['warehouse_signed'])

    def test_fake_photo_and_foreign_receipt_are_rejected(self):
        with self.assertRaises(ValueError): ops.signed_photo(dict(PHOTO, image_base64='aW1hZ2U='))
        with self.assertRaises(ValueError): ops.signed_photo(dict(PHOTO, recipient_signed='true'))
        with self.assertRaises(PermissionError): ops.receive(app, 1, {}, 'picker', 'PICKER_GUIADOR')

    def test_quantity_correction_requires_another_read(self):
        _, aid = self.begin()
        line = ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')['line_id']
        app.update_attention_line(aid, line, 'picked_qty', 2, 'picker', 'PICKER_GUIADOR')
        with self.assertRaises(ValueError): ops.finish_picking(app, aid, 'picker', 'PICKER_GUIADOR')
        ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')
        ops.finish_picking(app, aid, 'picker', 'PICKER_GUIADOR')

    def test_repeated_np_lines_require_a_specific_line(self):
        code, aid = self.begin()
        with app.db() as db:
            source = db.execute("INSERT INTO order_lines(sap_ov,source_row,item_code,description,required_qty,pending_qty,available_qty,warehouse) VALUES(?,99,'NP-01','Otro destino',1,1,10,'1')", (code,)).lastrowid
            db.execute("INSERT INTO attention_lines(attention_id,order_line_id,planned_qty,item_code,description,warehouse) VALUES(?,?,1,'NP-01','Otro destino','1')", (aid, source))
        choices = ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')['choices']
        self.assertEqual(len(choices), 2)
        with self.assertRaises(ValueError): ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR', 999999)
        ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR', choices[0]['id'])
        with app.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM dispatch_reads').fetchone()[0], 1)

    def test_sts_share_stock_with_existing_reservations(self):
        for key in ('first', 'second'):
            code = self.request(key, 7)['sap_ov']
            aid = app.create_attention(code, 'admin', 'ADMINISTRADOR')['id']
            app.assign_attention_responsibles(aid, 'picker', 'picker', 'admin', 'ADMINISTRADOR')
            app.change_attention_status(aid, 'EN PICKING', 'picker', 'PICKER_GUIADOR')
        with app.db() as db:
            self.assertEqual(db.execute("SELECT SUM(reserved_qty) FROM stock_allocations WHERE status='ACTIVA'").fetchone()[0], 10)

    def test_admin_cannot_ship_sts_without_finished_picking(self):
        _, aid = self.begin()
        app.change_attention_status(aid, 'EN GUIADO', 'admin', 'ADMINISTRADOR')
        with app.db() as db: line = app.attention_payload(db, aid)['lines'][0]['id']
        app.update_attention_line(aid, line, 'delivered_qty', 3, 'picker', 'PICKER_GUIADOR')
        app.change_attention_status(aid, 'GUIADO FINALIZADO', 'admin', 'ADMINISTRADOR')
        with app.db() as db: app.save_delivery_evidence(db, aid, PHOTO, 'admin', 'ADMINISTRADOR')
        with self.assertRaises(ValueError): ops.ship(app, aid, {'guide_reference':'NO-PICKING'}, 'admin', 'ADMINISTRADOR')

    def test_rollback_and_reset_require_new_physical_verification(self):
        _, aid = self.begin()
        ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')
        ops.finish_picking(app, aid, 'picker', 'PICKER_GUIADOR')
        app.admin_rollback_attention(aid, 'admin', 'ADMINISTRADOR', 'Revisar picking')
        with self.assertRaises(ValueError): ops.finish_picking(app, aid, 'picker', 'PICKER_GUIADOR')
        ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')
        app.admin_reset_attention(aid, 'admin', 'ADMINISTRADOR', 'Reiniciar prueba')
        with app.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM dispatch_reads').fetchone()[0], 0)

    def test_explicit_destructive_excel_reset_cleans_dependent_dispatch_rows(self):
        from tests.test_daily_operations import dispatch
        _, aid = self.begin()
        ops.scan(app, aid, 'NP-01', 'picker', 'PICKER_GUIADOR')
        source = Path(self.folder.name)/'reset-test.xlsx'
        source.write_bytes(dispatch([('QA-OV', 1, 'NP-02', 2, 5, 'ABIERTO')]))
        app.import_excel(source, reset=True)
        with app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dispatch_context').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dispatch_reads').fetchone()[0], 0)

    def test_http_session_roles_and_np_validation(self):
        import threading
        import requests
        _, aid = self.begin()
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            headers = {'X-User': 'picker', 'X-Role': 'PICKER_GUIADOR'}
            denied = requests.post(base+'/api/dispatch/requests', json={}, headers=headers, timeout=5)
            self.assertEqual(denied.status_code, 403)
            bad = requests.post(f'{base}/api/dispatch/attentions/{aid}/scan', json={'code':'BAD'}, headers=headers, timeout=5)
            self.assertEqual(bad.status_code, 400)
            read = requests.post(f'{base}/api/dispatch/attentions/{aid}/scan', json={'code':'NP-01'}, headers=headers, timeout=5)
            self.assertEqual(read.status_code, 200)
            self.assertTrue(read.json()['conform'])
            branches = requests.get(base+'/api/dispatch/branches', headers=headers, timeout=5)
            self.assertEqual(branches.status_code, 200)
            private = requests.get(base+'/api/dispatch/receipts/test/evidence', headers=headers, timeout=5)
            self.assertEqual(private.status_code, 403)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_sts_receipt_needs_its_own_photo_and_does_not_deduct_stock_twice(self):
        code, aid = self.guided()
        with app.db() as db: app.save_delivery_evidence(db, aid, PHOTO, 'picker', 'PICKER_GUIADOR')
        ops.ship(app, aid, {'guide_reference': 'GUIA-TEST'}, 'picker', 'PICKER_GUIADOR')
        self.assertTrue(app.can_view_order(code, 'picker', 'PICKER_GUIADOR'))
        self.assertFalse(app.can_view_order(code, 'another', 'PICKER_GUIADOR'))
        self.assertEqual(app.order_payload(code)['dispatch_context']['pending_qty'], 0)
        with self.assertRaises(ValueError): app.create_attention(code, 'admin', 'ADMINISTRADOR')
        with app.db() as db:
            shipment = ops.shipments(db, code)[0]
            consumed = db.execute('SELECT SUM(consumed_qty) FROM stock_allocations').fetchone()[0]
        self.assertEqual(shipment['state'], 'EN TRANSITO')
        payload = {'request_key': 'receipt-1', 'receiver': 'Receptor',
                   'lines': [{'id': shipment['lines'][0]['id'], 'quantity': 1}]}
        with self.assertRaises(ValueError): ops.receive(app, aid, payload, 'admin', 'ADMINISTRADOR')
        payload['evidence'] = PHOTO
        first = ops.receive(app, aid, payload, 'admin', 'ADMINISTRADOR')
        self.assertEqual(first[0]['state'], 'RECEPCION PARCIAL')
        self.assertEqual(first, ops.receive(app, aid, payload, 'admin', 'ADMINISTRADOR'))
        with app.db() as db:
            self.assertEqual(db.execute('SELECT SUM(consumed_qty) FROM stock_allocations').fetchone()[0], consumed)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dispatch_receipt_evidence').fetchone()[0], 1)


if __name__ == '__main__': unittest.main()
