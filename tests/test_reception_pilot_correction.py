"""Retired-pilot correction with synthetic BLs only."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from backend.services import reception
from backend.services.cloud_import_policy import documentary_only
from backend.services.reception_pilot_correction import correction_check, correct_pilot_reception
from backend.services.reception_work import reception_work_report
from backend.services.traceability import init_traceability_schema

STAMP = '2026-10-01T09:00:00'


def seed_pilot(connection, bl='QA-PILOT-1', complete=True):
    sid = connection.execute('''INSERT INTO reception_shipments
        (bl_awb,app_status,condition_status,received_packages,first_arrival_at,
         ip_reference,current_assistant,created_at,updated_at)
        VALUES (?,'REVISION SISTEMA','EN PROCESO',2,?,'QA-IP','qa.assistant',?,?)''',
                             (bl, STAMP, STAMP, STAMP)).lastrowid
    line = connection.execute('''INSERT INTO reception_lines
        (shipment_id,np_code,ip_reference,expected_qty,received_qty)
        VALUES (?,'QA-NP','QA-IP',5,1)''', (sid,)).lastrowid
    guide = 'QA-TRUCK-' + str(sid)
    connection.execute('''INSERT INTO reception_truck_guides
        (guide_code,guide_status,archived_at,archive_reason,created_by,created_at,updated_at)
        VALUES (?,'CANCELADA',?,'Retiro autorizado de pruebas','qa.admin',?,?)''',
                       (guide, STAMP, STAMP, STAMP))
    receipt = connection.execute('''INSERT INTO reception_receipts
        (shipment_id,sequence_no,received_packages,truck_guide,username,received_at)
        VALUES (?,1,2,?,'qa.admin',?)''', (sid, guide, STAMP)).lastrowid
    shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?', (sid,)).fetchone()
    attention = reception._create_reception_attention(connection, shipment, receipt, 'qa.admin', 'REVISION SISTEMA')
    connection.execute('UPDATE reception_attention_lines SET verified_qty=1 WHERE attention_id=?', (attention['id'],))
    ref = connection.execute('''INSERT INTO reception_accounting_refs
        (shipment_id,source_key,ip_reference,fr_number,em_number,created_at,updated_at)
        VALUES (?,?,'QA-IP','QA-FR',?,?,?)''',
        (sid, 'QA-REF-' + str(sid), 'QA-EM' if complete else '', STAMP, STAMP)).lastrowid
    if complete:
        connection.execute('''INSERT INTO reception_accounting_ems
            (accounting_ref_id,ip_reference_key,em_number,username,created_at)
            VALUES (?,'QAIP','QA-EM','importacion',?)''', (ref, STAMP))
    return sid, line, receipt, attention['id'], ref, guide


class PilotCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        reception.init_reception_schema(self.db)
        init_traceability_schema(self.db)
        self.db.execute('CREATE TABLE order_importation_refs(sap_ov TEXT,transport_type TEXT,bl_awb TEXT)')
        self.ids = seed_pilot(self.db)
        self.sid, self.line, self.receipt, self.attention, self.ref, self.guide = self.ids
        self.stock = patch.object(reception, 'global_stock_summary', return_value={})
        self.stock.start()
        self.addCleanup(self.stock.stop)

    def data(self, action='pending_arrival'):
        return {'action':action, 'reason':'Pruebas retiradas confirmadas por administracion',
                'confirmed':True, 'bl_confirmation':'QA-PILOT-1',
                'token':correction_check(self.db, self.sid).get('token')}

    def correct(self, data=None, role='ADMINISTRADOR'):
        return correct_pilot_reception(self.db, self.sid, data or self.data(), 'qa.admin', role)

    def test_pending_preserves_documents_and_snapshot_without_physical_work(self):
        before = tuple(self.db.execute('SELECT * FROM reception_accounting_refs').fetchone())
        result = self.correct()
        self.assertEqual(result['app_status'], 'PROGRAMADO')
        self.assertFalse(result['physically_received'])
        self.assertIsNone(result['active_attention_id'])
        self.assertEqual(result['lines'][0]['received_qty'], 0)
        self.assertEqual(tuple(self.db.execute('SELECT * FROM reception_accounting_refs').fetchone()), before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0], 1)
        saved = json.loads(self.db.execute("SELECT old_value FROM reception_history WHERE field_name='pilot_snapshot'").fetchone()[0])
        self.assertEqual(saved['reception_lines'][0]['received_qty'], 1)
        self.assertEqual(saved['reception_receipts'][0]['received_packages'], 2)
        report = reception_work_report(self.db, now=STAMP)
        self.assertEqual(report['summary']['total'], 0)
        self.assertEqual(report['summary']['pending_arrival'], 1)
        arrival = reception_work_report(self.db, now=STAMP, view='arrival')['items']
        self.assertEqual(len(arrival), 1)
        self.assertIsNone(arrival[0]['work_started_at'])
        self.assertFalse(correction_check(self.db, self.sid)['eligible'])

    def test_historical_closes_without_inventing_quantities_or_attention(self):
        result = self.correct(self.data('historical_closed'))
        self.assertEqual(result['app_status'], 'CERRADO')
        self.assertEqual(result['condition_status'], 'COMPLETADO')
        self.assertEqual(result['lines'][0]['received_qty'], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_attentions').fetchone()[0], 1)
        self.assertEqual(reception_work_report(self.db, now=STAMP)['summary']['total'], 0)
        context = documentary_only.set(True)
        try:
            reception._refresh_accounting_summary(self.db, self.sid, 'cloud.sync', 'QA.xlsx')
        finally:
            documentary_only.reset(context)
        self.assertEqual(self.db.execute('SELECT app_status,received_packages FROM reception_shipments').fetchone()[:], ('CERRADO', 0))

    def test_historical_requires_all_documentary_em(self):
        self.db.execute('DELETE FROM reception_accounting_ems')
        self.db.execute("UPDATE reception_accounting_refs SET em_number='' ")
        self.assertFalse(correction_check(self.db, self.sid)['can_close_history'])
        with self.assertRaisesRegex(ValueError, 'FR y EM'):
            self.correct(self.data('historical_closed'))
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines').fetchone()[0], 1)

    def test_pending_reset_survives_restart_and_manual_documentary_refresh(self):
        self.correct()
        reception.init_reception_schema(self.db)
        reception._refresh_accounting_summary(self.db, self.sid, 'qa.admin', 'QA-new-cut.xlsx')
        row = self.db.execute('SELECT app_status,received_packages,first_arrival_at FROM reception_shipments').fetchone()
        self.assertEqual(tuple(row), ('PROGRAMADO', 0, None))
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines').fetchone()[0], 0)
        self.assertIsNone(reception._active_reception_attention(self.db, self.sid))

    def test_historical_reset_survives_restart_without_legacy_quantity_initialization(self):
        self.correct(self.data('historical_closed'))
        reception.init_reception_schema(self.db)
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_shipments').fetchone()[0], 'CERRADO')
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines').fetchone()[0], 0)

    def test_detail_returns_token_after_legacy_sample_initialization(self):
        detail = reception.reception_detail(self.db, self.sid)
        data = self.data()
        data['token'] = detail['pilot_correction']['token']
        self.assertEqual(self.correct(data)['app_status'], 'PROGRAMADO')

    def test_new_real_attention_uses_full_quantity_not_retired_count(self):
        self.correct()
        shipment = self.db.execute('SELECT * FROM reception_shipments').fetchone()
        attention = reception._create_reception_attention(self.db, shipment, None, 'qa.admin')
        self.assertNotEqual(attention['id'], self.attention)
        self.assertEqual(self.db.execute('SELECT planned_qty FROM reception_attention_lines WHERE attention_id=?', (attention['id'],)).fetchone()[0], 5)
        self.assertEqual(reception._active_reception_attention(self.db, self.sid)['id'], attention['id'])

    def test_workers_cannot_correct_and_metadata_is_admin_only(self):
        for role in ('ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION', 'PICKER'):
            with self.assertRaises(PermissionError):
                self.correct(role=role)
        detail = reception.reception_detail(self.db, self.sid, 'ASISTENTE_RECEPCION', 'qa.assistant')
        self.assertNotIn('pilot_correction', detail)

    def test_requires_exact_bl_reason_explicit_confirmation_and_action(self):
        for change in ({'confirmed':False}, {'confirmed':'true'}, {'reason':'corto'},
                       {'bl_confirmation':'1'}, {'action':'delete'}, {'token':''}):
            with self.assertRaises(ValueError):
                self.correct({**self.data(), **change})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history WHERE event_type=?', ('CORRECCION PRUEBA',)).fetchone()[0], 0)

    def test_concurrent_document_update_rejected_even_when_timestamp_same(self):
        data = self.data()
        self.db.execute("UPDATE reception_accounting_refs SET em_number='QA-NEW' WHERE id=?", (self.ref,))
        with self.assertRaisesRegex(ValueError, 'cambio'):
            self.correct(data)

    def test_active_manifest_blocks_even_with_retired_guide(self):
        self.db.execute('''INSERT INTO reception_truck_bl_manifest
            (truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at)
            VALUES (?,?,2,'qa.admin',?,?)''', (self.guide, self.sid, STAMP, STAMP))
        self.assertFalse(correction_check(self.db, self.sid)['eligible'])

    def test_real_scan_or_unknown_provenance_never_assumed_test(self):
        for change in ("archived_at=NULL", "archive_reason='Cancelacion operativa'", "guide_status='LISTA_PARA_CONTEO'"):
            self.db.execute('SAVEPOINT qa_case')
            self.db.execute('UPDATE reception_truck_guides SET ' + change)
            self.assertFalse(correction_check(self.db, self.sid)['eligible'])
            self.db.execute('ROLLBACK TO qa_case'); self.db.execute('RELEASE qa_case')
        self.db.execute('UPDATE reception_receipts SET truck_guide=NULL')
        self.assertFalse(correction_check(self.db, self.sid)['eligible'])

    def test_downstream_inventory_blocks_correction(self):
        with patch('backend.services.reception_pilot_correction.reception._truck_guide_header') as guide:
            guide.return_value = {'guide_status':'CANCELADA','archived_at':STAMP,'archive_reason':'prueba'}
            self.db.execute('DROP TABLE inventory_lots')
            self.db.execute('CREATE TABLE inventory_lots(reception_shipment_id INTEGER)')
            self.db.execute('INSERT INTO inventory_lots VALUES (?)', (self.sid,))
            self.assertFalse(correction_check(self.db, self.sid)['eligible'])

    def test_failed_detail_rolls_back_every_change_and_audit(self):
        with patch.object(reception, 'reception_detail', side_effect=RuntimeError('QA rollback')):
            with self.assertRaises(RuntimeError):
                self.correct()
        self.assertEqual(self.db.execute('SELECT received_packages FROM reception_receipts').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines').fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='CORRECCION PRUEBA'").fetchone()[0], 0)

    def test_annulled_attention_remains_readable_but_cannot_reopen(self):
        self.correct()
        self.assertIsNone(reception._active_reception_attention(self.db, self.sid))
        self.assertEqual(reception._active_reception_attention(self.db, self.sid, self.attention)['id'], self.attention)
        with self.assertRaisesRegex(PermissionError, 'anulada'):
            reception.rewind_reception_stage(self.db, self.sid,
                {'status':'ARRIBADO','reason':'QA correccion','attention_id':self.attention}, 'qa.admin', 'ADMINISTRADOR')

    def test_archived_positive_arrival_and_scan_are_audited_and_voided(self):
        aid = self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES (?,?,2,'QA-ARRIVAL','qa.admin',?)''', (self.guide, self.sid, STAMP)).lastrowid
        self.db.execute('''INSERT INTO reception_truck_bl_locations
            (arrival_id,location_text,package_count,username,created_at,updated_at)
            VALUES (?,'QA-ZONE',2,'qa.admin',?,?)''', (aid, STAMP, STAMP))
        self.db.execute('''INSERT INTO reception_truck_package_scans
            (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
            VALUES (?,?,'QA-PIECE','QA-PIECE','qa.admin',?)''', (self.guide, self.sid, STAMP))
        self.correct()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_truck_bl_arrivals').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT scan_status FROM reception_truck_package_scans').fetchone()[0], 'ANULADO')
        saved = json.loads(self.db.execute("SELECT old_value FROM reception_history WHERE field_name='pilot_snapshot'").fetchone()[0])
        self.assertEqual(saved['reception_truck_bl_locations'][0]['location_text'], 'QA-ZONE')


if __name__ == '__main__':
    unittest.main()
