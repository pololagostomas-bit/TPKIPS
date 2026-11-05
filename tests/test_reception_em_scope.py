"""Explicit administrative association of an existing EM, without a new document."""
from backend.services import reception, reception_costing
from tests.test_reception_costing import CostingFixture
from tests import test_reception_partial_costing as fixtures
from unittest.mock import patch


class EmScopeTests(CostingFixture):
    source = fixtures.PartialCostingTests.source

    def setUp(self):
        super().setUp()
        self.other = self.attention(seq=2)
        self.first, self.second = self.source()
        self.em = self.db.execute('SELECT * FROM reception_accounting_ems WHERE accounting_ref_id=?', (self.first['id'],)).fetchone()

    def bind(self, role='ADMINISTRADOR', **data):
        from backend.services.reception_em_scope import bind_existing
        return bind_existing(self.db, self.sid, self.aid,
            {'id': self.first['id'], 'em_id': self.em['id'], 'em_number': '70001',
             'ip_key': 'IP260001', 'confirmed': True, 'reason': 'Scope verified with source owner', **data}, 'qa.admin', role)

    def test_binding_preserves_em_dates_and_physical_work_and_is_idempotent(self):
        before = [tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')]
        self.assertTrue(self.bind())
        self.assertFalse(self.bind())
        row = self.db.execute('SELECT * FROM reception_accounting_ems WHERE id=?', (self.em['id'],)).fetchone()
        self.assertEqual(row['attention_id'], self.aid)
        for key in ['em_number','em_date','username','created_at']:
            self.assertEqual(row[key], self.em[key])
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines ORDER BY id')], before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='VINCULO EM'").fetchone()[0], 1)
        reception_costing.reconcile(self.db, self.sid, 'qa')
        self.assertEqual(self.status(), 'CERRADO')
        self.assertEqual(self.status(self.other), 'SOLICITUD TRANSFERENCIA')

    def test_worker_cannot_bind_existing_source_em(self):
        for role in ['ASISTENTE_RECEPCION','AUXILIAR_RECEPCION','PICKER']:
            with self.subTest(role=role), self.assertRaises(PermissionError):
                self.bind(role)

    def test_bad_scope_confirmation_or_document_does_not_mutate(self):
        for values in [{'confirmed': False}, {'confirmed': 'true'}, {'reason': ''},
                       {'em_id': 999999}, {'em_number': '70002'}, {'ip_key': 'IP260999'},
                       {'id': self.second['id']}]:
            with self.subTest(values=values), self.assertRaises((ValueError,PermissionError)):
                self.bind(**values)
        self.assertIsNone(self.db.execute('SELECT attention_id FROM reception_accounting_ems WHERE id=?', (self.em['id'],)).fetchone()[0])

    def test_an_em_already_bound_to_another_arrival_cannot_be_moved(self):
        self.db.execute('UPDATE reception_accounting_ems SET attention_id=? WHERE id=?', (self.other, self.em['id']))
        with self.assertRaises(ValueError):
            self.bind()

    def test_canceled_or_wrong_stage_arrival_cannot_be_bound(self):
        for status, condition in [('SOLICITUD TRANSFERENCIA','ANULADA QA'), ('REVISION SISTEMA','EN PROCESO')]:
            self.db.execute('UPDATE reception_attentions SET app_status=?,condition_status=? WHERE id=?', (status, condition, self.aid))
            with self.assertRaises(PermissionError):
                self.bind()

    def test_numeric_alias_cannot_assign_the_same_em_to_two_arrivals(self):
        self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,ip_reference_key,attention_id,em_number,em_date,username,created_at) VALUES(?,'IP260001',?,'70001 -','2026-10-02','importacion','2026-10-02')", (self.first['id'], self.other))
        with self.assertRaises(ValueError):
            self.bind()

    def test_entry_scoped_to_another_ip_cannot_be_reassigned(self):
        self.db.execute("UPDATE reception_accounting_refs SET ip_reference='IP260001, IP260002' WHERE id=?", (self.first['id'],))
        self.db.execute("UPDATE reception_accounting_ems SET ip_reference_key='IP260002' WHERE id=?", (self.em['id'],))
        with self.assertRaises(ValueError):
            self.bind()

    def test_withdrawn_source_em_cannot_be_bound(self):
        self.db.execute("UPDATE reception_accounting_refs SET em_number='' WHERE id=?", (self.first['id'],))
        with self.assertRaises(ValueError):
            self.bind()

    def test_reference_update_uses_the_binding_and_costs_only_current_arrival(self):
        with patch.object(reception, 'reception_detail', return_value={}) as detail:
            reception.update_reception_references(self.db, self.sid,
                {'attention_id': self.aid, 'reference_updates': [{
                    'id': self.first['id'], 'em_id': self.em['id'], 'em_number': '70001',
                    'ip_key': 'IP260001', 'bind_to_attention': True, 'confirmed': True,
                    'reason': 'Verified against the received arrival'}]}, 'qa.admin', 'ADMINISTRADOR')
        self.assertEqual(detail.call_args.args[-1], self.aid)
        self.assertEqual(self.status(), 'CERRADO')
        self.assertEqual(self.status(self.other), 'SOLICITUD TRANSFERENCIA')
