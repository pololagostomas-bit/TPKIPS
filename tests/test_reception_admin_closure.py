"""Administrative exceptions preserve physical and documentary evidence."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from backend.services import reception, reception_admin_closure as service
from backend.services.reception_closure import closure_check
from backend.services.traceability import init_traceability_schema


ADMIN = 'ADMINISTRADOR'
STAMP = '2026-10-20 12:00:00'
REASON = 'Owner confirms exceptional regularization for synthetic QA'
CONDITION = 'CIERRE ADMINISTRATIVO'


class AdminClosureTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute('''CREATE TABLE order_importation_refs
            (bl_awb TEXT,sap_ov TEXT,transport_type TEXT,ip_reference TEXT,oc_number TEXT)''')
        self.sid = self.shipment('QA-ADMIN-CLOSURE')

    def shipment(self, bl):
        return self.db.execute('''INSERT INTO reception_shipments
            (bl_awb,created_at,updated_at,physical_initialized,system_quantities_initialized)
            VALUES (?,?,?,1,1)''', (bl, STAMP, STAMP)).lastrowid

    def rows(self, table):
        return [dict(row) for row in self.db.execute(f'SELECT * FROM {table} ORDER BY rowid')]

    def master(self):
        return dict(self.db.execute('SELECT * FROM reception_shipments WHERE id=?',
                                   (self.sid,)).fetchone())

    def line(self, expected=8, received=0, ip='IP-QA', scanned=False):
        return self.db.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,ip_reference,expected_qty,received_qty,np_scanned_at,np_scanned_by)
            VALUES (?,'NP-QA',?,?,?,?,?)''',
            (self.sid, ip, expected, received, STAMP if scanned else None,
             'qa.worker' if scanned else None)).lastrowid

    def attention(self, status='REVISION SISTEMA', packages=1, guide=None):
        seq = self.db.execute('SELECT COUNT(*)+1 FROM reception_receipts WHERE shipment_id=?',
                              (self.sid,)).fetchone()[0]
        rid = self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,truck_guide,username,received_at)
            VALUES (?,?,?,?,?,?)''', (self.sid, seq, packages, guide, 'qa.worker', STAMP)).lastrowid
        row = reception._create_reception_attention(self.db,
            self.db.execute('SELECT * FROM reception_shipments WHERE id=?', (self.sid,)).fetchone(),
            rid, 'qa.worker', status)
        self.db.execute('UPDATE reception_attentions SET system_quantities_initialized=1 WHERE id=?',
                        (row['id'],))
        self.db.execute('''UPDATE reception_shipments SET app_status=?,condition_status='EN PROCESO',
            received_packages=(SELECT SUM(received_packages) FROM reception_receipts WHERE shipment_id=?)
            WHERE id=?''', (status, self.sid, self.sid))
        return row['id']

    def accounting(self, ip='IP-QA'):
        ref = self.db.execute('''INSERT INTO reception_accounting_refs
            (shipment_id,source_key,ip_reference,fr_number,em_number,created_at,updated_at)
            VALUES (?,? ,?,'FR-QA','EM-QA',?,?)''',
            (self.sid, 'QA-REF-' + str(self.db.execute(
                'SELECT COUNT(*) FROM reception_accounting_refs').fetchone()[0]), ip, STAMP, STAMP)).lastrowid
        self.db.execute('''INSERT INTO reception_accounting_ems
            (accounting_ref_id,em_number,username,created_at) VALUES (?,'EM-QA','qa',?)''', (ref, STAMP))
        return ref

    def truck(self, status='EN_CURSO', *, cancelled_pilot=False):
        self.db.execute('''INSERT INTO reception_truck_guides
            (guide_code,guide_status,is_confirmed,source_type,created_by,created_at,updated_at,
             archived_at,archive_reason)
            VALUES ('QA-TRUCK',?,1,'ESCANER','qa',?,?,?,?)''',
            (status, STAMP, STAMP, STAMP if cancelled_pilot else None,
             'camion de prueba retirado' if cancelled_pilot else None))

    def manifest(self):
        self.db.execute('''INSERT INTO reception_truck_bl_manifest
            (truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at)
            VALUES ('QA-TRUCK',?,1,'qa',?,?)''', (self.sid, STAMP, STAMP))

    def transfer(self, aid=0, status='ACCEPTED'):
        return self.db.execute('''INSERT INTO reception_transfer_requests
            (shipment_id,attention_id,status,created_at,token_hash) VALUES (?,?,?,0,?)''',
            (self.sid, aid, status, 'qa-token-' + str(self.db.execute(
                'SELECT COUNT(*) FROM reception_transfer_requests').fetchone()[0]))).lastrowid

    def preview(self, aid=None, role=ADMIN):
        return service.preview_closure(self.db, self.sid, 'qa.admin', role, aid)

    def request(self, action='close_bl', aid=None, **changes):
        data = {'action': action, 'confirmed': True, 'bl_confirmation': self.master()['bl_awb'],
                'reason': REASON, 'token': self.preview(aid)['token'],
                'acknowledge_unverified': True}
        if aid is not None:
            data['attention_id'] = aid
        data.update(changes)
        return data

    def apply(self, data=None, **changes):
        return service.apply_closure(self.db, self.sid, data or self.request(**changes), 'qa.admin', ADMIN)

    def test_preview_has_contract_is_readonly_and_does_not_initialize_attention_or_sample(self):
        self.line(received=8)
        self.db.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA'")
        self.db.commit()
        before = list(self.db.iterdump())
        changes = self.db.total_changes
        self.db.execute('PRAGMA query_only=ON')
        result = self.preview()
        self.assertEqual(set(result), {
            'id', 'bl_awb', 'attention_id', 'app_status', 'condition_status', 'token',
            'can_reconcile', 'reconcile_blocker', 'reconcile_basis', 'can_retire_test', 'retire_blocker',
            'can_close_bl', 'close_bl_blocker', 'can_close_attention', 'attention_blocker',
            'open_attention_count', 'unread_np_count', 'pending_np_count', 'accounting_status'})
        self.assertEqual(result['id'], self.sid)
        self.assertIsNone(result['attention_id'])
        self.assertEqual(result['unread_np_count'], 1)
        self.assertEqual(result['pending_np_count'], 0)
        self.assertTrue(result['can_close_bl'])
        self.assertFalse(result['can_reconcile'])
        self.assertTrue(result['reconcile_blocker'])
        self.assertEqual(self.preview()['token'], result['token'])
        self.assertEqual(changes, self.db.total_changes)
        self.assertEqual(before, list(self.db.iterdump()))

    def test_roles_are_checked_before_any_read_even_for_get(self):
        data = self.request()
        for role in ('ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION', 'PICKER', None, ''):
            statements = []
            self.db.set_trace_callback(statements.append)
            try:
                with self.subTest(role=role), self.assertRaises(PermissionError):
                    self.preview(role=role)
                with self.subTest(role=role), self.assertRaises(PermissionError):
                    service.apply_closure(self.db, self.sid, data, 'qa.admin', role)
                self.assertEqual(statements, [])
            finally:
                self.db.set_trace_callback(None)

    def test_unknown_shipment_and_invalid_or_foreign_attention_do_not_fall_back(self):
        other = self.shipment('QA-OTHER')
        for aid in (0, -1, True, 1.5, '', 'no', '1.0', [], {}, 9000):
            with self.subTest(aid=aid), self.assertRaises(ValueError):
                self.preview(aid)
        self.line()
        aid = self.attention()
        with self.assertRaises(ValueError):
            service.preview_closure(self.db, other, 'qa.admin', ADMIN, aid)
        with self.assertRaises(ValueError):
            service.preview_closure(self.db, 99999, 'qa.admin', ADMIN)
        self.assertEqual(self.preview(str(aid))['attention_id'], aid)

    def test_confirmation_reason_identity_and_action_validation_are_atomic(self):
        data = self.request()
        cases = ({'confirmed': False}, {'confirmed': 'true'}, {'confirmed': 1},
                 {'bl_confirmation': 'qa-admin-closure'}, {'bl_confirmation': ' QA-ADMIN-CLOSURE'},
                 {'bl_confirmation': ''}, {'reason': 'short'}, {'reason': ' ' * 8},
                 {'reason': 'x' * 501}, {'reason': 12345678}, {'action': 'other'},
                 {'token': ''}, {'token': None}, {'token': 'z' * 64}, {'attention_id': False})
        for change in cases:
            before = list(self.db.iterdump())
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.apply({**data, **change})
            self.assertEqual(before, list(self.db.iterdump()))
        for invalid in (None, [], 'close_bl'):
            with self.assertRaises(ValueError):
                service.apply_closure(self.db, self.sid, invalid, 'qa.admin', ADMIN)
        with self.assertRaises(ValueError):
            service.apply_closure(self.db, self.sid, data, '', ADMIN)

    def test_exception_actions_require_literal_acknowledgment(self):
        aid = self.attention()
        for action, selected in (('close_bl', None), ('close_attention', aid)):
            data = self.request(action, selected)
            for value in (None, False, 'true', 1):
                with self.subTest(action=action, value=value), self.assertRaises(ValueError):
                    self.apply({**data, 'acknowledge_unverified': value})
        self.assertNotEqual(self.master()['app_status'], 'CERRADO')

    def test_reason_boundaries(self):
        for size in (8, 500):
            self.db.execute('SAVEPOINT qa_reason')
            result = self.apply(self.request(reason='x' * size))
            self.assertEqual(result['condition_status'], CONDITION)
            self.db.execute('ROLLBACK TO qa_reason')
            self.db.execute('RELEASE qa_reason')

    def test_unread_defaults_and_missing_np_are_distinct_and_selected(self):
        self.line(expected=8)
        first = self.attention()
        self.db.execute('UPDATE reception_attention_lines SET planned_qty=3,verified_qty=3 WHERE attention_id=?', (first,))
        second = self.attention()
        self.db.execute('UPDATE reception_attention_lines SET np_scanned_at=? WHERE attention_id=?', (STAMP, second))
        self.assertEqual((self.preview(first)['unread_np_count'], self.preview(first)['pending_np_count']), (1, 0))
        self.assertEqual((self.preview(second)['unread_np_count'], self.preview(second)['pending_np_count']), (0, 1))
        self.assertEqual(self.preview()['open_attention_count'], 2)

    def test_close_bl_allows_documentary_ip_mismatch_and_preserves_every_evidence_table(self):
        self.line(expected=8, received=3, scanned=True)
        first = self.attention()
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=3,np_scanned_at=?', (STAMP,))
        second = self.attention()
        self.accounting('P-QA')
        self.db.execute("UPDATE reception_shipments SET ip_reference='IP-QA',fr_number='FR-QA',em_number='EM-QA',validation_sample_json='[1]' WHERE id=?", (self.sid,))
        self.db.execute('''INSERT INTO inventory_lots
            (lot_code,reception_shipment_id,bl_awb,item_key,item_code,received_qty,created_by,created_at,updated_at)
            VALUES ('QA-LOT',?,'QA-ADMIN-CLOSURE','QA','NP-QA',3,'qa',?,?)''', (self.sid, STAMP, STAMP))
        preserved_tables = ('reception_lines', 'reception_attention_lines', 'reception_receipts',
            'reception_accounting_refs', 'reception_accounting_ems', 'inventory_lots',
            'reception_truck_package_scans', 'reception_truck_bl_arrivals',
            'reception_truck_bl_locations', 'reception_notifications')
        before = {table: self.rows(table) for table in preserved_tables}
        master = self.master()
        attentions = self.rows('reception_attentions')
        preview = self.preview()
        self.assertFalse(preview['can_reconcile'])
        self.assertTrue(preview['can_close_bl'])
        result = self.apply()
        self.assertEqual(result, {'id': self.sid, 'attention_id': None, 'app_status': 'CERRADO',
            'condition_status': CONDITION, 'action': 'close_bl', 'unchanged': False})
        for table in preserved_tables:
            self.assertEqual(self.rows(table), before[table], table)
        ignored = {'app_status', 'condition_status', 'updated_at'}
        self.assertEqual({k: v for k, v in master.items() if k not in ignored},
                         {k: v for k, v in self.master().items() if k not in ignored})
        for old, new in zip(attentions, self.rows('reception_attentions')):
            self.assertIn(new['id'], (first, second))
            self.assertEqual(new['app_status'], 'CERRADO')
            self.assertEqual(new['condition_status'], CONDITION)
            ignored = {'app_status', 'condition_status', 'updated_at', 'completed_at'}
            self.assertEqual({k: v for k, v in old.items() if k not in ignored},
                             {k: v for k, v in new.items() if k not in ignored})
        receipt = next(row for row in self.rows('reception_history') if row['field_name'] == 'admin_closure_request')
        audit = json.loads(receipt['new_value'])
        self.assertFalse(audit['fr_em_sap_verified'])
        self.assertIn('no verificados', receipt['reason'])
        self.assertIn(REASON, receipt['reason'])

    def test_close_attention_changes_only_selected_real_arrival_and_keeps_master_open(self):
        self.line(received=3)
        first = self.attention()
        second = self.attention(status='UBICACION')
        other = dict(self.db.execute('SELECT * FROM reception_attentions WHERE id=?', (second,)).fetchone())
        before_lines = self.rows('reception_attention_lines')
        result = self.apply(self.request('close_attention', first))
        self.assertEqual(result['attention_id'], first)
        self.assertEqual(result['app_status'], 'CERRADO')
        self.assertEqual(result['condition_status'], CONDITION)
        self.assertEqual(dict(self.db.execute('SELECT * FROM reception_attentions WHERE id=?', (second,)).fetchone()), other)
        self.assertEqual(self.master()['app_status'], other['app_status'])
        self.assertEqual(self.master()['condition_status'], other['condition_status'])
        self.assertEqual(self.rows('reception_attention_lines'), before_lines)

    def test_last_attention_closure_waits_for_later_arrival_even_when_normally_complete(self):
        self.line(expected=3, received=3, scanned=True)
        aid = self.attention()
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=3,np_scanned_at=?', (STAMP,))
        self.accounting()
        self.apply(self.request('close_attention', aid))
        self.assertEqual(self.master()['app_status'], 'PROGRAMADO')
        self.assertFalse(closure_check(self.db, self.sid)[0])
        self.assertIn('CIERRE ADMINISTRATIVO', closure_check(self.db, self.sid)[1])
        reception._refresh_manual_accounting_status(self.db, self.sid, 'qa.sync', close_when_complete=True)
        reception._refresh_accounting_summary(self.db, self.sid, 'qa.sync', 'qa.xlsx')
        self.db.commit()
        reception.init_reception_schema(self.db)
        self.assertEqual(self.master()['app_status'], 'PROGRAMADO')
        self.assertEqual(self.rows('reception_attentions')[0]['condition_status'], CONDITION)
        self.assertEqual(self.rows('reception_lines')[0]['received_qty'], 3)

    def test_closed_master_and_retired_record_survive_init(self):
        for action, expected in (('close_bl', CONDITION), ('retire_test', 'REGISTRO DE PRUEBA RETIRADO')):
            with self.subTest(action=action):
                result = self.apply(self.request(action))
                self.db.commit()
                reception.init_reception_schema(self.db)
                self.assertEqual(self.master()['app_status'], 'CERRADO')
                self.assertEqual(self.master()['condition_status'], expected)
                if action == 'close_bl':
                    self.sid = self.shipment('QA-RETIRE')
                self.assertFalse(result['unchanged'])

    def test_attention_closure_survives_actual_source_and_accounting_import_and_init(self):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.title = 'COMPRADOR QA'
        sheet.append(['GUIA DE IMPORTACION', 'CODIGO', 'PEDIDO TRITON', 'OV', 'CANTIDAD SOLICITADA'])
        sheet.append(['QA-ADMIN-CLOSURE', 'NP-QA', 'IP-QA', 'OV-QA', 3])
        reception.import_reception_workbook(self.db, book, 'qa.xlsx', 'qa.sync', ADMIN)
        aid = self.attention()
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=3,np_scanned_at=?', (STAMP,))
        reception._sync_reception_line_totals(self.db, self.sid)
        self.apply(self.request('close_attention', aid))
        accounting = Workbook()
        self.addCleanup(accounting.close)
        sheet = accounting.active
        sheet.title = reception.ACCOUNTING_SHEET_NAME
        sheet.append(['AWB', 'IP', 'FACTURA RESERVA', 'ENTRADA DE MERCANCIA',
                      'FECHA DE RECEPCION', 'FECHA DE EM'])
        sheet.append(['QA-ADMIN-CLOSURE', 'IP-QA', 'FR-QA', 'EM-QA', '2026-10-20', '2026-10-20'])
        reception.import_reception_accounting_workbook(self.db, accounting, 'qa-accounting.xlsx', 'qa.sync', ADMIN)
        reception.import_reception_workbook(self.db, book, 'qa.xlsx', 'qa.sync', ADMIN)
        self.db.commit()
        reception.init_reception_schema(self.db)
        self.assertEqual(self.master()['app_status'], 'PROGRAMADO')
        self.assertEqual(self.master()['accounting_status'], 'EM REGISTRADA')
        self.assertFalse(closure_check(self.db, self.sid)[0])
        self.assertEqual(self.rows('reception_attentions')[0]['condition_status'], CONDITION)
        self.assertEqual(self.rows('reception_lines')[0]['received_qty'], 3)

    def test_accounting_refresh_after_partial_admin_closure_preserves_unreceived_zero(self):
        self.line(expected=3, received=3, ip='IP-QA-RECEIVED')
        self.line(expected=7, received=0, ip='IP-QA-RECEIVED')
        aid = self.attention()
        self.db.execute('''UPDATE reception_attention_lines SET verified_qty=3,np_scanned_at=?
            WHERE reception_line_id=(SELECT MIN(id) FROM reception_lines)''', (STAMP,))
        self.accounting('IP-QA-RECEIVED')
        self.apply(self.request('close_attention', aid))
        before = self.rows('reception_lines')
        reception._refresh_accounting_summary(self.db, self.sid, 'qa.sync', 'qa.xlsx')
        self.assertEqual([r['received_qty'] for r in self.rows('reception_lines')], [3, 0])
        self.assertEqual(self.rows('reception_lines'), before)
        self.assertNotEqual(self.master()['app_status'], 'CERRADO')

    def test_legacy_master_close_preserves_zero_quantities_through_startup_migration(self):
        self.line(expected=8)
        self.db.execute('''UPDATE reception_shipments SET physical_initialized=0,
            system_quantities_initialized=0,app_status='REVISION SISTEMA' ''')
        self.apply()
        self.db.commit()
        reception.init_reception_schema(self.db)
        self.assertEqual(self.rows('reception_lines')[0]['received_qty'], 0)
        self.assertEqual(self.master()['condition_status'], CONDITION)

    def test_retirement_rejects_unexplained_legacy_physical_dates(self):
        self.db.execute("UPDATE reception_shipments SET first_arrival_at=?,app_status='ARRIBADO'", (STAMP,))
        self.assertFalse(self.preview()['can_retire_test'])

    def test_attention_closure_requires_selected_nonannulled_positive_receipt(self):
        self.assertFalse(self.preview()['can_close_attention'])
        with self.assertRaises(ValueError):
            self.apply(self.request('close_attention'))
        aid = self.attention(packages=0)
        self.assertFalse(self.preview(aid)['can_close_attention'])
        with self.assertRaises(ValueError):
            self.apply(self.request('close_attention', aid))
        self.db.execute('UPDATE reception_receipts SET received_packages=1')
        self.db.execute("UPDATE reception_attentions SET condition_status='ANULADA PRUEBA RETIRADA'")
        self.assertFalse(self.preview(aid)['can_close_attention'])
        with self.assertRaises(ValueError):
            self.apply(self.request('close_attention', aid))
        self.db.execute("UPDATE reception_attentions SET condition_status='EN PROCESO',receipt_id=NULL")
        self.assertFalse(self.preview(aid)['can_close_attention'])

    def test_reconcile_uses_ordinary_proof_and_does_not_claim_exception(self):
        self.line(expected=3, received=3)
        aid = self.attention(status='CERRADO')
        self.accounting()
        self.db.execute("UPDATE reception_shipments SET app_status='ARRIBADO'")
        self.db.execute("UPDATE reception_attentions SET condition_status='COMPLETADO' WHERE id=?", (aid,))
        self.assertTrue(self.preview()['can_reconcile'])
        result = self.apply(self.request('reconcile', acknowledge_unverified=False))
        self.assertEqual(result['condition_status'], 'COMPLETADO')
        self.assertEqual(self.master()['app_status'], 'CERRADO')

    def test_reconcile_rejects_incomplete_accounting_and_administrative_attention(self):
        self.line(expected=3, received=3)
        aid = self.attention(status='CERRADO')
        self.db.execute("UPDATE reception_shipments SET app_status='ARRIBADO'")
        with self.assertRaises(ValueError):
            self.apply(self.request('reconcile'))
        self.accounting()
        self.db.execute('UPDATE reception_attentions SET condition_status=? WHERE id=?', (CONDITION, aid))
        eligible, reason = closure_check(self.db, self.sid, allow_documentary=True)
        self.assertFalse(eligible)
        self.assertIn('CIERRE ADMINISTRATIVO', reason)
        with self.assertRaises(ValueError):
            self.apply(self.request('reconcile'))
        self.assertTrue(self.preview()['can_close_bl'])
        self.assertEqual(self.apply()['condition_status'], CONDITION)

    def test_reconcile_documentary_history_uses_validated_basis_and_preserves_zero_on_init(self):
        self.line(expected=8)
        self.accounting()
        self.db.execute('UPDATE reception_shipments SET physical_initialized=0,system_quantities_initialized=0')
        preview = self.preview()
        self.assertTrue(preview['can_reconcile'])
        self.assertIn('Historico documental', preview['reconcile_basis'])
        self.assertIn('sin inventar recepcion fisica', preview['reconcile_basis'])
        result = self.apply(self.request('reconcile', acknowledge_unverified=False))
        self.assertEqual(result['condition_status'], 'COMPLETADO')
        self.db.commit()
        reception.init_reception_schema(self.db)
        self.assertEqual(self.rows('reception_lines')[0]['received_qty'], 0)
        self.assertEqual(self.rows('reception_receipts'), [])
        self.assertEqual(self.master()['app_status'], 'CERRADO')

    def test_retire_empty_phantom_without_manufacturing_fulfillment(self):
        self.assertTrue(self.preview()['can_retire_test'])
        result = self.apply(self.request('retire_test', acknowledge_unverified=False))
        self.assertEqual(result['condition_status'], 'REGISTRO DE PRUEBA RETIRADO')
        self.assertEqual(self.rows('reception_lines'), [])
        self.assertEqual(self.rows('reception_receipts'), [])
        self.assertEqual(self.master()['received_packages'], 0)

    def test_retire_accepts_only_old_annulled_zero_pilot_and_preserves_it(self):
        self.truck('CANCELADA', cancelled_pilot=True)
        self.manifest()
        aid = self.attention(status='CERRADO', packages=0, guide='QA-TRUCK')
        self.db.execute("UPDATE reception_attentions SET condition_status='ANULADA PRUEBA RETIRADA' WHERE id=?", (aid,))
        self.db.execute("UPDATE reception_shipments SET app_status='PROGRAMADO',truck_guide='QA-TRUCK'")
        before = self.rows('reception_attentions'), self.rows('reception_receipts')
        self.assertTrue(self.preview()['can_retire_test'])
        self.apply(self.request('retire_test'))
        self.assertEqual(before, (self.rows('reception_attentions'), self.rows('reception_receipts')))

    def test_only_proven_annulled_zero_pilot_can_retain_temporary_location_when_retired(self):
        self.truck('CANCELADA', cancelled_pilot=True)
        self.manifest()
        aid = self.attention(status='CERRADO', packages=0, guide='QA-TRUCK')
        self.db.execute('''UPDATE reception_attentions SET condition_status='ANULADA PRUEBA RETIRADA',
            location_text='QA-OLD-TEMP' WHERE id=?''', (aid,))
        self.db.execute('''UPDATE reception_shipments SET app_status='PROGRAMADO',
            truck_guide='QA-TRUCK',location_text='QA-OLD-TEMP' ''')
        self.assertTrue(self.preview()['can_retire_test'])
        for sql in (
                'UPDATE reception_receipts SET received_packages=1',
                'UPDATE reception_shipments SET bultos_closed=1',
                'UPDATE reception_shipments SET transfer_assistant_checked=1',
                "UPDATE reception_attentions SET condition_status='EN PROCESO'",
                "UPDATE reception_truck_guides SET archived_at=NULL",
                "UPDATE reception_truck_guides SET archive_reason='cancelado sin procedencia'",
                "UPDATE reception_truck_guides SET guide_status='PENDIENTE'"):
            self.db.execute('SAVEPOINT qa_pilot_guard')
            self.db.execute(sql)
            with self.subTest(sql=sql):
                self.assertFalse(self.preview()['can_retire_test'])
            self.db.execute('ROLLBACK TO qa_pilot_guard')
            self.db.execute('RELEASE qa_pilot_guard')
        preserved = {table: self.rows(table) for table in (
            'reception_receipts', 'reception_attentions', 'reception_truck_guides')}
        self.apply(self.request('retire_test'))
        self.assertEqual(self.master()['location_text'], 'QA-OLD-TEMP')
        for table, rows in preserved.items():
            self.assertEqual(self.rows(table), rows)

    def test_unproven_temporary_location_alone_blocks_retirement(self):
        self.db.execute("UPDATE reception_shipments SET location_text='QA-TEMP'")
        self.assertFalse(self.preview()['can_retire_test'])

    def test_retirement_rejects_source_accounting_positive_receipt_lot_and_live_scan(self):
        mutations = (
            lambda: self.line(expected=0), lambda: self.accounting(), lambda: self.attention(),
            lambda: self.db.execute("UPDATE reception_shipments SET received_packages=1"),
            lambda: self.db.execute("UPDATE reception_shipments SET transfer_assistant_checked=1"),
            lambda: self.db.execute("UPDATE reception_shipments SET fr_number='FR-QA'"),
            lambda: self.db.execute('''INSERT INTO inventory_lots
                (lot_code,bl_awb,item_key,item_code,created_by,created_at,updated_at)
                VALUES ('QA-LOT','qa-admin-closure','QA','NP-QA','qa','qa','qa')'''),
            lambda: self.transfer(status='CONFIRMED'),
        )
        for index, mutate in enumerate(mutations):
            self.db.execute('SAVEPOINT qa_retirement')
            mutate()
            with self.subTest(case=index):
                preview = self.preview()
                self.assertFalse(preview['can_retire_test'])
                self.assertTrue(preview['retire_blocker'])
                before = list(self.db.iterdump())
                with self.assertRaises(ValueError):
                    self.apply(self.request('retire_test'))
                self.assertEqual(before, list(self.db.iterdump()))
            self.db.execute('ROLLBACK TO qa_retirement')
            self.db.execute('RELEASE qa_retirement')
        self.truck('CANCELADA', cancelled_pilot=True)
        self.db.execute('''INSERT INTO reception_truck_package_scans
            (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
            VALUES ('QA-TRUCK',?,'QA-PIECE','QA-PIECE','qa',?)''', (self.sid, STAMP))
        self.assertFalse(self.preview()['can_retire_test'])

    def test_zero_receipt_or_annulment_without_archived_test_provenance_is_not_safe_retirement(self):
        aid = self.attention(status='CERRADO', packages=0)
        self.db.execute("UPDATE reception_attentions SET condition_status='ANULADA' WHERE id=?", (aid,))
        self.db.execute("UPDATE reception_shipments SET app_status='PROGRAMADO'")
        self.assertFalse(self.preview()['can_retire_test'])

    def test_active_unsaved_truck_intake_blocks_all_actions(self):
        self.truck()
        self.manifest()
        result = self.preview()
        for flag in ('can_reconcile', 'can_retire_test', 'can_close_bl', 'can_close_attention'):
            self.assertFalse(result[flag])
        self.assertIn('CAMION', result['close_bl_blocker'].upper())
        before = list(self.db.iterdump())
        for action in ('reconcile', 'retire_test', 'close_bl'):
            with self.assertRaises(ValueError):
                self.apply(self.request(action))
            self.assertEqual(before, list(self.db.iterdump()))

    def test_saved_truck_arrival_is_not_an_unfinished_intake(self):
        self.truck('LISTA_PARA_CONTEO')
        self.manifest()
        aid = self.attention(guide='QA-TRUCK')
        self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES ('QA-TRUCK',?,1,'qa-arrival','qa',?)''', (self.sid, STAMP))
        self.assertTrue(self.preview(aid)['can_close_attention'])
        self.assertEqual(self.apply(self.request('close_attention', aid))['condition_status'], CONDITION)

    def test_old_positive_arrival_does_not_bypass_current_unfinished_truck_header(self):
        self.truck('LISTA_PARA_CONTEO')
        self.manifest()
        aid = self.attention(guide='QA-TRUCK')
        self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES ('QA-TRUCK',?,1,'qa-old-arrival','qa',?)''', (self.sid, STAMP))
        for status in ('PENDIENTE', 'EN_CURSO', 'ZONA_RECEPCION'):
            self.db.execute('UPDATE reception_truck_guides SET guide_status=?', (status,))
            with self.subTest(status=status):
                self.assertFalse(self.preview(aid)['can_close_attention'])
                self.assertFalse(self.preview()['can_close_bl'])
                with self.assertRaises(ValueError):
                    self.apply(self.request('close_attention', aid))

    def test_transfer_revocation_is_scoped_audited_and_keeps_confirmed_requests(self):
        first = self.attention()
        second = self.attention()
        self.transfer(first)
        self.transfer(second)
        self.transfer(0, 'PENDING')
        self.transfer(first, 'CONFIRMED')
        before_confirmed = self.rows('reception_transfer_requests')[-1]
        self.apply(self.request('close_attention', first))
        rows = self.rows('reception_transfer_requests')
        self.assertEqual([r['status'] for r in rows], ['REVOKED', 'ACCEPTED', 'PENDING', 'CONFIRMED'])
        self.assertIsNone(rows[0]['token_hash'])
        self.assertEqual(rows[-1], before_confirmed)
        revocations = [r for r in self.rows('reception_history') if r['field_name'].startswith('transfer_request:')]
        self.assertEqual(len(revocations), 1)
        self.assertEqual(revocations[0]['new_value'], 'REVOKED')
        self.apply()
        self.assertEqual([r['status'] for r in self.rows('reception_transfer_requests')],
                         ['REVOKED', 'REVOKED', 'REVOKED', 'CONFIRMED'])
        self.assertEqual(self.rows('reception_notifications'), [])
        self.assertEqual(self.master()['transfer_assistant_checked'], 0)

    def test_same_request_retry_after_commit_or_reconnect_is_idempotent_without_duplicate_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'qa.sqlite'
            self.db.commit()
            disk = sqlite3.connect(target)
            self.db.backup(disk)
            disk.row_factory = sqlite3.Row
            data = self.request()
            first = service.apply_closure(disk, self.sid, data, 'qa.admin', ADMIN)
            disk.commit()
            count = disk.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
            disk.close()
            disk = sqlite3.connect(target)
            disk.row_factory = sqlite3.Row
            try:
                retry = service.apply_closure(disk, self.sid, data, 'qa.admin', ADMIN)
                self.assertEqual(retry, {**first, 'unchanged': True})
                self.assertEqual(disk.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0], count)
                with self.assertRaises(ValueError):
                    service.apply_closure(disk, self.sid, {**data, 'reason': 'Another confirmed request'}, 'qa.admin', ADMIN)
            finally:
                disk.close()

    def test_repeated_requests_are_idempotent_for_every_action(self):
        for action in ('retire_test', 'close_attention', 'reconcile'):
            self.db.execute('SAVEPOINT qa_retry')
            aid = None
            if action != 'retire_test':
                self.line(expected=3, received=3)
                aid = self.attention(status='CERRADO' if action == 'reconcile' else 'REVISION SISTEMA')
                self.db.execute("UPDATE reception_shipments SET app_status='ARRIBADO'")
                if action == 'reconcile':
                    self.accounting()
            data = self.request(action, aid)
            first = self.apply(data)
            before = list(self.db.iterdump())
            self.assertEqual(self.apply(data), {**first, 'unchanged': True})
            self.assertEqual(before, list(self.db.iterdump()))
            self.db.execute('ROLLBACK TO qa_retry')
            self.db.execute('RELEASE qa_retry')

    def test_retry_cannot_reapply_after_reopening_or_later_data_changes(self):
        data = self.request()
        self.apply(data)
        self.db.execute("UPDATE reception_shipments SET app_status='ARRIBADO'")
        with self.assertRaises(ValueError):
            self.apply(data)
        self.assertEqual(self.master()['app_status'], 'ARRIBADO')

    def test_stale_receipt_cannot_reopen_an_administrative_closure(self):
        self.db.execute("UPDATE reception_shipments SET current_assistant='qa.worker' WHERE id=?", (self.sid,))
        for action in ('close_bl', 'retire_test'):
            self.db.execute('SAVEPOINT qa_closed_receipt')
            self.apply(self.request(action))
            before = list(self.db.iterdump())
            for username, role in (('qa.worker', 'ASISTENTE_RECEPCION'), ('qa.admin', ADMIN)):
                with self.subTest(action=action, role=role), self.assertRaisesRegex(PermissionError, 'reabrir'):
                    reception.add_physical_receipt(self.db, self.sid,
                        {'received_packages': 1}, username, role)
                self.assertEqual(before, list(self.db.iterdump()))
            self.db.execute('ROLLBACK TO qa_closed_receipt')
            self.db.execute('RELEASE qa_closed_receipt')

    def test_receipt_is_available_after_an_explicit_admin_reopening(self):
        self.apply(self.request('retire_test'))
        reception.rewind_reception_stage(self.db, self.sid,
            {'status': 'PROGRAMADO', 'reason': 'Explicit reopening for synthetic QA'}, 'qa.admin', ADMIN)
        reception.add_physical_receipt(self.db, self.sid, {'received_packages': 1}, 'qa.admin', ADMIN)
        self.assertEqual(self.master()['app_status'], 'ARRIBADO')
        self.assertEqual(self.master()['received_packages'], 1)

    def test_ordinary_receipt_reserves_writer_before_reading_closure_state(self):
        self.db.commit()
        statements = []
        self.db.set_trace_callback(statements.append)
        try:
            reception.add_physical_receipt(self.db, self.sid,
                {'received_packages': 1}, 'qa.admin', ADMIN)
        finally:
            self.db.set_trace_callback(None)
        self.assertEqual(statements[0].upper(), 'BEGIN IMMEDIATE')

    def test_snapshot_detects_changes_even_when_updated_at_is_unchanged(self):
        lid = self.line()
        aid = self.attention()
        self.truck('LISTA_PARA_CONTEO')
        self.manifest()
        ref = self.accounting()
        self.transfer(aid)
        changes = (
            ("UPDATE reception_lines SET received_qty=2 WHERE id=?", (lid,)),
            ("UPDATE reception_lines SET np_scanned_at=? WHERE id=?", (STAMP, lid)),
            ("UPDATE reception_attention_lines SET verified_qty=2 WHERE attention_id=?", (aid,)),
            ("UPDATE reception_receipts SET received_packages=2 WHERE shipment_id=?", (self.sid,)),
            ("UPDATE reception_accounting_refs SET ip_reference='P-QA' WHERE id=?", (ref,)),
            ("UPDATE reception_truck_guides SET guide_status='EN_CURSO' WHERE guide_code='QA-TRUCK'", ()),
            ("UPDATE reception_transfer_requests SET status='CONFIRMED' WHERE attention_id=?", (aid,)),
            ("UPDATE reception_shipments SET validation_sample_json='[99]' WHERE id=?", (self.sid,)),
        )
        for sql, params in changes:
            data = self.request('close_attention', aid)
            self.db.execute('SAVEPOINT qa_stale')
            self.db.execute(sql, params)
            before = list(self.db.iterdump())
            with self.subTest(sql=sql), self.assertRaisesRegex(ValueError, 'cambio|vigente'):
                self.apply(data)
            self.assertEqual(before, list(self.db.iterdump()))
            self.db.execute('ROLLBACK TO qa_stale')
            self.db.execute('RELEASE qa_stale')

    def test_token_binds_explicit_attention_and_requests_do_not_choose_one_implicitly(self):
        first, second = self.attention(), self.attention()
        data = self.request('close_attention', first)
        self.assertNotEqual(data['token'], self.preview(second)['token'])
        with self.assertRaises(ValueError):
            self.apply({**data, 'attention_id': second})

    def test_write_lock_precedes_first_read_and_success_remains_in_callers_transaction(self):
        data = self.request()
        self.db.commit()
        statements = []
        self.db.set_trace_callback(statements.append)
        try:
            self.apply(data)
        finally:
            self.db.set_trace_callback(None)
        self.assertEqual(statements[0].upper(), 'BEGIN IMMEDIATE')
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.master()['app_status'], 'PROGRAMADO')
        self.assertEqual(self.rows('reception_history'), [])

    def test_audit_failure_rolls_back_status_and_transfer_revocations_preserving_outer_work(self):
        self.transfer()
        self.db.executescript('''CREATE TRIGGER qa_fail_audit BEFORE INSERT ON reception_history
            WHEN NEW.field_name='admin_closure_request'
            BEGIN SELECT RAISE(ABORT,'QA audit failure'); END;''')
        self.db.execute("UPDATE reception_shipments SET supplier='outer work'")
        data = self.request()
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'QA audit failure'):
            self.apply(data)
        self.assertEqual(before, list(self.db.iterdump()))
        self.assertTrue(self.db.in_transaction)

    def test_two_connections_cannot_apply_a_stale_preview_after_another_writer_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'qa.sqlite'
            self.db.commit()
            writer = sqlite3.connect(path)
            self.db.backup(writer)
            reader = sqlite3.connect(path, timeout=0.05)
            reader.row_factory = writer.row_factory = sqlite3.Row
            try:
                token = service.preview_closure(reader, self.sid, 'qa.admin', ADMIN)['token']
                writer.execute('BEGIN IMMEDIATE')
                writer.execute("UPDATE reception_shipments SET supplier='concurrent change' WHERE id=?", (self.sid,))
                data = {**self.request(), 'token': token}
                with self.assertRaises(sqlite3.OperationalError):
                    service.apply_closure(reader, self.sid, data, 'qa.admin', ADMIN)
                writer.commit()
                with self.assertRaisesRegex(ValueError, 'cambio|vigente'):
                    service.apply_closure(reader, self.sid, data, 'qa.admin', ADMIN)
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0], 0)
            finally:
                writer.close()
                reader.close()


if __name__ == '__main__':
    unittest.main()
