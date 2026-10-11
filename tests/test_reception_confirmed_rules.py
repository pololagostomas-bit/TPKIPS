import os
import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.reception_closure import closure_check, master_state, reconcile_closure
from backend.services.reception_sla import deadline, elapsed_hours
from backend.services.truck_entry import resolve_entered_bl
from tests.test_reception_work import shipment, complete_refs, STAMP


class ConfirmedRulesTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        reception.init_reception_schema(self.db)
        self.addCleanup(self.db.close)

    def closed_attention(self, sid):
        return self.db.execute('''INSERT INTO reception_attentions
            (shipment_id,sequence_no,app_status,condition_status,created_at,updated_at,completed_at)
            VALUES (?,1,'CERRADO','COMPLETADO',?,?,?)''',(sid,STAMP,STAMP,STAMP)).lastrowid

    def test_unknown_bl_does_not_write_anything(self):
        for role in ('ADMINISTRADOR','ASISTENTE_RECEPCION'):
            before=self.db.total_changes
            with self.assertRaisesRegex(ValueError,'BL no encontrada'):
                resolve_entered_bl(self.db,'UNKNOWN-BL','test.user',role)
            self.assertEqual(self.db.total_changes,before)

    def test_known_bl_can_be_resolved_repeatedly_without_new_rows(self):
        sid=shipment(self.db,bl='KNOWN-BL')
        for code in ('knownbl',' KNOWN-BL '):
            row,created=resolve_entered_bl(self.db,code,'test.user','ASISTENTE_RECEPCION')
            self.assertEqual(row['id'],sid)
            self.assertFalse(created)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_shipments').fetchone()[0],1)

    def test_historical_closure_is_explicit_audited_and_idempotent(self):
        sid=shipment(self.db)
        complete_refs(self.db,sid)
        self.db.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,ip_reference,expected_qty,received_qty)
            VALUES (?,'TEST-NP','IP-101',5,0)''',(sid,))
        data={'confirmed':True,'historical':True,'reason':'Validacion del historico'}
        with patch.object(reception,'reception_detail',return_value={}):
            reconcile_closure(self.db,sid,data,'admin.test','ADMINISTRADOR')
            before=self.db.total_changes
            reconcile_closure(self.db,sid,data,'admin.test','ADMINISTRADOR')
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_shipments').fetchone()[0],'CERRADO')
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0],0)
        audit=self.db.execute("SELECT * FROM reception_history WHERE event_type='CONCILIACION CIERRE'").fetchall()
        self.assertEqual(len(audit),1)
        self.assertEqual(audit[0]['username'],'admin.test')
        self.assertIn(data['reason'],audit[0]['reason'])

    def test_historical_requires_admin_confirmation_and_reason(self):
        sid=shipment(self.db);complete_refs(self.db,sid)
        for data,role,error in [({'confirmed':True,'historical':True,'reason':'Historic test'},'ASISTENTE_RECEPCION',PermissionError),
                                ({'historical':True,'reason':'Historic test'},'ADMINISTRADOR',ValueError),
                                ({'confirmed':True,'historical':True,'reason':'short'},'ADMINISTRADOR',ValueError),
                                ({'confirmed':True,'reason':'Historic test'},'ADMINISTRADOR',ValueError)]:
            before=self.db.total_changes
            with self.assertRaises(error):
                reconcile_closure(self.db,sid,data,'test',role)
            self.assertEqual(self.db.total_changes,before)

    def test_missing_ip_docs_never_close(self):
        sid=shipment(self.db);complete_refs(self.db,sid,2)
        self.assertFalse(closure_check(self.db,sid,allow_documentary=True)[0])

    def test_open_partial_attention_keeps_master_open(self):
        sid=shipment(self.db,status='ARRIBADO');complete_refs(self.db,sid)
        self.closed_attention(sid)
        self.db.execute('''INSERT INTO reception_attentions
            (shipment_id,sequence_no,app_status,condition_status,created_at,updated_at)
            VALUES (?,2,'UBICACION','EN PROCESO',?,?)''',(sid,STAMP,STAMP))
        self.assertEqual(master_state(self.db,sid)[0],'UBICACION')
        self.assertFalse(closure_check(self.db,sid,allow_documentary=True)[0])

    def test_closed_partial_with_package_balance_keeps_master_open(self):
        sid=shipment(self.db,status='ARRIBADO');complete_refs(self.db,sid)
        self.closed_attention(sid)
        self.db.execute('UPDATE reception_shipments SET expected_packages=3,received_packages=2 WHERE id=?',(sid,))
        self.assertEqual(master_state(self.db,sid),('ARRIBADO','SALDO POR ARRIBAR'))

    def test_closed_partial_with_unit_balance_keeps_master_open(self):
        sid=shipment(self.db,status='ARRIBADO');complete_refs(self.db,sid);self.closed_attention(sid)
        self.db.execute('INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty) VALUES (?,\'NP\',\'IP-101\',10,6)',(sid,))
        self.assertEqual(master_state(self.db,sid),('ARRIBADO','UNIDADES POR ATENDER'))

    def test_complete_closed_attention_closes_master_without_changing_attention(self):
        sid=shipment(self.db,status='ARRIBADO');complete_refs(self.db,sid);self.closed_attention(sid)
        self.assertEqual(master_state(self.db,sid),('CERRADO','COMPLETADO'))

    def test_closing_attention_does_not_overwrite_pending_package_balance(self):
        sid=shipment(self.db,status='SOLICITUD TRANSFERENCIA');complete_refs(self.db,sid)
        aid=self.closed_attention(sid)
        self.db.execute("UPDATE reception_shipments SET expected_packages=3,received_packages=2,transfer_assistant_checked=1 WHERE id=?",(sid,))
        self.db.execute("UPDATE reception_attentions SET app_status='SOLICITUD TRANSFERENCIA',transfer_assistant_checked=1 WHERE id=?",(aid,))
        with patch.object(reception,'reception_detail',return_value={}):
            reception.change_reception_status(self.db,sid,{'status':'CERRADO'},'admin.test','ADMINISTRADOR')
        master=self.db.execute('SELECT app_status,condition_status FROM reception_shipments WHERE id=?',(sid,)).fetchone()
        self.assertEqual(tuple(master),('ARRIBADO','SALDO POR ARRIBAR'))
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_attentions WHERE id=?',(aid,)).fetchone()[0],'CERRADO')

    def test_open_attention_cannot_be_closed_by_entering_em(self):
        sid=shipment(self.db,status='EM');complete_refs(self.db,sid)
        aid=self.closed_attention(sid)
        self.db.execute("UPDATE reception_attentions SET app_status='EM' WHERE id=?",(aid,))
        reception._refresh_manual_accounting_status(self.db,sid,'admin.test',close_when_complete=True)
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_shipments WHERE id=?',(sid,)).fetchone()[0],'EM')

    def test_future_confirmed_truck_keeps_master_open_even_without_planned_packages(self):
        sid=shipment(self.db,status='ARRIBADO');complete_refs(self.db,sid);self.closed_attention(sid)
        self.db.execute("INSERT INTO reception_truck_guides(guide_code,is_confirmed,guide_status,created_by,created_at,updated_at) VALUES ('TEST-FUTURE',1,'PENDIENTE','test',?,?)",(STAMP,STAMP))
        self.db.execute("INSERT INTO reception_truck_bl_manifest(truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at) VALUES ('TEST-FUTURE',?,0,'test',?,?)",(sid,STAMP,STAMP))
        self.assertEqual(master_state(self.db,sid),('ARRIBADO','CAMION POR ARRIBAR'))

    def test_advanced_without_attention_cannot_be_closed_as_historical(self):
        sid=shipment(self.db,status='UBICACION');complete_refs(self.db,sid)
        self.assertFalse(closure_check(self.db,sid,allow_documentary=True)[0])

    def test_unmatched_physical_truck_arrival_is_not_documentary_history(self):
        sid=shipment(self.db);complete_refs(self.db,sid)
        self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES ('TEST-ORPHAN',?,1,'test-orphan-key','test',?)''',(sid,STAMP))
        self.assertFalse(closure_check(self.db,sid,allow_documentary=True)[0])

    def test_sla_skips_peru_holiday_and_sunday_but_counts_saturday_night(self):
        start='2026-10-07 08:00:00'
        end=deadline(start,72)
        self.assertEqual(end,'2026-10-12T08:00:00')
        self.assertEqual(elapsed_hours(start,end),72)
        self.assertEqual(reception._elapsed_hours_excluding_sundays(start,end),72)
        self.assertEqual(elapsed_hours('2026-10-10 13:00:00','2026-10-10 23:00:00'),10)

    def test_sla_holiday_sunday_does_not_double_skip_or_observe_monday(self):
        self.assertEqual(elapsed_hours('2026-06-06 08:00:00','2026-06-08 08:00:00'),24)
        self.assertEqual(elapsed_hours('2026-06-08 08:00:00','2026-06-08 09:00:00'),1)

    def test_sla_movable_easter_holidays_and_year_boundary(self):
        self.assertEqual(elapsed_hours('2026-04-01 08:00:00','2026-04-04 08:00:00'),24)
        end=deadline('2026-12-31 08:00:00',48)
        self.assertEqual(end,'2027-01-04T08:00:00')
        self.assertEqual(elapsed_hours('2026-12-31 08:00:00',end),48)

    def test_company_extra_holiday_is_configurable(self):
        with patch.dict(os.environ,{'WMS_SLA_EXTRA_HOLIDAYS':'["2026-10-09"]'}):
            end=deadline('2026-10-07 08:00:00',72)
            self.assertEqual(end,'2026-10-13T08:00:00')
            self.assertEqual(elapsed_hours('2026-10-07 08:00:00',end),72)

    def test_invalid_calendar_never_silently_ignores_holidays(self):
        with patch.dict(os.environ,{'WMS_SLA_EXTRA_HOLIDAYS':'{"bad":true}'}), self.assertRaises(ValueError):
            elapsed_hours('2026-10-09 08:00:00','2026-10-09 09:00:00')


if __name__=='__main__':
    unittest.main()
