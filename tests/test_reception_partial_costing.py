"""A costed EM belongs to an exact arrival; another source row can stay pending."""
from openpyxl import Workbook
from backend.services import reception, reception_costing as costing
from tests.test_reception_costing import CostingFixture


class PartialCostingTests(CostingFixture):
    def setUp(self):
        super().setUp()
        self.other = self.attention(seq=2)

    def source(self, second_em='', second_cost=''):
        book = Workbook(); sheet = book.active; sheet.title = reception.ACCOUNTING_SHEET_NAME
        sheet.append(['IP','AWB','FACTURA RESERVA','ENTRADA DE MERCANCIA','FECHA DE RECEPCION','FECHA DE EM','FECHA DE COSTEO'])
        sheet.append(['IP260001','QA-COST','QA-FR','70001','2026-10-01','2026-10-02','2026-10-03'])
        sheet.append(['IP260001','QA-COST','QA-FR',second_em,'2026-10-01','2026-10-04' if second_em else '',second_cost])
        reception.import_reception_accounting_workbook(self.db, book, 'qa-facturas.xlsx', 'qa', 'ADMINISTRADOR')
        return list(self.db.execute('SELECT * FROM reception_accounting_refs ORDER BY source_row'))

    def bind(self, reference, attention):
        self.db.execute('UPDATE reception_accounting_ems SET attention_id=? WHERE accounting_ref_id=?', (attention, reference['id']))

    def test_costed_bound_arrival_closes_while_same_fr_future_row_is_pending(self):
        first, second = self.source()
        self.bind(first, self.aid)
        costing.reconcile(self.db, self.sid, 'qa')
        self.assertEqual(self.status(), 'CERRADO')
        self.assertEqual(self.status(self.other), 'SOLICITUD TRANSFERENCIA')
        self.assertEqual(costing.evidence(self.db,self.sid,self.aid)['reference_ids'], [first['id']])
        self.assertFalse(costing.evidence(self.db,self.sid,self.other)['ready'])
        self.assertEqual(self.db.execute('SELECT em_number FROM reception_accounting_refs WHERE id=?', (second['id'],)).fetchone()[0], '')

    def test_each_bound_em_keeps_its_own_source_costing_date(self):
        first, second = self.source('70002', '2026-10-05')
        self.bind(first, self.aid); self.bind(second, self.other)
        costing.reconcile(self.db, self.sid, 'qa')
        self.assertEqual(costing.evidence(self.db,self.sid,self.aid)['costing_date'], '2026-10-03')
        self.assertEqual(costing.evidence(self.db,self.sid,self.other)['costing_date'], '2026-10-05')

    def test_unassigned_source_em_never_guesses_which_arrival_it_covers(self):
        self.source()
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])
        self.assertFalse(costing.evidence(self.db,self.sid,self.other)['ready'])

    def test_invalid_bound_date_does_not_borrow_another_valid_cost(self):
        first, second = self.source('70002', '2026-10-05')
        self.bind(first, self.aid); self.bind(second, self.other)
        self.db.execute("UPDATE reception_accounting_refs SET costing_date='' WHERE id=?", (first['id'],))
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])

    def test_numeric_trailing_separator_does_not_create_a_second_em(self):
        self.assertEqual(reception._accounting_em_tokens('70001 -'), ['70001'])
        self.assertEqual(reception._accounting_em_tokens('QA-EM'), ['QA-EM'])
        first, _ = self.source()
        self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,ip_reference_key,em_number,em_date,username,created_at) VALUES(?,'IP260001','70001 -','2026-10-02','importacion','2026-10-02')", (first['id'],))
        self.assertEqual(reception._accounting_em_values(self.db,first['id'],'IP260001'), ['70001'])

    def test_withdrawn_current_em_cannot_close_via_its_old_ledger_entry(self):
        first, _ = self.source()
        self.bind(first, self.aid)
        self.db.execute("UPDATE reception_accounting_refs SET em_number='' WHERE id=?", (first['id'],))
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])
