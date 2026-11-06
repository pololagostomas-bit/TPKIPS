"""Distinct read NP are not the same metric as fully received source orders."""
from io import BytesIO
import unittest

from openpyxl import load_workbook
from backend.services import reception, reception_np_progress
from tests import test_reception_count_locations as fixtures


class NpProgressCounterTests(unittest.TestCase):
    setUp = fixtures.CountLocationTests.setUp
    stock_value = fixtures.CountLocationTests.stock_value

    def test_one_read_counts_once_while_another_order_of_same_np_stays_pending(self):
        other = self.db.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,ov_number,expected_qty) VALUES (?,'NP-QA','OV-2',2)''',
            (self.sid,)).lastrowid
        self.db.execute('''INSERT INTO reception_attention_lines
            (attention_id,reception_line_id,planned_qty,verified_qty) VALUES (?,?,2,0)''',
            (self.attention,other))
        self.db.execute("""UPDATE reception_attention_lines SET verified_qty=8,
            np_scanned_at='2026-11-01T10:00:00',np_quantity_saved=1 WHERE reception_line_id=?""", (self.lid,))
        before = [tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        for reason in ('', reception_np_progress.DEFERRED_REASON):
            with self.subTest(reason=reason):
                self.db.execute('UPDATE reception_attention_lines SET np_unreceived_reason=? WHERE reception_line_id=?',
                    (reason,other))
                payload = {'id':self.sid,'lines':[dict(row) for row in self.db.execute('SELECT * FROM reception_lines')]}
                reception_np_progress.add_progress(self.db,payload,self.attention)
                self.assertEqual(payload['np_progress'], {'read':1,'total':1})
                self.assertEqual(self.db.execute('SELECT verified_qty FROM reception_attention_lines WHERE reception_line_id=?',
                    (other,)).fetchone()[0],0)
        book = load_workbook(BytesIO(reception.reception_operational_report_bytes(
            self.db,self.sid,'ADMINISTRADOR','qa.admin',self.attention)),read_only=True)
        self.addCleanup(book.close)
        received = {row[1] for row in list(book['Packing List SAP'].values)[1:] if row[6]>0}
        self.assertEqual(payload['np_progress']['read'],len(received))
        self.db.execute('UPDATE reception_attention_lines SET np_unreceived_reason=NULL WHERE reception_line_id=?', (other,))
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')],before)

    def test_default_quantity_and_cancelled_reads_do_not_count(self):
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=8 WHERE attention_id=?',(self.attention,))
        payload = {'id':self.sid,'lines':[dict(row) for row in self.db.execute('SELECT * FROM reception_lines')]}
        reception_np_progress.add_progress(self.db,payload,self.attention)
        self.assertEqual(payload['np_progress'], {'read':0,'total':1})
        self.db.execute("UPDATE reception_attention_lines SET np_scanned_at='2026-11-01T10:00:00' WHERE attention_id=?", (self.attention,))
        self.db.execute("UPDATE reception_attentions SET condition_status='ANULADA' WHERE id=?",(self.attention,))
        reception_np_progress.add_progress(self.db,payload,self.attention)
        self.assertEqual(payload['np_progress'], {'read':0,'total':1})
