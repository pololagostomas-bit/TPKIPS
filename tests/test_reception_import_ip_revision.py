"""Mutable IP revisions on synthetic workbooks; no operating records."""
import unittest

from backend import app
from backend.services import reception
from tests import test_reception_import_identity as fixtures


class ImportIPRevisionTests(unittest.TestCase):
    setUp = fixtures.ImportLineIdentityTests.setUp
    load = fixtures.ImportLineIdentityTests.load
    workbook = fixtures.ImportLineIdentityTests.workbook
    rows = fixtures.ImportLineIdentityTests.rows

    def test_ip_edit_keeps_line_id_and_audits_change_once(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-OLD')]))
        before = self.rows()[0]
        for _ in range(2):
            result = self.load(self.workbook([('54321', 'OV-1', 'IP-NEW')]))
            self.assertEqual((result['lines_created'], result['lines_updated']), (0, 1))
            self.assertEqual([(r['id'], r['ip_reference']) for r in self.rows()], [(before['id'], 'IP-NEW')])
        with app.db() as connection:
            changes = connection.execute('SELECT old_value,new_value FROM reception_history WHERE field_name=?',
                                         (f"linea:{before['id']}:ip_reference",)).fetchall()
        self.assertEqual([tuple(row) for row in changes], [('IP-OLD', 'IP-NEW')])

    def test_ip_edit_is_not_inferred_by_excel_position(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-OLD')]))
        before = self.rows()[0]['id']
        book = self.workbook([('54321', 'OV-1', 'IP-NEW')])
        book.active.insert_rows(2, amount=7)
        self.load(book)
        self.assertEqual([(r['id'], r['source_row']) for r in self.rows()], [(before, 9)])

    def test_stock_rows_use_stable_oc_and_keep_legitimate_oc_orders_separate(self):
        self.load(self.workbook([('54321', 'S/N', 'IP-OLD'), ('65432', 'S/N', 'IP-OLD')]))
        before = {r['oc_number']: r['id'] for r in self.rows()}
        self.load(self.workbook([('65432', 'S/N', 'IP-NEW-B'), ('54321', 'S/N', 'IP-NEW-A')]))
        self.assertEqual({r['oc_number']: r['id'] for r in self.rows()}, before)

    def test_reserve_exact_and_oc_revisions_before_ip_revisions(self):
        self.load(self.workbook([('PRE-1', 'OV-1', 'IP-A'), ('54321', 'OV-1', 'IP-B'), ('99999', 'OV-2', 'IP-C')]))
        before = {r['oc_number']: r['id'] for r in self.rows()}
        result = self.load(self.workbook([('54321', 'OV-1', 'IP-NEW'), ('77777', 'OV-1', 'IP-A'), ('99999', 'OV-2', 'IP-C')]))
        self.assertEqual(result['lines_created'], 0)
        self.assertEqual({r['oc_number']: r['id'] for r in self.rows()},
                         {'54321': before['54321'], '77777': before['PRE-1'], '99999': before['99999']})

    def test_same_cut_multiple_ips_and_added_order_are_not_a_revision(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A')]))
        old = self.rows()[0]['id']
        result = self.load(self.workbook([('54321', 'OV-1', 'IP-B'), ('54321', 'OV-1', 'IP-A')]))
        self.assertEqual(result['lines_created'], 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(next(r['id'] for r in self.rows() if r['ip_reference'] == 'IP-A'), old)
        self.load(self.workbook([('54321', 'OV-1', 'IP-A'), ('54321', 'OV-1', 'IP-B')]))
        self.assertEqual(len(self.rows()), 2)

    def test_crossed_ip_and_oc_anchors_are_ambiguous_not_reassigned_work(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A'), ('65432', 'OV-1', 'IP-B')]))
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'Actualizacion de IP ambigua'):
            self.load(self.workbook([('54321', 'OV-1', 'IP-B'), ('65432', 'OV-1', 'IP-A')]))
        self.assertEqual(self.rows(), before)

    def test_conflicting_anchor_guard_does_not_depend_on_input_order(self):
        self.load(self.workbook([('11111', 'OV-1', 'IP-A'), ('22222', 'OV-1', 'IP-B'), ('33333', 'OV-1', 'IP-C')]))
        before = self.rows()
        forward = [('22222', 'OV-1', 'IP-A'), ('33333', 'OV-1', 'IP-B'), ('44444', 'OV-1', 'IP-C')]
        for records in (forward, list(reversed(forward))):
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, 'Actualizacion de IP ambigua'):
                self.load(self.workbook(records))
            self.assertEqual(self.rows(), before)

    def test_oc_revision_cannot_consume_another_pending_ip_revision_anchor(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A'), ('54321', 'OV-1', 'IP-B')]))
        before = self.rows()
        forward = [('77777', 'OV-1', 'IP-A'), ('54321', 'OV-1', 'IP-C')]
        for records in (forward, list(reversed(forward))):
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, 'Actualizacion de IP ambigua'):
                self.load(self.workbook(records))
            self.assertEqual(self.rows(), before)

    def test_whitespace_only_ip_normalization_does_not_log_document_revision(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A')]))
        old = self.rows()[0]
        with app.db() as connection:
            connection.execute('UPDATE reception_lines SET ip_reference=? WHERE id=?', (' IP-A ', old['id']))
        for _ in range(2):
            self.load(self.workbook([('54321', 'OV-1', ' IP-A ')]))
        with app.db() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM reception_history WHERE field_name=?',
                             (f"linea:{old['id']}:ip_reference",)).fetchone()[0], 0)
        self.assertEqual(self.rows()[0]['ip_reference'], 'IP-A')

    def test_same_np_in_another_sheet_is_a_distinct_order(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A')]))
        book = self.workbook([('54321', 'OV-1', 'IP-B')])
        book.active.title = 'OTHER BUYER'
        self.assertEqual(self.load(book)['lines_created'], 1)
        self.assertEqual(len(self.rows()), 2)

    def test_ambiguous_ip_changes_fail_before_any_write(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A'), ('54321', 'OV-1', 'IP-B')]))
        before = self.rows()
        with app.db() as connection:
            changes = connection.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
            book = self.workbook([('54321', 'OV-1', 'IP-C'), ('54321', 'OV-1', 'IP-D')])
            self.addCleanup(book.close)
            with self.assertRaisesRegex(ValueError, 'Actualizacion de IP ambigua'):
                reception.import_reception_workbook(connection, book, 'qa.xlsx', 'qa.admin', 'ADMINISTRADOR')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0], changes)
        self.assertEqual(self.rows(), before)

    def test_ip_and_oc_changing_together_or_missing_oc_cannot_guess_identity(self):
        for old_oc, new_oc in [('PRE-1', '54321'), ('', '')]:
            with self.subTest(old_oc=old_oc, new_oc=new_oc):
                self.setUp()
                self.load(self.workbook([(old_oc, 'OV-1', 'IP-A')]))
                before = self.rows()
                with self.assertRaisesRegex(ValueError, 'Actualizacion de IP ambigua'):
                    self.load(self.workbook([(new_oc, 'OV-1', 'IP-B')]))
                self.assertEqual(self.rows(), before)

    def test_different_ov_sheet_bl_and_np_never_reuse_old_line(self):
        for column, value in [(1, 'QA-OTHER-BL'), (2, 'QA-OTHER-NP'), (4, 'OV-OTHER')]:
            with self.subTest(column=column):
                self.setUp()
                self.load(self.workbook([('54321', 'OV-1', 'IP-A')]))
                before = self.rows()[0]['id']
                book = self.workbook([('54321', 'OV-1', 'IP-B')])
                book.active.cell(2, column, value)
                result = self.load(book)
                self.assertEqual(result['lines_created'], 1)
                self.assertEqual(self.rows()[0]['id'], before)

    def test_revision_preserves_frozen_attention_counts_reads_and_locations(self):
        self.load(self.workbook([('54321', 'OV-1', 'IP-A')]))
        old = self.rows()[0]
        with app.db() as connection:
            connection.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA',received_packages=1 WHERE id=?", (old['shipment_id'],))
            shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?', (old['shipment_id'],)).fetchone()
            attention = reception._create_reception_attention(connection, shipment, None, 'qa.admin', 'REVISION SISTEMA')
            connection.execute("""UPDATE reception_attention_lines SET verified_qty=3, np_quantity_saved=1,
                final_location='QA-BIN',count_location_saved=1,np_scanned_at='2026-10-22T12:00:00',
                np_scanned_by='qa.admin' WHERE attention_id=?""", (attention['id'],))
            before = tuple(connection.execute('SELECT * FROM reception_attention_lines WHERE attention_id=?', (attention['id'],)).fetchone())
        book = self.workbook([('54321', 'OV-1', 'IP-B')])
        book.active.cell(2, 6, 9)
        self.load(book)
        self.assertEqual([r['id'] for r in self.rows()], [old['id']])
        self.assertEqual(self.rows()[0]['expected_qty'], 9)
        with app.db() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM reception_attention_lines WHERE attention_id=?', (attention['id'],)).fetchone()), before)
            detail = reception.reception_detail(connection, old['shipment_id'], 'ADMINISTRADOR', 'qa.admin', attention_id=attention['id'])
            self.assertEqual(len(detail['lines']), 1)
            self.assertEqual(detail['lines'][0]['expected_qty'], 5)
            self.assertEqual(detail['lines'][0]['ip_reference'], 'IP-B')


if __name__ == '__main__':
    unittest.main()
