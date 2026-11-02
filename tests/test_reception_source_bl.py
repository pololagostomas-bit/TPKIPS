"""Current documentary BL association is distinct from preserved physical work."""
import unittest
from openpyxl import Workbook
from backend import app
from backend.services import reception
from tests import test_reception_importation_customer as fixtures


class SourceBlTests(unittest.TestCase):
    setUp=fixtures.ImportationCustomerTests.setUp
    load=fixtures.ImportationCustomerTests.load

    def book(self,guide='QA-BL',ip='IP260001',ov='810001'):
        book=Workbook();sheet=book.active;sheet.title='QA-SHEET'
        sheet.append(['GUIA DE IMPORTACION','CODIGO','PEDIDO TRITON','OV','ORDEN DE COMPRA','CANTIDAD SOLICITADA','MODO DE TRANSPORTE'])
        sheet.append([guide,'QA-NP',ip,ov,'83001',5,'AEREO'])
        return book

    def detail(self,guide='QA-BL'):
        with app.db() as c:
            sid=c.execute('SELECT id FROM reception_shipments WHERE bl_awb=?',(guide,)).fetchone()[0]
            return reception.reception_detail(c,sid,'ADMINISTRADOR','qa.admin')

    def test_blank_bl_retires_current_offer_without_deleting_history(self):
        self.load(self.book());line=self.detail()['lines'][0]
        with app.db() as c:c.execute('UPDATE reception_lines SET received_qty=3 WHERE id=?',(line['id'],))
        self.load(self.book(guide='',ip='IP260001-2'))
        current=self.detail()['lines'][0]
        self.assertIs(current.get('source_bl_eligible'),False)
        self.assertEqual(current['source_bl_state'],'NO_BL')
        self.assertEqual(current['id'],line['id'])
        self.assertEqual(current['received_qty'],3)
        self.assertEqual(self.detail()['np_progress']['total'],0)

    def test_other_bl_is_not_reassigned_or_given_old_count(self):
        self.load(self.book())
        with app.db() as c:c.execute('UPDATE reception_lines SET received_qty=3')
        self.load(self.book(guide='QA-OTHER'))
        self.assertIs(self.detail()['lines'][0].get('source_bl_eligible'),False)
        other=self.detail('QA-OTHER')['lines'][0]
        self.assertIs(other['source_bl_eligible'],True)
        self.assertEqual(other['received_qty'],0)

    def test_distinct_orders_of_same_np_keep_their_explicit_bl(self):
        book=self.book();book.active.append(['QA-OTHER','QA-NP','IP260002','810001','83001',7,'AEREO'])
        self.load(book)
        self.assertIs(self.detail()['lines'][0].get('source_bl_eligible'),True)
        self.assertIs(self.detail('QA-OTHER')['lines'][0]['source_bl_eligible'],True)

    def test_missing_line_is_not_matched_merely_by_same_np_and_bl(self):
        self.load(self.book())
        self.load(self.book(ip='IP260002',ov='810002'))
        lines=self.detail()['lines']
        old=next(x for x in lines if x['ov_number']=='810001')
        self.assertIs(old.get('source_bl_eligible'),False)
        self.assertEqual(sum(x['source_bl_eligible'] for x in lines),1)

    def test_current_refs_can_protect_existing_install_before_first_new_snapshot(self):
        self.load(self.book())
        from backend.services import reception_source_bl as source
        with app.db() as c:
            c.execute('DELETE FROM reception_source_bl_state');c.execute('DELETE FROM reception_source_bl_rows')
            c.execute("INSERT INTO order_importation_refs(sap_ov,bl_awb,transport_type,ip_reference,oc_number,source_sheet,source_row,item_code,updated_at) VALUES('810001','','SIN DEFINIR','IP260001-2','83001','QA-SHEET',2,'QA-NP','2026-10-01')")
        line=self.detail()['lines'][0]
        self.assertIs(line['source_bl_eligible'],False)
        self.assertEqual(line['source_bl_state'],'NO_BL')

    def test_reorder_does_not_change_membership(self):
        self.load(self.book());before=self.detail()['lines'][0]['id']
        book=self.book();book.active.insert_rows(2)
        self.load(book)
        line=self.detail()['lines'][0]
        self.assertEqual(line['id'],before)
        self.assertIs(line.get('source_bl_eligible'),True)

    def test_partial_ov_map_does_not_withdraw_another_order_of_same_np(self):
        book=self.book();book.active.append(['QA-BL','QA-NP','IP260002','810002','83001',2,'AEREO']);self.load(book)
        with app.db() as c:
            c.execute('DELETE FROM reception_source_bl_state');c.execute('DELETE FROM reception_source_bl_rows')
            c.execute("INSERT INTO order_importation_refs(sap_ov,bl_awb,transport_type,ip_reference,oc_number,source_sheet,source_row,item_code,updated_at) VALUES('810002','','SIN DEFINIR','IP260002','83001','QA-SHEET',3,'QA-NP','2026-10-01')")
        lines=self.detail()['lines']
        self.assertIs(next(l for l in lines if l['ov_number']=='810001')['source_bl_eligible'],True)
        self.assertIs(next(l for l in lines if l['ov_number']=='810002')['source_bl_eligible'],False)
