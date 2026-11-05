"""Automatic absence from an earlier delivery must not label a later read."""
import unittest
from backend.services import reception
from backend.services.reception_partial_count import DEFERRED_REASON
from tests import test_reception_count_locations as fixtures


class CountNoteTests(unittest.TestCase):
    stock_value = fixtures.CountLocationTests.stock_value
    detail = fixtures.CountLocationTests.detail

    def setUp(self):
        fixtures.CountLocationTests.setUp(self)
        self.db.execute('UPDATE reception_lines SET blocked_reason=? WHERE id=?', (DEFERRED_REASON, self.lid))
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=0,np_unreceived_reason=? WHERE attention_id=?',
                        (DEFERRED_REASON, self.attention))
        shipment = self.db.execute('SELECT * FROM reception_shipments WHERE id=?', (self.sid,)).fetchone()
        self.other = reception._create_reception_attention(self.db, shipment, None, 'receiver', 'REVISION SISTEMA')['id']
        self.db.execute("""UPDATE reception_attention_lines SET planned_qty=8,verified_qty=8,
            np_scanned_at='2026-10-13T10:00:00',np_quantity_saved=1 WHERE attention_id=?""", (self.other,))
        reception._sync_reception_line_totals(self.db, self.sid)

    def test_later_read_has_requested_quantity_without_old_absence_note(self):
        before = [tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        line = self.detail(self.other)['lines'][0]
        self.assertEqual(line['attention_verified_qty'], 8)
        self.assertEqual(line['blocked_reason'], '')
        self.assertFalse(line['np_unreceived_reason'])
        self.assertEqual(self.detail(self.other)['np_progress'], {'read': 1, 'total': 1})
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')], before)
        self.assertEqual(self.db.execute('SELECT blocked_reason FROM reception_lines WHERE id=?', (self.lid,)).fetchone()[0], DEFERRED_REASON)

    def test_original_delivery_keeps_its_own_absence(self):
        line = self.detail()['lines'][0]
        self.assertEqual(line['blocked_reason'], DEFERRED_REASON)
        self.assertEqual(line['np_unreceived_reason'], DEFERRED_REASON)
        self.assertEqual(line['attention_verified_qty'], 0)

    def test_human_comment_is_not_silently_removed(self):
        comment = 'Caja danada: validar unidades con el responsable'
        self.db.execute('UPDATE reception_lines SET blocked_reason=? WHERE id=?', (comment, self.lid))
        self.assertEqual(self.detail(self.other)['lines'][0]['blocked_reason'], comment)

    def test_unread_prefill_does_not_reuse_previous_absence_as_current_comment(self):
        self.db.execute('UPDATE reception_attention_lines SET np_scanned_at=NULL,np_quantity_saved=0 WHERE attention_id=?', (self.other,))
        line = self.detail(self.other)['lines'][0]
        self.assertEqual(line['blocked_reason'], '')
        self.assertFalse(line['np_scanned_at'])
        self.assertEqual(self.detail(self.other)['np_progress']['read'], 0)
