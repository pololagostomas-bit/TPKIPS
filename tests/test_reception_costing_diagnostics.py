"""Transfer explanations use the same evidence as automatic closure."""
from unittest.mock import patch

from backend.services import reception_costing as costing
from tests.test_reception_costing import CostingFixture


class CostingDiagnosticTests(CostingFixture):
    def issues(self):
        return costing.evidence(self.db, self.sid, self.aid).get('issues', [])

    def test_missing_ip_identifies_the_uncovered_ip_without_claiming_missing_date(self):
        self.import_cost()
        self.db.execute("UPDATE reception_lines SET ip_reference='IP260002-3'")
        proof = costing.evidence(self.db, self.sid, self.aid)
        self.assertFalse(proof['ready'])
        self.assertEqual([i['code'] for i in proof.get('issues', [])], ['IP_NOT_IN_FACTURAS'])
        self.assertEqual(proof['issues'][0]['ip_reference'], 'IP260002-3')
        self.assertIn('Facturas', proof['issues'][0]['action'])

    def test_missing_documents_and_date_are_explained_together_and_fresh_on_next_read(self):
        self.import_cost(cost='')
        self.db.execute("UPDATE reception_accounting_refs SET fr_number='',em_number=''")
        self.db.execute('DELETE FROM reception_accounting_ems')
        self.assertEqual({i['code'] for i in self.issues()}, {'MISSING_FR', 'MISSING_EM', 'MISSING_COSTING_DATE'})
        self.db.execute("UPDATE reception_accounting_refs SET fr_number='QA-FR',em_number='QA-EM',costing_date='2026-10-03'")
        self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,ip_reference_key,em_number,em_date,username,created_at) SELECT id,'IP260001','QA-EM','2026-10-02','qa','2026-10-02' FROM reception_accounting_refs")
        proof = costing.evidence(self.db, self.sid, self.aid)
        self.assertTrue(proof['ready'])
        self.assertEqual(proof['issues'], [])

    def test_dates_explain_the_exact_rule_and_source_location(self):
        for date, code in [('bad-date', 'INVALID_COSTING_DATE'), ('2026-02-30', 'INVALID_COSTING_DATE'),
                           ('2026-09-30', 'COSTING_BEFORE_ARRIVAL'), ('2099-01-01', 'COSTING_IN_FUTURE'),
                           ('2026-10-01', 'COSTING_BEFORE_EM')]:
            with self.subTest(date=date):
                self.import_cost(cost='')
                self.db.execute('UPDATE reception_accounting_refs SET costing_date=?', (date,))
                issue = next((i for i in self.issues() if i['code'] == code), None)
                self.assertIsNotNone(issue)
                self.assertEqual(issue['source_row'], 2)
                self.assertEqual(issue['source_sheet'], 'FACTURAS IMPORTACIONES Repuesto')
                self.assertTrue(issue['field'])
                self.assertTrue(issue['action'])

    def test_repeated_reference_field_has_one_issue_not_one_per_ip(self):
        self.import_cost(cost='', ip='IP260001, IP260002')
        self.db.execute("UPDATE reception_lines SET ip_reference='IP260001, IP260002'")
        self.assertEqual([i['code'] for i in self.issues()], ['MISSING_COSTING_DATE'])

    def test_structural_causes_are_explained_without_mutation(self):
        for sql, code in [
            ("UPDATE reception_shipments SET accounting_conflict_count=1", 'ACCOUNTING_CONFLICT'),
            ("UPDATE reception_receipts SET received_packages=0", 'MISSING_PHYSICAL_ARRIVAL'),
            ("UPDATE reception_lines SET ip_reference=''", 'MISSING_LINE_IP'),
            ("UPDATE reception_attention_lines SET verified_qty=0", 'NO_RECEIVED_NP'),
            ("UPDATE reception_attentions SET condition_status='ANULADA QA'", 'INACTIVE_ATTENTION'),
        ]:
            with self.subTest(code=code):
                self.db.execute('SAVEPOINT scenario')
                self.db.execute(sql)
                before = self.db.total_changes
                self.assertIn(code, [i['code'] for i in self.issues()])
                self.assertEqual(self.db.total_changes, before)
                self.db.execute('ROLLBACK TO scenario')
                self.db.execute('RELEASE scenario')

    def test_source_file_and_np_bl_association_have_distinct_explanations(self):
        self.import_cost()
        self.db.execute("UPDATE reception_accounting_refs SET source_file=''")
        self.assertIn('MISSING_SOURCE', [i['code'] for i in self.issues()])
        lid = self.db.execute('SELECT id FROM reception_lines').fetchone()[0]
        with patch('backend.services.reception_source_bl.excluded_ids', return_value={lid}):
            self.assertEqual([i['code'] for i in self.issues()], ['NP_BL_MISMATCH'])

    def test_second_arrival_requires_explicit_em_scope_and_does_not_change_it(self):
        self.attention(seq=2)
        self.import_cost()
        self.assertIn('EM_SCOPE_REQUIRED', [i['code'] for i in self.issues()])
        self.assertEqual(self.status(), 'SOLICITUD TRANSFERENCIA')

    def test_diagnosis_works_on_query_only_connection(self):
        self.import_cost(cost='')
        self.db.execute('PRAGMA query_only=ON')
        self.assertEqual([i['code'] for i in self.issues()], ['MISSING_COSTING_DATE'])
