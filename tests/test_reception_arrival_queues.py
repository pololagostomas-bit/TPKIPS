"""Read-only arrival priorities, distinct from physical arrival and SLA."""
import unittest

from tests import test_reception_work as work_tests
from tests.test_reception_work import shipment, complete_refs, STAMP


class ArrivalQueueTests(unittest.TestCase):
    setUp = work_tests.ReceptionWorkTests.setUp
    tearDown = work_tests.ReceptionWorkTests.tearDown
    report = work_tests.ReceptionWorkTests.report

    def waiting(self, bl, day=None, fr=None):
        sid = shipment(self.db,bl=bl,ips='')
        self.db.execute('UPDATE reception_shipments SET scheduled_date=?,fr_number=? WHERE id=?',
                        (day,fr,sid))
        return sid

    def test_future_today_missing_and_invalid_dates_are_upcoming_without_fr(self):
        for index,day in enumerate(('2026-09-29','2026-09-28',None,'not-a-date')):
            self.waiting(f'QA-UPCOMING-{index}',day)
        report = self.report(view='upcoming')
        self.assertEqual(report['total_bl'],4)
        self.assertEqual(report['summary']['upcoming_arrival'],4)
        self.assertEqual(report['summary']['pending_truck'],0)
        self.assertTrue(all(not row['work_pending'] for row in report['items']))

    def test_past_date_or_any_fr_requires_truck_without_marking_arrived(self):
        past = self.waiting('QA-PAST','2026-09-27')
        master = self.waiting('QA-MASTER-FR','2026-12-01','QA-FR-MASTER')
        reference = self.waiting('QA-REF-FR')
        complete_refs(self.db,reference,1)
        both = self.waiting('QA-BOTH','2026-09-26','QA-FR-BOTH')
        before = self.db.total_changes
        report = self.report(view='truck')
        self.assertEqual({row['id'] for row in report['items']},{past,master,reference,both})
        by_id = {row['id']:row for row in report['items']}
        self.assertEqual(by_id[past]['arrival_reason'],'Fecha Triton vencida')
        self.assertEqual(by_id[master]['arrival_reason'],'FR registrada')
        self.assertTrue(by_id[reference]['has_fr'])
        self.assertEqual(by_id[both]['arrival_reason'],'FR registrada / Fecha Triton vencida')
        self.assertEqual(report['summary']['pending_arrival'],4)
        self.assertEqual(report['summary']['pending_truck'],4)
        self.assertEqual(report['summary']['total'],0)
        for row in report['items']:
            self.assertEqual(row['work_status'],'PROGRAMADO')
            self.assertEqual(row['sla_status'],'SIN INICIO')
            self.assertIsNone(row['remaining_hours'])
            self.assertIsNone(row['sla_due_at'])
            self.assertIsNone(row['work_started_at'])
        self.assertEqual(self.report(view='pending')['items'],[])
        self.assertEqual(self.report(view='history')['items'],[])
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)

    def test_queue_moves_after_sync_without_writing_business_states(self):
        sid = self.waiting('QA-SYNC','2026-09-29')
        self.assertEqual(self.report(view='upcoming')['total_bl'],1)
        self.db.execute('UPDATE reception_shipments SET fr_number=? WHERE id=?',('QA-FR',sid))
        self.assertEqual(self.report(view='truck')['total_bl'],1)
        self.assertEqual(self.report(view='upcoming')['total_bl'],0)
        self.db.execute('UPDATE reception_shipments SET fr_number=NULL WHERE id=?',(sid,))
        self.assertEqual(self.report(view='truck',now='2026-09-30 00:00:00')['total_bl'],1)
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_shipments WHERE id=?',(sid,)).fetchone()[0],'PROGRAMADO')

    def test_arrivals_and_closed_history_never_enter_truck_queue(self):
        arrived = shipment(self.db,bl='QA-ARRIVED',arrival=STAMP,ips='')
        closed = shipment(self.db,bl='QA-CLOSED',status='CERRADO',ips='')
        for sid in (arrived,closed):
            self.db.execute('UPDATE reception_shipments SET scheduled_date=?,fr_number=? WHERE id=?',
                            ('2026-09-01','QA-FR',sid))
        self.assertEqual(self.report(view='truck')['total_bl'],0)
        self.assertEqual(self.report(view='upcoming')['total_bl'],0)
        self.assertEqual(self.report(view='pending')['total_bl'],1)
        self.assertEqual(self.report(view='history')['total_bl'],1)

    def test_lima_day_boundary_not_utc_or_worker_browser(self):
        self.waiting('QA-TODAY','2026-09-27')
        self.assertEqual(self.report(view='truck',now='2026-09-28T04:59:59Z')['total_bl'],0)
        self.assertEqual(self.report(view='truck',now='2026-09-28T05:00:00Z')['total_bl'],1)

    def test_legacy_arrival_view_and_filtered_paging_keep_global_totals(self):
        for index in range(105):
            self.waiting(f'QA-DUE-{index:03d}','2026-09-27')
        self.waiting('QA-FUTURE','2026-10-01')
        report = self.report(view='truck',offset=100)
        self.assertEqual(report['total_bl'],105)
        self.assertEqual(len(report['items']),5)
        filtered = self.report(view='truck',search='104')
        self.assertEqual(filtered['total_bl'],1)
        self.assertEqual(filtered['summary']['pending_truck'],105)
        self.assertEqual(filtered['summary']['upcoming_arrival'],1)
        self.assertEqual(self.report(view='arrival')['total_bl'],106)

    def test_assignments_and_roles_do_not_expose_other_users_pending_trucks(self):
        self.waiting('QA-OWN',fr='QA-FR')
        report = self.report(view='truck',role='ASISTENTE_RECEPCION',username='worker.test')
        self.assertEqual(report['total_bl'],1)
        report = self.report(view='truck',role='ASISTENTE_RECEPCION',username='other')
        self.assertEqual(report['summary']['pending_truck'],0)
        self.assertEqual(report['items'],[])
        with self.assertRaises(PermissionError):
            self.report(view='truck',role='PICKER',username='worker.test')

    def test_only_active_unarchived_trucks_are_returned_for_navigation(self):
        sid = self.waiting('QA-ASSIGNED',fr='QA-FR')
        for guide,status,active,archived in (
                ('QA-LIVE','PENDIENTE',1,None),('QA-SECOND','EN_CURSO',1,None),
                ('QA-CANCELLED','CANCELADA',1,None),('QA-ARCHIVED','PENDIENTE',1,STAMP),
                ('QA-INACTIVE','PENDIENTE',0,None)):
            self.db.execute('''INSERT INTO reception_truck_guides
                (guide_code,guide_status,archived_at,created_by,created_at,updated_at)
                VALUES (?,?,?,'qa',?,?)''',(guide,status,archived,STAMP,STAMP))
            self.db.execute('''INSERT INTO reception_truck_bl_manifest
                (truck_guide,shipment_id,planned_packages,operational_active,created_by,created_at,updated_at)
                VALUES (?,?,1,?,'qa',?,?)''',(guide,sid,active,STAMP,STAMP))
        self.assertEqual(self.report(view='truck')['items'][0]['arrival_trucks'],['QA-LIVE','QA-SECOND'])


if __name__=='__main__':
    unittest.main()
