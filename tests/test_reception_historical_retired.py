"""Historical closure is explicit; an annulment or accounting count is not a receipt."""
import sqlite3
import unittest
from unittest.mock import patch
from backend.services import reception
from backend.services.reception_closure import closure_check, reconcile_closure
from backend.services.reception_work import reception_work_report
from backend.services.traceability import init_traceability_schema
from tests.test_reception_pilot_correction import seed_pilot, STAMP


class RetiredHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute('CREATE TABLE order_importation_refs(sap_ov TEXT,transport_type TEXT,bl_awb TEXT,ip_reference TEXT,oc_number TEXT)')
        self.sid,self.line,self.receipt,self.attention,self.ref,self.guide=seed_pilot(self.db)
        self.db.execute("UPDATE reception_shipments SET app_status='PROGRAMADO',received_packages=0 WHERE id=?",(self.sid,))
        self.db.execute('UPDATE reception_receipts SET received_packages=0 WHERE shipment_id=?',(self.sid,))
        self.db.execute("UPDATE reception_attentions SET app_status='CERRADO',condition_status='ANULADA POR REVERSION' WHERE shipment_id=?",(self.sid,))
        self.db.execute('UPDATE reception_lines SET received_qty=0 WHERE shipment_id=?',(self.sid,))
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=0 WHERE attention_id=?',(self.attention,))
        self.stock=patch.object(reception,'global_stock_summary',return_value={})
        self.stock.start();self.addCleanup(self.stock.stop)

    def close(self, **changes):
        return reconcile_closure(self.db,self.sid,
            {'confirmed':True,'historical':True,'reason':'Historico confirmado por propietario',**changes},
            'qa.admin','ADMINISTRADOR')

    def test_only_retired_tests_close_master_without_fake_attention_or_receipt(self):
        self.assertEqual(closure_check(self.db,self.sid)[0],False)
        self.assertEqual(closure_check(self.db,self.sid,allow_documentary=True)[0],True)
        preserved={table:[tuple(row) for row in self.db.execute('SELECT * FROM '+table)]
            for table in ('reception_attentions','reception_attention_lines','reception_receipts',
                          'reception_lines','reception_accounting_refs','reception_accounting_ems')}
        detail=self.close()
        self.assertEqual(detail['app_status'],'CERRADO')
        self.assertEqual(detail['condition_status'],'COMPLETADO')
        self.assertIsNone(detail['first_arrival_at'])
        self.assertEqual(detail['attention_count'],0)
        self.assertEqual(detail['voided_attention_count'],1)
        self.assertEqual(detail['attentions'],[])
        self.assertIsNone(detail['active_attention_id'])
        for table,values in preserved.items():
            self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM '+table)],values,table)
        report=reception_work_report(self.db,view='history',now=STAMP)
        self.assertEqual(len(report['items']),1)
        self.assertIsNone(report['items'][0]['attention_id'])
        self.assertEqual(report['summary']['pending_arrival'],0)
        self.assertEqual(report['summary']['total'],0)
        self.assertIsNone(report['items'][0]['work_started_at'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE field_name='first_arrival_at'").fetchone()[0],1)
        reception.init_reception_schema(self.db)
        reception._refresh_accounting_summary(self.db,self.sid,'cloud.sync','qa.xlsx')
        self.assertEqual(self.db.execute('SELECT app_status,received_packages FROM reception_shipments').fetchone()[:],('CERRADO',0))

    def test_zero_test_attentions_do_not_appear_as_completed_tasks_before_master_closure(self):
        report=reception_work_report(self.db,view='history',now=STAMP)
        self.assertEqual(report['items'],[])
        self.assertEqual(report['summary']['open_attentions'],0)
        detail=reception.reception_detail(self.db,self.sid)
        self.assertEqual(detail['attentions'],[])
        explicit=reception.reception_detail(self.db,self.sid,attention_id=self.attention)
        self.assertEqual(explicit['attentions'][0]['id'],self.attention)
        self.assertEqual(explicit['attentions'][0]['label'],'Atencion anulada')

    def test_live_arrival_or_unverified_annulment_or_inventory_never_uses_shortcut(self):
        cases=[
            "UPDATE reception_receipts SET received_packages=1",
            "UPDATE reception_attentions SET app_status='EM'",
            "UPDATE reception_attentions SET condition_status='EN PROCESO'",
            "UPDATE reception_attentions SET receipt_id=NULL",
            "UPDATE reception_receipts SET truck_guide=NULL",
            "UPDATE reception_truck_guides SET archived_at=NULL",
            "UPDATE reception_truck_guides SET archive_reason='Cancelacion operativa'",
            "UPDATE reception_lines SET received_qty=1",
            "UPDATE reception_shipments SET accounting_conflict_count=1",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.db.execute('SAVEPOINT test_guard')
                self.db.execute(sql)
                self.assertFalse(closure_check(self.db,self.sid,allow_documentary=True)[0])
                self.db.execute('ROLLBACK TO test_guard');self.db.execute('RELEASE test_guard')
        self.db.execute('DROP TABLE inventory_lots')
        self.db.execute('CREATE TABLE inventory_lots(reception_shipment_id INTEGER)')
        self.db.execute('INSERT INTO inventory_lots VALUES (?)',(self.sid,))
        self.assertFalse(closure_check(self.db,self.sid,allow_documentary=True)[0])

    def test_each_expected_ip_and_fr_needs_its_em(self):
        self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty) VALUES (?,'NP-2','IP-2',1)",(self.sid,))
        self.assertFalse(closure_check(self.db,self.sid,allow_documentary=True)[0])
        self.db.execute("DELETE FROM reception_lines WHERE np_code='NP-2'")
        self.db.execute('DELETE FROM reception_accounting_ems')
        self.db.execute("UPDATE reception_accounting_refs SET em_number='' ")
        self.assertFalse(closure_check(self.db,self.sid,allow_documentary=True)[0])

    def test_confirmation_and_historical_flag_and_admin_required(self):
        for change in ({'historical':False},{'confirmed':False},{'reason':'corto'}):
            with self.assertRaises(ValueError):
                self.close(**change)
        with self.assertRaises(PermissionError):
            reconcile_closure(self.db,self.sid,{'confirmed':True,'historical':True,'reason':'Confirmado QA'},
                              'worker','ASISTENTE_RECEPCION',return_detail=False)

    def test_active_unconfirmed_manifest_blocks_documentary_closure(self):
        self.db.execute('''INSERT INTO reception_truck_bl_manifest
            (truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at)
            VALUES (?,?,1,'qa',?,?)''',(self.guide,self.sid,STAMP,STAMP))
        self.assertFalse(closure_check(self.db,self.sid,allow_documentary=True)[0])

    def test_fast_maintenance_result_keeps_audit_and_idempotency(self):
        with patch.object(reception,'reception_detail',side_effect=AssertionError('Not in maintenance path')):
            data={'confirmed':True,'historical':True,'reason':'Historico confirmado QA'}
            first=reconcile_closure(self.db,self.sid,data,'qa.admin','ADMINISTRADOR',return_detail=False)
            second=reconcile_closure(self.db,self.sid,data,'qa.admin','ADMINISTRADOR',return_detail=False)
        self.assertFalse(first['unchanged']);self.assertTrue(second['unchanged'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE field_name='app_status' AND new_value='CERRADO'").fetchone()[0],1)

    def test_real_partial_positions_exclude_retired_sequences_without_renumbering_ids(self):
        for sequence in (2,3):
            receipt=self.db.execute('''INSERT INTO reception_receipts
                (shipment_id,sequence_no,received_packages,username,received_at)
                VALUES (?,?,1,'qa',?)''',(self.sid,sequence,STAMP)).lastrowid
            self.db.execute('''INSERT INTO reception_attentions
                (shipment_id,sequence_no,receipt_id,app_status,created_at,updated_at)
                VALUES (?,?,?,'REVISION SISTEMA',?,?)''',(self.sid,sequence,receipt,STAMP,STAMP))
        work=reception_work_report(self.db,now=STAMP)
        self.assertEqual([row['attention_position'] for row in work['items']],[1,2])
        self.assertEqual([row['attention_sequence'] for row in work['items']],[2,3])
        self.assertTrue(all(row['attention_total']==2 for row in work['items']))
        detail=reception.reception_detail(self.db,self.sid)
        self.assertEqual(detail['attention_count'],2)
        self.assertEqual([row['label'] for row in detail['attentions']],['Atención 1/2','Atención 2/2'])
        items=reception.list_receptions(self.db,search='QA-PILOT-1',state='ALL')
        self.assertEqual([row['attention_label'] for row in items],['Atención 1/2','Atención 2/2'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_attentions').fetchone()[0],3)


if __name__=='__main__':
    unittest.main()
