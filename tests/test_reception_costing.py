"""Synthetic source dates never stand in for a physical receipt or SAP check."""
import sqlite3
import unittest
from openpyxl import Workbook
from backend.services import reception


class CostingFixture(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        reception.init_reception_schema(self.db)
        self.addCleanup(self.db.close)
        self.sid = self.db.execute("""INSERT INTO reception_shipments
            (bl_awb,app_status,expected_packages,received_packages,created_at,updated_at)
            VALUES('QA-COST','SOLICITUD TRANSFERENCIA',1,1,'2026-10-01','2026-10-01')""").lastrowid
        self.aid = self.attention()

    def attention(self, seq=1, ip='IP260001', status='SOLICITUD TRANSFERENCIA'):
        rid = self.db.execute("""INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,username,received_at)
            VALUES(?,?,1,'qa','2026-10-01T08:00:00')""", (self.sid,seq)).lastrowid
        aid = self.db.execute("""INSERT INTO reception_attentions
            (shipment_id,receipt_id,sequence_no,app_status,created_at,updated_at)
            VALUES(?,?,?,?, '2026-10-01T08:00:00','2026-10-01T08:00:00')""", (self.sid,rid,seq,status)).lastrowid
        lid = self.db.execute("""INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty)
            VALUES(?, ?,?,1,1)""", (self.sid,'QA-NP-'+str(seq),ip)).lastrowid
        self.db.execute('INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty,verified_qty) VALUES(?,?,1,1)',(aid,lid))
        return aid

    def import_cost(self, cost='2026-10-03', ip='IP260001', fr='QA-FR', em='QA-EM'):
        book=Workbook();sheet=book.active;sheet.title=reception.ACCOUNTING_SHEET_NAME
        sheet.append(['IP','AWB','FACTURA RESERVA','ENTRADA DE MERCANCIA','FECHA DE RECEPCION','FECHA DE EM','FECHA DE COSTEO'])
        sheet.append([ip,'QA-COST',fr,em,'2026-10-01','2026-10-02',cost])
        return reception.import_reception_accounting_workbook(self.db,book,'qa-facturas.xlsx','qa','ADMINISTRADOR')

    def status(self,aid=None):
        return self.db.execute('SELECT app_status FROM reception_attentions WHERE id=?',(aid or self.aid,)).fetchone()[0]


class CostingTests(CostingFixture):
    def test_excel_date_closes_step_five_without_inventing_sap_check(self):
        self.import_cost()
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.db.execute('SELECT transfer_assistant_checked FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],0)
        from backend.services import reception_costing as costing
        self.assertEqual(costing.evidence(self.db,self.sid,self.aid)['costing_date'],'2026-10-03')

    def test_repeat_is_idempotent(self):
        self.import_cost()
        count=self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0]
        self.import_cost()
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history').fetchone()[0],count)

    def test_costing_never_skips_physical_work(self):
        self.db.execute("UPDATE reception_attentions SET app_status='UBICACION'")
        self.db.execute("UPDATE reception_shipments SET app_status='UBICACION'")
        self.import_cost()
        self.assertEqual(self.status(),'UBICACION')

    def test_missing_or_invalid_dates_do_not_close(self):
        for value in ['', 'pendiente','2099-01-01','2026-09-30','2026-02-30']:
            with self.subTest(value=value):
                self.import_cost(value)
                self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_unrelated_ip_and_missing_documents_do_not_close(self):
        self.import_cost(ip='IP260002')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')
        self.db.execute('DELETE FROM reception_accounting_refs')
        self.import_cost(fr='')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_other_arrival_stays_open(self):
        other=self.attention(seq=2,ip='IP260002',status='REVISION SISTEMA')
        self.import_cost()
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.status(other),'REVISION SISTEMA')
        self.assertNotEqual(self.db.execute('SELECT app_status FROM reception_shipments').fetchone()[0],'CERRADO')

    def test_same_ip_in_two_arrivals_requires_em_bound_to_each(self):
        other=self.attention(seq=2)
        self.import_cost()
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')
        self.assertEqual(self.status(other),'SOLICITUD TRANSFERENCIA')
        ref=self.db.execute('SELECT id FROM reception_accounting_refs').fetchone()[0]
        self.db.execute('UPDATE reception_accounting_ems SET attention_id=? WHERE accounting_ref_id=?',(self.aid,ref))
        from backend.services import reception_costing as costing
        costing.reconcile(self.db,self.sid,'qa')
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.status(other),'SOLICITUD TRANSFERENCIA')

    def test_conflict_and_annulled_attention_do_not_close(self):
        self.db.execute("UPDATE reception_attentions SET condition_status='ANULADA POR PRUEBA'")
        self.import_cost()
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_costing_must_cover_every_received_ip(self):
        lid=self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty) VALUES(?,'QA-SECOND','IP260002',1,1)",(self.sid,)).lastrowid
        self.db.execute('INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty,verified_qty) VALUES(?,?,1,1)',(self.aid,lid))
        self.import_cost()
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_reconcile_is_atomic_and_revokes_unused_link(self):
        from backend.services import reception_transfer
        reception_transfer.enqueue(self.db,self.sid,self.aid)
        self.import_cost()
        self.assertEqual(self.db.execute('SELECT status FROM reception_transfer_requests').fetchone()[0],'REVOKED')

    def test_conflicting_ip_does_not_close(self):
        self.import_cost(cost='')
        self.db.execute("UPDATE reception_shipments SET accounting_conflict_count=1")
        self.db.execute("UPDATE reception_accounting_refs SET costing_date='2026-10-03'")
        from backend.services import reception_costing
        reception_costing.reconcile(self.db,self.sid,'qa')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_corrected_costing_date_tracks_excel_without_reopening(self):
        self.import_cost()
        completed=self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0]
        self.import_cost(cost='2026-10-04')
        self.assertEqual(self.db.execute('SELECT costing_date FROM reception_attention_costing WHERE attention_id=?',(self.aid,)).fetchone()[0],'2026-10-04')
        self.assertEqual(self.status(),'CERRADO')
        self.assertEqual(self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],completed)

    def test_costing_before_documentary_em_does_not_close(self):
        self.import_cost(cost='2026-10-01')
        self.assertEqual(self.status(),'SOLICITUD TRANSFERENCIA')

    def test_removed_source_date_preserves_history_but_stops_claiming_available(self):
        self.import_cost()
        self.import_cost(cost='')
        from backend.services import reception_followup
        self.assertEqual(reception_followup.report(self.db)['items'][0]['state'],'COSTEO')
        self.assertEqual(self.status(),'CERRADO')
        self.import_cost(cost='2026-10-04')
        self.assertEqual(reception_followup.report(self.db)['items'][0]['state'],'DISPONIBLE')

    def test_already_closed_delivery_gets_documentary_costing_without_redoing_closure(self):
        self.db.execute("UPDATE reception_attentions SET app_status='CERRADO',completed_at='2026-10-03T10:00:00',transfer_assistant_checked=1 WHERE id=?",(self.aid,))
        self.db.execute("UPDATE reception_shipments SET app_status='CERRADO'")
        self.import_cost()
        from backend.services import reception_followup
        self.assertEqual(reception_followup.report(self.db)['items'][0]['state'],'DISPONIBLE')
        self.assertEqual(self.db.execute('SELECT completed_at FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],'2026-10-03T10:00:00')
