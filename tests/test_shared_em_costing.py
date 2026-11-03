"""One source row may explicitly cover two IPs without moving a manual EM."""
import unittest
from unittest.mock import patch
from backend.services import reception,reception_costing as costing
from tests import test_reception_costing as fixtures


class SharedEMTests(fixtures.CostingFixture):
    def setUp(self):
        super().setUp()
        lid=self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty) VALUES(?,'QA-SECOND','IP260002',1,1)",(self.sid,)).lastrowid
        self.db.execute('INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty,verified_qty) VALUES(?,?,1,1)',(self.aid,lid))
        self.import_cost(cost='',ip='IP260001, IP260002')
        self.db.execute('UPDATE reception_accounting_ems SET ip_reference_key=?,attention_id=?,username=?',('IP260002',self.aid,'qa.worker'))

    def test_explicit_source_row_closes_both_ips_without_reassigning_manual_em(self):
        before=tuple(self.db.execute('SELECT * FROM reception_accounting_ems').fetchone())
        self.import_cost(ip='IP260001, IP260002')
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(tuple(self.db.execute('SELECT * FROM reception_accounting_ems').fetchone()),before)
        self.assertEqual(costing.evidence(self.db,self.sid,self.aid)['costing_date'],'2026-10-03')

    def test_same_ip_in_another_delivery_does_not_share_the_confirmation(self):
        other=self.attention(seq=2,ip='IP260001')
        self.import_cost(ip='IP260001, IP260002')
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.status(other),'SOLICITUD TRANSFERENCIA')

    def test_source_without_second_ip_cannot_close_the_delivery(self):
        self.import_cost(ip='IP260001')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_removed_source_em_revokes_shared_proof_without_reopening_history(self):
        self.import_cost(ip='IP260001, IP260002')
        self.assertEqual(self.status(),'CERRADO')
        completed=self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0]
        self.import_cost(ip='IP260001, IP260002',em='')
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],completed)

    def test_a_manual_summary_cannot_create_source_coverage(self):
        self.import_cost(ip='IP260001, IP260002',em='')
        self.db.execute("UPDATE reception_accounting_refs SET em_number='QA-EM',costing_date='2026-10-03'")
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])

    def test_multiple_source_ems_do_not_invent_an_ip_assignment(self):
        self.import_cost(cost='',ip='IP260001, IP260002',em='QA-EM, QA-EM-2')
        self.db.execute('UPDATE reception_accounting_ems SET ip_reference_key=?',('IP260002',))
        self.import_cost(ip='IP260001, IP260002',em='QA-EM, QA-EM-2')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_source_date_guards_still_apply_to_shared_em(self):
        for value in ['', '2099-01-01', '2026-09-30', '2026-10-01']:
            with self.subTest(value=value):
                self.import_cost(cost=value,ip='IP260001, IP260002')
                self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_withdrawn_source_em_cannot_survive_via_unscoped_history(self):
        self.import_cost(ip='IP260001, IP260002')
        self.db.execute('UPDATE reception_accounting_ems SET ip_reference_key=NULL')
        self.import_cost(ip='IP260001, IP260002',em='')
        self.assertFalse(costing.evidence(self.db,self.sid,self.aid)['ready'])

    def test_changed_source_em_does_not_reuse_old_unscoped_em(self):
        self.db.execute('UPDATE reception_accounting_ems SET ip_reference_key=NULL')
        self.import_cost(ip='IP260001, IP260002',em='QA-NEW-EM')
        ref=self.db.execute('SELECT id FROM reception_accounting_refs').fetchone()[0]
        self.assertEqual(reception._accounting_em_values(self.db,ref,'IP260001'),['QA-NEW-EM'])

    def test_failed_import_restores_previous_source_snapshot(self):
        from backend.services import accounting_source_em
        self.db.commit()
        before=[tuple(r) for r in self.db.execute('SELECT * FROM reception_accounting_source_em')]
        with patch.object(accounting_source_em,'store',side_effect=RuntimeError('qa failure')):
            with self.assertRaises(RuntimeError),self.db:
                self.import_cost(ip='IP260001, IP260002')
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM reception_accounting_source_em')],before)
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')
