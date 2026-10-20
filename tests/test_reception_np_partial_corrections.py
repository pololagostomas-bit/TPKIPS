"""NP partial corrections do not alter the physical package ledger."""
import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.services import reception
from backend.services.reception_partial_count import continue_partial_count
from tests import test_reception_partial_count as fixtures


class NpPartialCorrectionTests(unittest.TestCase):
    setUpBase = fixtures.PartialCountTests.setUpBase
    setUp = fixtures.PartialCountTests.setUp
    stock_value = fixtures.PartialCountTests.stock_value
    detail = fixtures.PartialCountTests.detail
    scan = fixtures.PartialCountTests.scan
    partial = fixtures.PartialCountTests.partial

    def defer(self, role='ADMINISTRADOR', **overrides):
        return reception.update_reception_line_quantity(self.db, self.sid, self.lid, {
            'attention_id': self.attention, 'received_qty': 0, 'defer_np': True,
            'confirmed': True, 'previous_received_qty': 8,
            'reason': 'Wrongly included in this arrival; belongs to another receipt', **overrides,
        }, 'receiver', role)

    def test_count_reopening_preserves_zero_partial_and_excess_counts(self):
        self.scan()
        for quantity in (0, 3, 10):
            with self.subTest(quantity=quantity):
                self.db.execute("UPDATE reception_attentions SET app_status='EM' WHERE id=?", (self.attention,))
                self.db.execute('''UPDATE reception_attention_lines SET verified_qty=?,
                    np_unreceived_reason=? WHERE attention_id=? AND reception_line_id=?''',
                    (quantity, 'Absent from this arrival' if quantity == 0 else None, self.attention, self.lid))
                result = reception.rewind_reception_stage(self.db, self.sid,
                    {'attention_id': self.attention, 'status': 'REVISION SISTEMA',
                     'reason': 'Correct this arrival without resetting counts'}, 'receiver', 'ADMINISTRADOR')
                line = next(row for row in result['lines'] if row['id'] == self.lid)
                self.assertEqual(line['attention_verified_qty'], quantity)
                self.assertTrue(line['np_scanned_at'])
                self.assertEqual(bool(line['np_unreceived_reason']), quantity == 0)

    def test_admin_defers_a_saved_read_and_keeps_its_original_evidence(self):
        self.scan()
        before = self.detail()['lines'][0]['np_scanned_at']
        package_rows = [tuple(row) for row in self.db.execute('SELECT * FROM reception_receipts')]
        result = self.defer()
        line = next(row for row in result['lines'] if row['id'] == self.lid)
        self.assertEqual(line['attention_verified_qty'], 0)
        self.assertEqual(line['attention_planned_qty'], 8)
        self.assertEqual(line['np_scanned_at'], before)
        self.assertTrue(line['np_unreceived_reason'].startswith('CORRECCION ADMIN NP:'))
        self.assertEqual(package_rows, [tuple(row) for row in self.db.execute('SELECT * FROM reception_receipts')])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CORRECCION NP'").fetchone()[0], 1)

    def test_invalid_or_stale_or_worker_deferral_does_not_write(self):
        self.scan()
        for role, values, error in (
            ('ASISTENTE_RECEPCION', {}, PermissionError),
            ('ADMINISTRADOR', {'confirmed': False}, ValueError),
            ('ADMINISTRADOR', {'reason': 'short'}, ValueError),
            ('ADMINISTRADOR', {'previous_received_qty': 7}, ValueError),
            ('ADMINISTRADOR', {'received_qty': 1}, ValueError),
            ('ADMINISTRADOR', {'scan_np': True}, ValueError),
            ('ADMINISTRADOR', {'defer_np': 'true'}, ValueError),
        ):
            with self.subTest(role=role, values=values):
                before = list(self.db.iterdump())
                with self.assertRaises(error):
                    self.defer(role, **values)
                self.assertEqual(list(self.db.iterdump()), before)

    def test_unread_np_uses_normal_partial_flow_not_scan_correction(self):
        before = list(self.db.iterdump())
        with self.assertRaises(ValueError):
            self.defer()
        self.assertEqual(before, list(self.db.iterdump()))

    def test_old_scan_retry_cannot_restore_admin_deferred_quantity(self):
        self.scan(); self.defer()
        history = self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        result = self.scan()
        self.assertEqual(next(row for row in result['lines'] if row['id'] == self.lid)['attention_verified_qty'], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0], history)

    def test_only_admin_can_restore_an_admin_deferred_order(self):
        self.scan(); self.defer()
        before = list(self.db.iterdump())
        with self.assertRaises(PermissionError):
            reception.update_reception_line_quantity(self.db, self.sid, self.lid,
                {'attention_id': self.attention, 'received_qty': 8}, 'receiver', 'ASISTENTE_RECEPCION')
        self.assertEqual(before, list(self.db.iterdump()))
        result = reception.update_reception_line_quantity(self.db, self.sid, self.lid,
            {'attention_id': self.attention, 'received_qty': 8, 'reason': 'Physical quantity rechecked'},
            'receiver', 'ADMINISTRADOR')
        line = next(row for row in result['lines'] if row['id'] == self.lid)
        self.assertEqual(line['attention_verified_qty'], 8)
        self.assertFalse(line['np_unreceived_reason'])

    def test_corrected_read_can_finish_partial_with_no_unresolved_ids(self):
        self.scan(); self.scan(self.missing, 2); self.defer()
        received_packages = self.detail()['received_packages']
        result = self.partial(line_ids=[])
        self.assertEqual(result['app_status'], 'EM')
        line = next(row for row in result['lines'] if row['id'] == self.lid)
        self.assertEqual(line['attention_verified_qty'], 0)
        self.assertTrue(line['np_unreceived_reason'])
        self.assertEqual(result['received_packages'], received_packages)
        self.assertEqual(self.partial(line_ids=[])['app_status'], 'EM')

    def test_empty_partial_without_a_deferred_order_or_with_unread_rows_fails(self):
        self.scan()
        with self.assertRaises(ValueError):
            self.partial(line_ids=[])
        self.defer()
        with self.assertRaises(ValueError):
            self.partial(line_ids=[])

    def test_full_worker_save_can_keep_a_protected_row_unchanged(self):
        self.scan(); self.defer()
        line = next(row for row in self.detail()['lines'] if row['id'] == self.lid)
        before = list(self.db.iterdump())
        reception.update_reception_line_quantity(self.db, self.sid, self.lid, {
            'attention_id': self.attention, 'received_qty': 0,
            'reason': line['blocked_reason'], 'count_location': line['final_location'],
        }, 'receiver', 'ASISTENTE_RECEPCION')
        self.assertEqual(list(self.db.iterdump()), before)
        result = reception.update_reception_line_quantity(self.db, self.sid, self.missing,
            {'attention_id': self.attention, 'received_qty': 1}, 'receiver', 'ASISTENTE_RECEPCION')
        self.assertEqual(next(row for row in result['lines'] if row['id'] == self.missing)['attention_verified_qty'], 1)
        self.assertEqual(next(row for row in result['lines'] if row['id'] == self.lid)['attention_verified_qty'], 0)

    def test_worker_noop_cannot_change_protected_reason_location_or_quantity(self):
        self.scan(); self.defer()
        line = next(row for row in self.detail()['lines'] if row['id'] == self.lid)
        for changes in ({'received_qty': 1}, {'reason': 'Worker overwrote the correction'},
                        {'count_location': 'QA-OTHER'}):
            with self.subTest(changes=changes):
                before = list(self.db.iterdump())
                with self.assertRaises(PermissionError):
                    reception.update_reception_line_quantity(self.db, self.sid, self.lid, {
                        'attention_id': self.attention, 'received_qty': 0,
                        'reason': line['blocked_reason'], 'count_location': line['final_location'],
                        **changes,
                    }, 'receiver', 'ASISTENTE_RECEPCION')
                self.assertEqual(list(self.db.iterdump()), before)

    def test_worker_guard_and_write_are_atomic_against_an_admin_correction(self):
        self.scan(); self.db.commit()
        directory = self.enterContext(tempfile.TemporaryDirectory())
        filename = Path(directory) / 'concurrent.sqlite'
        target = sqlite3.connect(filename)
        try:
            self.db.backup(target)
        finally:
            target.close()
        worker = sqlite3.connect(filename, timeout=1)
        admin = sqlite3.connect(filename, timeout=0)
        worker.row_factory = admin.row_factory = sqlite3.Row
        self.addCleanup(worker.close); self.addCleanup(admin.close)
        original_save = reception._save_count_location
        admin_committed = False

        def admin_update():
            reception.update_reception_line_quantity(admin, self.sid, self.lid, {
                'attention_id': self.attention, 'received_qty': 0, 'defer_np': True,
                'confirmed': True, 'previous_received_qty': 8,
                'reason': 'Administrative physical inspection for this delivery',
            }, 'receiver', 'ADMINISTRADOR')
            admin.commit()

        def interleaved_save(connection, *args, **kwargs):
            nonlocal admin_committed
            if connection is worker:
                try:
                    admin_update()
                    admin_committed = True
                except sqlite3.OperationalError:
                    admin.rollback()
            return original_save(connection, *args, **kwargs)

        with patch.object(reception, '_save_count_location', side_effect=interleaved_save):
            reception.update_reception_line_quantity(worker, self.sid, self.lid,
                {'attention_id': self.attention, 'received_qty': 8}, 'receiver', 'ASISTENTE_RECEPCION')
            worker.commit()
        if not admin_committed:
            admin_update()
        quantity, reason = admin.execute('''SELECT verified_qty,np_unreceived_reason
            FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?''',
            (self.attention, self.lid)).fetchone()
        self.assertEqual(quantity, 0, 'A stale worker write must not undo an admin correction')
        self.assertTrue(reason.startswith('CORRECCION ADMIN NP:'))


if __name__ == '__main__':
    unittest.main()
