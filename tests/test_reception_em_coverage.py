"""Exceptional combined coverage never changes the one-EM-per-arrival default."""
from unittest.mock import patch
from backend.services import reception as r, reception_costing as costing
from tests.test_reception_costing import CostingFixture


class EmCoverageTests(CostingFixture):
    def setUp(self):
        super().setUp()
        self.second=self.attention(seq=2); self.third=self.attention(seq=3)
        self.import_cost(em='70001',cost='2026-10-04')
        self.ref=self.db.execute('SELECT * FROM reception_accounting_refs').fetchone()
        self.em=self.db.execute('SELECT * FROM reception_accounting_ems').fetchone()
        self.db.execute('UPDATE reception_accounting_ems SET attention_id=? WHERE id=?',(self.third,self.em['id']))

    def coverage(self, ids=None, role='ADMINISTRADOR', **values):
        from backend.services.reception_em_coverage import set_coverage
        return set_coverage(self.db,self.sid,{
            'id':self.ref['id'],'em_id':self.em['id'],'em_number':'70001','ip_key':'IP260001',
            'coverage_attention_ids':ids if ids is not None else [self.aid,self.second,self.third],
            'confirmed':True,'reason':'Source owner confirms this combined EM coverage',**values},'qa.admin',role)

    def test_default_never_shares_a_single_em_automatically(self):
        costing.reconcile(self.db,self.sid,'qa')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')
        self.assertEqual(self.status(self.second),'SOLICITUD TRANSFERENCIA')
        self.assertEqual(self.status(self.third),'CERRADO')
        self.assertFalse(r._accounting_ref_em_complete(self.db,self.sid,self.ref,'IP260001'))

    def test_explicit_three_arrival_coverage_closes_each_without_copying_em_or_physical_rows(self):
        physical=[tuple(x) for x in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        original=tuple(self.db.execute('SELECT * FROM reception_accounting_ems').fetchone())
        self.assertTrue(self.coverage());self.assertFalse(self.coverage())
        costing.reconcile(self.db,self.sid,'qa')
        self.assertTrue(all(self.status(a)=='CERRADO' for a in [self.aid,self.second,self.third]))
        self.assertEqual(tuple(self.db.execute('SELECT * FROM reception_accounting_ems').fetchone()),original)
        self.assertEqual([tuple(x) for x in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')],physical)
        self.assertEqual(r._accounting_em_values(self.db,self.ref['id'],'IP260001'),['70001'])
        self.assertTrue(r._accounting_ref_em_complete(self.db,self.sid,self.ref,'IP260001'))
        self.assertEqual(r._accounting_status_for_shipment(self.db,self.sid),'EM REGISTRADA')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='COBERTURA EM'").fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT SUM(transfer_assistant_checked) FROM reception_attentions').fetchone()[0],0)

    def test_partial_selection_does_not_cover_omitted_or_future_arrivals(self):
        self.coverage([self.aid,self.third]);fourth=self.attention(seq=4)
        costing.reconcile(self.db,self.sid,'qa')
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.status(self.second),'SOLICITUD TRANSFERENCIA')
        self.assertEqual(self.status(fourth),'SOLICITUD TRANSFERENCIA')
        self.assertFalse(r._accounting_ref_em_complete(self.db,self.sid,self.ref,'IP260001'))

    def test_worker_or_bad_scope_confirmation_document_cannot_add_coverage(self):
        for role in ['ASISTENTE_RECEPCION','AUXILIAR_RECEPCION']:
            with self.subTest(role=role),self.assertRaises(PermissionError):self.coverage(role=role)
        for data in [{'confirmed':False},{'confirmed':'true'},{'reason':''},{'em_id':999999},
                     {'em_number':'70002'},{'ip_key':'IP260999'},
                     {'coverage_attention_ids':[self.aid,self.second]},
                     {'coverage_attention_ids':[self.third]},
                     {'coverage_attention_ids':[self.aid,self.third,self.third]},
                     {'coverage_attention_ids':[True,self.third]},
                     {'coverage_attention_ids':[999999,self.third]}]:
            with self.subTest(data=data),self.assertRaises((ValueError,PermissionError)):self.coverage(**data)
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])

    def test_canceled_unreceived_or_other_ip_cannot_be_covered(self):
        for query in ["UPDATE reception_attentions SET condition_status='ANULADA QA' WHERE id=?",
                      "UPDATE reception_attentions SET receipt_id=NULL WHERE id=?",
                      "UPDATE reception_attention_lines SET verified_qty=0 WHERE attention_id=?"]:
            with self.subTest(query=query):
                self.db.execute('SAVEPOINT invalid_case');self.db.execute(query,(self.aid,))
                with self.assertRaises((ValueError,PermissionError)):self.coverage()
                self.db.execute('ROLLBACK TO invalid_case');self.db.execute('RELEASE invalid_case')

    def test_source_or_original_assignment_change_invalidates_saved_coverage(self):
        self.coverage()
        for query,args in [("UPDATE reception_accounting_refs SET em_number=''",()),
                           ("UPDATE reception_accounting_refs SET fr_number='OTHER-FR'",()),
                           ("UPDATE reception_accounting_refs SET ip_reference='IP260999'",()),
                           ('UPDATE reception_accounting_ems SET attention_id=?',(self.second,))]:
            with self.subTest(query=query):
                self.db.execute('SAVEPOINT changed_source');self.db.execute(query,args)
                self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])
                self.db.execute('ROLLBACK TO changed_source');self.db.execute('RELEASE changed_source')

    def test_revocation_preserves_closure_but_removes_current_cost_evidence(self):
        self.coverage();costing.reconcile(self.db,self.sid,'qa')
        completed=self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0]
        self.assertTrue(self.coverage([]));costing.reconcile(self.db,self.sid,'qa')
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],completed)
        self.assertEqual(self.db.execute('SELECT source_current FROM reception_attention_costing WHERE attention_id=?',(self.aid,)).fetchone()[0],0)

    def test_reference_update_routes_exception_to_coverage_and_reconciliation(self):
        with patch.object(r,'reception_detail',return_value={}):
            r.update_reception_references(self.db,self.sid,{'attention_id':self.aid,'reference_updates':[{
                'id':self.ref['id'],'em_id':self.em['id'],'em_number':'70001','ip_key':'IP260001',
                'coverage_attention_ids':[self.aid,self.second,self.third],'confirmed':True,
                'reason':'Confirmed combined documentary coverage'}]},'qa.admin','ADMINISTRADOR')
        self.assertEqual(self.status(),'CERRADO')

    def test_separate_three_ems_still_cover_three_arrivals_without_exception(self):
        self.db.execute("UPDATE reception_accounting_refs SET em_number='70001, 70002, 70003'")
        for em,aid in [('70002',self.aid),('70003',self.second)]:
            self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,ip_reference_key,attention_id,em_number,em_date,username,created_at) VALUES(?,'IP260001',?,?,'2026-10-02','qa','2026-10-02')",(self.ref['id'],aid,em))
        costing.reconcile(self.db,self.sid,'qa')
        self.assertTrue(all(self.status(a)=='CERRADO' for a in [self.aid,self.second,self.third]))

    def test_exception_cannot_claim_an_arrival_with_a_different_current_em(self):
        self.db.execute("UPDATE reception_accounting_refs SET em_number='70001, 70002'")
        self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,ip_reference_key,attention_id,em_number,em_date,username,created_at) VALUES(?,'IP260001',?,'70002','2026-10-02','qa','2026-10-02')",(self.ref['id'],self.aid))
        with self.assertRaises(ValueError):self.coverage()
        self.assertFalse(costing.evidence(self.db,self.sid,self.second)['ready'])

    def test_future_empty_row_of_same_fr_does_not_ask_for_another_em_after_full_coverage(self):
        self.coverage()
        row=dict(self.ref);row.pop('id');row.update(source_key='qa-future-row',source_row=99,em_number='',costing_date='')
        self.db.execute('INSERT INTO reception_accounting_refs('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        future=self.db.execute("SELECT * FROM reception_accounting_refs WHERE source_key='qa-future-row'").fetchone()
        self.assertTrue(r._accounting_ref_em_complete(self.db,self.sid,future,'IP260001'))
