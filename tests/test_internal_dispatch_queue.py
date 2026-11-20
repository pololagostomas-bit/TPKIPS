"""Cutoff queues are read-only; synthetic SAP orders and actor identities."""
from datetime import datetime
import unittest

from backend import app
from backend.services import dispatch_queue as queue
from tests import test_dispatch_sts as fixtures


class InternalDispatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DispatchSTSTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)

    def add(self,code,created,customer='TRITON TRADING S.A.',status='PENDIENTE'):
        with app.db() as db:
            db.execute('INSERT INTO orders(sap_ov,customer_name,source_order_date,app_status,document_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                       (code,customer,created,status,'Abierto',app.now(),app.now()))
            db.execute('INSERT INTO order_lines(sap_ov,source_row,item_code,pending_qty,required_qty,available_qty,warehouse) VALUES(?,?,?,?,?,?,?)',
                       (code,1,'NP-01',3,3,10,'1'))

    def read(self,**kw):
        with app.db() as db:
            before=db.total_changes
            result=queue.work_queue(app,db,'admin','ADMINISTRADOR',reference=datetime(2026,11,17,8),**kw)
            self.assertEqual(before,db.total_changes)
            return result

    def test_monday_cutoff_prioritizes_current_separately_from_backlog_and_future(self):
        for code,stamp in [('OLD','2026-11-13 16:00:00'),('CURRENT','2026-11-16 16:00:00'),
                           ('AFTER','2026-11-16 16:00:01'),('UNKNOWN','2026-11-16')]:self.add(code,stamp)
        self.add('REGULAR','2026-11-16 14:00:00','Cliente QA')
        result=self.read()
        self.assertEqual([r['sap_ov'] for r in result['items']],['CURRENT'])
        self.assertEqual(result['counts'],{'current':1,'carryover':1,'review':1})
        self.assertEqual(result['cutoff_at'],'2026-11-16T16:00:00')
        self.assertEqual(result['delivery_start'],'2026-11-17T08:00:00')
        self.assertEqual(result['delivery_end'],'2026-11-17T10:00:00')
        self.assertEqual([r['sap_ov'] for r in self.read(scope='carryover')['items']],['OLD'])
        self.assertEqual([r['sap_ov'] for r in self.read(scope='review')['items']],['UNKNOWN'])

    def test_latest_completed_cutoff_uses_lima_and_friday_carries_to_monday(self):
        meta=queue.cutoff_window(datetime.fromisoformat('2026-11-17T20:59:59+00:00'))
        self.assertEqual(meta['cutoff_at'],'2026-11-16T16:00:00')
        self.assertEqual(queue.cutoff_window(datetime(2026,11,16,8))['cutoff_at'],'2026-11-13T16:00:00')
        self.assertEqual(queue.cutoff_window(datetime(2026,11,13,16))['delivery_start'],'2026-11-16T08:00:00')

    def test_pagination_reaches_every_pending_ov_without_enriching_stock(self):
        for i in range(43):self.add(f'QA-{i:03}','2026-11-16 15:00:00')
        found=[]
        for page in range(1,9):
            result=self.read(page=page);self.assertEqual(result['total'],43)
            self.assertLessEqual(len(result['items']),6);found.extend(r['sap_ov'] for r in result['items'])
        self.assertEqual(len(found),43);self.assertEqual(len(set(found)),43)

    def test_regular_orders_require_search_and_never_start_work(self):
        self.add('QA-REGULAR','2026-11-16 12:00:00','Cliente QA')
        self.assertEqual(self.read(customer_type='regular')['items'],[])
        self.assertEqual([r['sap_ov'] for r in self.read(customer_type='regular',search='QA-REGULAR')['items']],['QA-REGULAR'])
        with app.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM attentions').fetchone()[0],0)

    def test_roles_closed_documents_and_completed_deliveries_stay_out(self):
        self.add('OTHER','2026-11-16 12:00:00')
        self.add('MINE','2026-11-16 12:00:00')
        for code,picker in [('OTHER','other'),('MINE','picker')]:
            aid=app.create_attention(code,'admin','ADMINISTRADOR')['id']
            with app.db() as db:db.execute("UPDATE attentions SET app_status='ASIGNADO',current_picker=? WHERE id=?",(picker,aid))
        with app.db() as db:
            result=queue.work_queue(app,db,'picker','PICKER',reference=datetime(2026,11,17,8))
            self.assertEqual([r['sap_ov'] for r in result['items']],['MINE'])
            db.execute("UPDATE orders SET app_status='CERRADO SAP',document_status='Cerrado' WHERE sap_ov='MINE'")
        self.assertEqual([r['sap_ov'] for r in self.read()['items']],['OTHER'])
        code,aid=self.fixture.guided()
        with app.db() as db:
            db.execute("UPDATE dispatch_context SET kind='OV' WHERE sap_ov=?",(code,))
            db.execute("UPDATE orders SET customer_name='TRITON TRADING S.A.',source_order_date='2026-11-16 13:00:00' WHERE sap_ov=?",(code,))
            app.save_delivery_evidence(db,aid,fixtures.PHOTO,'picker','PICKER_GUIADOR')
        from backend.services import dispatch_operations as ops
        ops.ship(app,aid,{'guide_reference':'QA-TEST'},'picker','PICKER_GUIADOR')
        self.assertNotIn(code,[r['sap_ov'] for r in self.read()['items']])
        with app.db() as db:db.execute('UPDATE order_lines SET pending_qty=4,required_qty=4 WHERE sap_ov=?',(code,))
        self.assertIn(code,[r['sap_ov'] for r in self.read()['items']])


if __name__=='__main__':unittest.main()
