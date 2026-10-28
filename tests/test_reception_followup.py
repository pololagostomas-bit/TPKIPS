import unittest
from tests.test_reception_costing import CostingFixture


class FollowupTests(CostingFixture):
    def report(self,**options):
        from backend.services import reception_followup
        return reception_followup.report(self.db,options)

    def test_real_arrivals_and_simple_states(self):
        self.db.execute("UPDATE reception_attentions SET app_status='ARRIBADO'")
        self.db.execute("UPDATE reception_shipments SET app_status='ARRIBADO'")
        item=self.report()['items'][0]
        self.assertEqual(item['state'],'RECEPCION')
        self.assertEqual(item['arrival_date'],'2026-10-01')
        self.assertEqual(item['bl_awb'],'QA-COST')
        self.assertEqual(item['costing_date'],'')

    def test_documentary_closed_and_planned_shipments_do_not_appear_as_arrived(self):
        self.db.execute("INSERT INTO reception_shipments(bl_awb,app_status,created_at,updated_at) VALUES('QA-DOC','CERRADO','2026-10-01','2026-10-01')")
        self.assertEqual(self.report()['total'],1)
        self.assertEqual(self.report(search='QA-DOC')['total'],0)

    def test_costing_sets_available_and_uses_source_date(self):
        self.import_cost()
        item=self.report()['items'][0]
        self.assertEqual(item['state'],'DISPONIBLE')
        self.assertEqual(item['costing_date'],'2026-10-03')
        self.assertEqual(item['available_date'],'2026-10-03')
        self.assertEqual(item['em_date'],'2026-10-02')

    def test_other_delivery_keeps_bl_in_work_with_available_delivery_visible(self):
        other=self.attention(seq=2,ip='IP260002',status='REVISION SISTEMA')
        self.import_cost()
        item=self.report()['items'][0]
        self.assertEqual(item['state'],'ALMACEN')
        self.assertEqual(item['costed_deliveries'],1)
        self.assertEqual(len(item['deliveries']),2)
        self.assertEqual(item['delivery_count'],2)

    def test_filter_and_totals_precede_pagination(self):
        r=self.report(state='COSTEO',limit='1',offset='0')
        self.assertEqual(r['summary']['COSTEO'],1)
        self.assertEqual(r['total'],1)
        self.assertEqual(self.report(state='DISPONIBLE')['total'],0)
        self.assertEqual(self.report(search='no-match')['summary']['COSTEO'],0)

    def test_all_filtered_rows_count_even_outside_current_page(self):
        original=self.sid
        for index in range(3):
            self.sid=self.db.execute("INSERT INTO reception_shipments(bl_awb,app_status,created_at,updated_at) VALUES(?,'SOLICITUD TRANSFERENCIA','2026-10-01','2026-10-01')",('QA-PAGE-'+str(index),)).lastrowid
            self.attention()
        self.sid=original
        r=self.report(limit='1')
        self.assertEqual(len(r['items']),1)
        self.assertEqual(r['summary']['COSTEO'],4)
        self.assertEqual(r['total'],4)
        self.assertTrue(r['has_more'])

    def test_bad_filters_are_rejected(self):
        for options in [{'state':'CERRADO'},{'limit':'5000'},{'offset':'-1'},{'from':'bad'},{'from':'2026-10-20','to':'2026-10-01'}]:
            with self.subTest(options=options),self.assertRaises(ValueError):self.report(**options)

    def test_receipt_with_cancelled_attention_does_not_prove_arrival(self):
        self.db.execute("UPDATE reception_attentions SET condition_status='ANULADA POR CORRECCION'")
        self.assertEqual(self.report()['total'],0)

    def test_pending_costing_and_dates_are_read_only(self):
        before=self.db.total_changes
        r=self.report()
        self.assertEqual(r['items'][0]['state'],'COSTEO')
        self.assertEqual(self.db.total_changes,before)
