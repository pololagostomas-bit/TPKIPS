"""Current OV replaces COT on each unchanged, anchored source row."""
from io import BytesIO
import unittest
from openpyxl import load_workbook
from backend import app
from backend.services import reception as r
from tests import test_reception_import_ov_revision as fixtures


class BatchOVRevisionTests(unittest.TestCase):
    setUp=fixtures.ImportOVRevisionTests.setUp
    load=fixtures.ImportOVRevisionTests.load
    workbook=fixtures.ImportOVRevisionTests.workbook
    rows=fixtures.ImportOVRevisionTests.rows

    def seed(self):
        self.load(self.workbook([('54321','COT 100','QA-IP'),('54321','COT 200','QA-IP')]))
        before=self.rows()
        with app.db() as c:
            c.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA',received_packages=1")
            shipment=c.execute('SELECT * FROM reception_shipments').fetchone()
            attention=r._create_reception_attention(c,shipment,None,'qa.admin','REVISION SISTEMA')
            for index,line in enumerate(before,1):
                c.execute('''UPDATE reception_attention_lines SET verified_qty=?,np_quantity_saved=1,
                    final_location=?,count_location_saved=1,np_scanned_at='2026-11-27T08:00:00',
                    np_scanned_by='qa.admin' WHERE reception_line_id=?''',(index,'QA-BIN-'+str(index),line['id']))
            physical=[tuple(row) for row in c.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        return before,attention['id'],physical

    def test_two_cot_rows_become_two_real_ovs_preserving_individual_work_and_export(self):
        before,aid,physical=self.seed()
        book=self.workbook([('54321','159001','QA-IP'),('54321','159002','QA-IP')])
        for _ in range(2):
            self.load(book)
            self.assertEqual([(row['id'],row['ov_number']) for row in self.rows()],
                             [(before[0]['id'],'159001'),(before[1]['id'],'159002')])
        with app.db() as c:
            self.assertEqual([tuple(row) for row in c.execute('SELECT * FROM reception_attention_lines ORDER BY id')],physical)
            detail=r.reception_detail(c,before[0]['shipment_id'],attention_id=aid)
            self.assertEqual([(line['ov_number'],line['attention_verified_qty'],line['final_location']) for line in detail['lines']],
                             [('159001',1,'QA-BIN-1'),('159002',2,'QA-BIN-2')])
            changes=[tuple(row) for row in c.execute("SELECT old_value,new_value FROM reception_history WHERE field_name LIKE '%:ov_number' ORDER BY id")]
            self.assertEqual(changes,[('COT 100','159001'),('COT 200','159002')])
            data=r.reception_operational_report_bytes(c,before[0]['shipment_id'],attention_id=aid)
        exported=load_workbook(BytesIO(data),data_only=True)
        try:self.assertEqual([(row[4],row[6]) for row in exported['Packing List SAP'].iter_rows(min_row=2,values_only=True)],
                             [('159001',1),('159002',2)])
        finally:exported.close()

    def test_one_quote_unchanged_is_reserved_before_other_row_becomes_real(self):
        before,_,_=self.seed()
        self.load(self.workbook([('54321','COT 100','QA-IP'),('54321','159002','QA-IP')]))
        self.assertEqual([(row['id'],row['ov_number']) for row in self.rows()],
                         [(before[0]['id'],'COT 100'),(before[1]['id'],'159002')])

    def test_new_ovs_may_have_same_number_but_distinct_rows_are_not_collapsed(self):
        before,_,_=self.seed()
        self.load(self.workbook([('54321','159001','QA-IP'),('54321','159001','QA-IP')]))
        self.assertEqual([(row['id'],row['ov_number']) for row in self.rows()],[(line['id'],'159001') for line in before])

    def test_row_moves_missing_rows_or_changed_quantity_do_not_guess_multiple_matches(self):
        self.seed();before=self.rows()
        for kind in ['moved','missing','quantity','description','blank_anchor']:
            with self.subTest(kind=kind):
                book=self.workbook([('54321','159001','QA-IP'),('54321','159002','QA-IP')])
                if kind=='moved':book.active.insert_rows(2,3)
                if kind=='missing':book.active.delete_rows(3)
                if kind=='quantity':book.active.cell(2,6,9)
                if kind=='description':
                    book.active.cell(1,7,'DESCRIPCION');book.active.cell(2,7,'Different part')
                if kind=='blank_anchor':book.active.cell(2,3,'')
                with self.assertRaises(ValueError):self.load(book)
                self.assertEqual(self.rows(),before)

    def test_same_rows_are_not_enough_for_other_ip_or_oc_or_real_prior_order(self):
        for column,value in [(3,'QA-OTHER-IP'),(5,'65432')]:
            with self.subTest(column=column):
                self.setUp();self.seed();before=self.rows()
                book=self.workbook([('54321','159001','QA-IP'),('54321','159002','QA-IP')])
                for row in (2,3):book.active.cell(row,column,value)
                self.load(book)
                self.assertEqual([row['ov_number'] for row in self.rows() if row['id'] in {line['id'] for line in before}],['COT 100','COT 200'])
        self.setUp();self.seed();before=self.rows()
        with app.db() as c:c.execute("UPDATE reception_lines SET ov_number='158001' WHERE id=?",(before[0]['id'],))
        snapshot=self.rows()
        with self.assertRaises(ValueError):self.load(self.workbook([('54321','159001','QA-IP'),('54321','159002','QA-IP')]))
        self.assertEqual(self.rows(),snapshot)

    def test_two_changed_cot_numbers_are_not_new_real_ovs(self):
        self.seed();before=self.rows()
        with self.assertRaises(ValueError):self.load(self.workbook([('54321','COT 300','QA-IP'),('54321','COT 400','QA-IP')]))
        self.assertEqual(self.rows(),before)
