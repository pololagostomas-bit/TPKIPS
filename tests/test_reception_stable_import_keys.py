"""Synthetic legacy PRE/OC overlap; never move physical work between rows."""
import unittest
from backend import app
from backend.services import reception
from tests import test_reception_import_identity as fixtures


class StableImportKeysTests(unittest.TestCase):
    setUp=fixtures.ImportLineIdentityTests.setUp
    load=fixtures.ImportLineIdentityTests.load
    workbook=fixtures.ImportLineIdentityTests.workbook
    rows=fixtures.ImportLineIdentityTests.rows

    def legacy(self):
        self.load(self.workbook([('54321','S/N',''),('PRE-123','S/N','QA-IP')]))
        rows=self.rows();old,current=rows
        with app.db() as c:
            c.execute('UPDATE reception_lines SET source_row=2,received_qty=5 WHERE id IN (?,?)',(old['id'],current['id']))
        return old['id'],current['id']

    def test_legacy_overlap_updates_internal_id_preserving_physical_rows(self):
        old,current=self.legacy()
        result=self.load(self.workbook([('54321','S/N','QA-IP')]))
        self.assertEqual((result['lines_created'],result['lines_updated']),(0,1))
        rows={r['id']:r for r in self.rows()}
        self.assertEqual(rows[current]['oc_number'],'54321')
        self.assertEqual([(rows[i]['id'],rows[i]['received_qty']) for i in (old,current)],[(old,5),(current,5)])
        with app.db() as c:
            detail=reception.reception_detail(c,rows[current]['shipment_id'],'ADMINISTRADOR','qa.admin')
            shadow=next(r for r in detail['lines'] if r['id']==old)
            self.assertFalse(shadow['source_bl_eligible'])
            self.assertEqual(shadow['source_bl_state'],'SUPERSEDED')
            self.assertTrue(c.execute("SELECT 1 FROM reception_history WHERE event_type='IDENTIDAD DOCUMENTAL'").fetchone())

    def test_previous_reference_and_inserted_rows_keep_internal_id(self):
        self.load(self.workbook([('PRE-123','S/N','QA-IP')]))
        before=self.rows()[0]['id']
        self.load(self.workbook([('54321','S/N','QA-IP')]))
        self.load(self.workbook([('PRE-123','S/N','QA-IP')]))
        book=self.workbook([('77777','S/N','QA-IP')]);book.active.insert_rows(2,4)
        self.load(book)
        self.assertEqual([(r['id'],r['source_row']) for r in self.rows()],[(before,6)])
        with app.db() as c:
            self.assertGreaterEqual(c.execute('SELECT COUNT(*) FROM reception_import_keys WHERE line_id=?',(before,)).fetchone()[0],3)

    def test_simultaneous_old_and_new_references_are_distinct_orders(self):
        self.load(self.workbook([('PRE-123','OV-QA','QA-IP')]))
        self.load(self.workbook([('54321','OV-QA','QA-IP')]))
        current=self.rows()[0]['id']
        self.load(self.workbook([('PRE-123','OV-QA','QA-IP'),('54321','OV-QA','QA-IP')]))
        self.assertEqual(len(self.rows()),2)
        self.assertEqual(next(r['id'] for r in self.rows() if r['oc_number']=='54321'),current)
        self.load(self.workbook([('54321','OV-QA','QA-IP'),('PRE-123','OV-QA','QA-IP')]))
        self.assertEqual(len(self.rows()),2)

    def test_same_row_number_with_different_quantity_is_not_proof(self):
        old,_=self.legacy()
        with app.db() as c:c.execute('UPDATE reception_lines SET expected_qty=9 WHERE id=?',(old,))
        before=self.rows()
        with self.assertRaisesRegex(ValueError,'ambigua'):
            self.load(self.workbook([('54321','S/N','QA-IP')]))
        self.assertEqual(self.rows(),before)

    def test_two_current_orders_do_not_retire_a_legacy_line(self):
        old,current=self.legacy()
        self.load(self.workbook([('54321','S/N',''),('54321','S/N','QA-IP')]))
        self.assertEqual({r['id'] for r in self.rows()},{old,current})
        with app.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM reception_import_legacy').fetchone()[0],0)

    def test_recorded_legacy_reference_returns_to_canonical_row(self):
        old,current=self.legacy()
        self.load(self.workbook([('54321','S/N','QA-IP')]))
        self.load(self.workbook([('54321','S/N','')]))
        self.assertEqual({r['id'] for r in self.rows()},{old,current})
        with app.db() as c:
            detail=reception.reception_detail(c,self.rows()[0]['shipment_id'],'ADMINISTRADOR','qa.admin')
            self.assertFalse(next(r for r in detail['lines'] if r['id']==old)['source_bl_eligible'])

    def test_multiple_incomplete_antecedents_remain_ambiguous(self):
        self.load(self.workbook([('54321','S/N',''),('54321','S/N',''),('PRE-123','S/N','QA-IP')]))
        with app.db() as c:c.execute('UPDATE reception_lines SET source_row=2')
        before=self.rows()
        with self.assertRaisesRegex(ValueError,'ambigua'):
            self.load(self.workbook([('54321','S/N','QA-IP')]))
        self.assertEqual(self.rows(),before)

    def test_revision_does_not_rewrite_attention_read_or_location(self):
        old,current=self.legacy()
        with app.db() as c:
            c.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA',received_packages=1")
            shipment=c.execute('SELECT * FROM reception_shipments').fetchone()
            attention=reception._create_reception_attention(c,shipment,None,'qa','REVISION SISTEMA')
            c.execute("UPDATE reception_attention_lines SET np_scanned_at='2026-11-02T12:00:00',np_scanned_by='qa',verified_qty=3,final_location='QA-BIN',count_location_saved=1 WHERE reception_line_id=?",(current,))
            before=[tuple(r) for r in c.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        self.load(self.workbook([('54321','S/N','QA-IP')]))
        with app.db() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM reception_attention_lines ORDER BY id')],before)

    def test_corrupt_old_key_cannot_reassign_another_np(self):
        self.load(self.workbook([('PRE-123','OV-QA','QA-IP')]))
        first=self.rows()[0]
        self.load(self.workbook([('54321','OV-QA','QA-IP')]))
        book=self.workbook([('55555','OV-OTHER','QA-OTHER-IP')]);book.active.cell(2,2,'QA-OTHER-NP')
        self.load(book);other=self.rows()[-1]
        with app.db() as c:
            c.execute('UPDATE reception_import_keys SET line_id=? WHERE source_key=?',(other['id'],first['source_key']))
        before=self.rows()
        with self.assertRaisesRegex(ValueError,'otro pedido'):
            self.load(self.workbook([('PRE-123','OV-QA','QA-IP')]))
        self.assertEqual(self.rows(),before)
