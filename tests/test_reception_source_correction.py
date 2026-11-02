import unittest
from backend.services import reception,reception_source_bl as source
from backend.services.reception_np_progress import deferred_balances
from tests import test_reception_partial_count as fixtures


class SourceCorrectionTests(unittest.TestCase):
    setUpBase=fixtures.PartialCountTests.setUpBase
    detail=fixtures.PartialCountTests.detail
    stock_value=fixtures.PartialCountTests.stock_value
    scan=fixtures.PartialCountTests.scan

    def setUp(self):
        fixtures.PartialCountTests.setUp(self)
        self.scan()
        self.db.execute("UPDATE reception_lines SET source_key='qa-source',source_sheet='QA-SHEET',ip_reference='QA-IP',oc_number='QA-OC' WHERE id=?",(self.lid,))
        row=dict(self.db.execute('SELECT * FROM reception_lines WHERE id=?',(self.lid,)).fetchone())
        source.store(self.db,[{'source_sheet':'QA-SHEET','source_row':2,'np_code':row['np_code'],'guide':'','ip':'QA-IP','oc':'QA-OC','ov':row['ov_number']}],['QA-SHEET'],'qa.xlsx','2026-10-28')

    def correct(self,role='ADMINISTRADOR',**changes):
        return reception.update_reception_line_quantity(self.db,self.sid,self.lid,{
            'attention_id':self.attention,'source_bl_correction':True,'confirmed':True,
            'received_qty':0,'previous_received_qty':8,'reason':'Source removed the BL from this order',**changes},'receiver',role)

    def test_worker_rejected_and_admin_correction_preserves_scan_and_plan(self):
        previous=self.detail()['lines'][0]['np_scanned_at']
        with self.assertRaises(PermissionError):self.scan()
        with self.assertRaises(PermissionError):self.correct(role='ASISTENTE_RECEPCION')
        result=self.correct();line=next(r for r in result['lines'] if r['id']==self.lid)
        self.assertEqual(line['attention_verified_qty'],0)
        self.assertEqual(line['attention_planned_qty'],8)
        self.assertEqual(line['np_scanned_at'],previous)
        self.assertFalse(line['source_bl_eligible'])
        self.assertTrue(self.db.execute("SELECT 1 FROM reception_history WHERE event_type='CORRECCION NP' AND field_name LIKE '%:source_bl'").fetchone())
        self.assertNotIn(self.sid,deferred_balances(self.db))

    def test_stale_or_unconfirmed_request_cannot_remove_count(self):
        for change in [{'confirmed':False},{'previous_received_qty':7},{'reason':'short'},{'received_qty':1},{'scan_np':True},{'attention_id':None}]:
            with self.subTest(change=change),self.assertRaises(ValueError):self.correct(**change)
        self.assertEqual(self.db.execute('SELECT verified_qty FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',(self.attention,self.lid)).fetchone()[0],8)

    def test_unscanned_defaults_can_be_cleared_without_faking_a_read(self):
        self.db.execute('UPDATE reception_attention_lines SET np_scanned_at=NULL WHERE attention_id=? AND reception_line_id=?',(self.attention,self.lid))
        result=self.correct();line=next(r for r in result['lines'] if r['id']==self.lid)
        self.assertFalse(line['np_scanned_at']);self.assertEqual(line['attention_verified_qty'],0)

    def test_forward_stage_cannot_hide_positive_foreign_count(self):
        with self.assertRaisesRegex(PermissionError,'regularizar'):
            reception.change_reception_status(self.db,self.sid,{'attention_id':self.attention,'status':'EM'},'receiver','ADMINISTRADOR')

    def test_corrected_line_does_not_block_valid_np_count_completion(self):
        self.correct();self.scan(self.missing,2)
        result=reception.change_reception_status(self.db,self.sid,{'attention_id':self.attention,'status':'EM'},'receiver','ADMINISTRADOR')
        self.assertEqual(result['app_status'],'EM')
        self.assertEqual(result['np_progress'],{'read':1,'total':1})
