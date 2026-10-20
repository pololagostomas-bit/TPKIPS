"""Separate arrivals remain separate tasks, including administrative reversal."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import app
from backend.services import reception


class IndependentArrivalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = app.DB_PATH
        app.DB_PATH = Path(self.tmp.name) / 'qa.sqlite'
        app.init_db()
        self.db = sqlite3.connect(app.DB_PATH)
        self.db.row_factory = sqlite3.Row
        self.sid = self.db.execute("""INSERT INTO reception_shipments
            (bl_awb,expected_packages,current_assistant,current_auxiliary,created_at,updated_at)
            VALUES ('QA-INDEPENDENT',10,'operator','aux','2026-10-19','2026-10-19')""").lastrowid
        self.lid = self.db.execute("""INSERT INTO reception_lines
            (shipment_id,np_code,description,expected_qty) VALUES (?,'NP-QA','Synthetic part',8)""",
            (self.sid,)).lastrowid

    def tearDown(self):
        self.db.close()
        app.DB_PATH = self.original_path
        self.tmp.cleanup()

    def arrive(self, guide, locate=True):
        reception.plan_truck_bl_packages(self.db, guide, self.sid, 1, 'operator', 'ADMINISTRADOR')
        reception.confirm_truck_guide(self.db, guide, guide, 'operator', 'ADMINISTRADOR')
        reception.process_truck_guide_arrivals(self.db, guide,
            [{'shipment_id': self.sid, 'received_packages': 1}], 'qa-' + guide, '',
            'operator', 'ADMINISTRADOR')
        if locate:
            reception.process_truck_guide_locations(self.db, guide,
                [{'shipment_id': self.sid, 'locations': [{'location': 'TEMP', 'package_count': 1}]}],
                'operator', 'ADMINISTRADOR')
        self.db.execute('UPDATE reception_shipments SET truck_guide=? WHERE id=?', (guide, self.sid))
        return self.db.execute('''SELECT a.id FROM reception_attentions a
            JOIN reception_receipts r ON r.id=a.receipt_id WHERE r.truck_guide=?''', (guide,)).fetchone()[0]

    def test_start_count_returns_this_truck_attention_not_oldest(self):
        first = self.arrive('QA-FIRST')
        second = self.arrive('QA-SECOND')
        result = reception.start_truck_guide_bl_counting(
            self.db, 'QA-SECOND', self.sid, 'operator', 'ADMINISTRADOR')
        self.assertEqual(result['shipment']['attention_id'], second)
        self.assertEqual(result['shipment']['app_status'], 'REVISION SISTEMA')
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_attentions WHERE id=?',
                                        (first,)).fetchone()[0], 'ARRIBADO')

    def test_selected_older_arrival_can_start_while_newer_is_open(self):
        first = self.arrive('QA-FIRST')
        self.arrive('QA-SECOND')
        try:
            detail = reception.change_reception_status(self.db, self.sid,
                {'status': 'REVISION SISTEMA', 'attention_id': first, 'require_location': True},
                'operator', 'ADMINISTRADOR')
        except PermissionError as error:
            self.fail('Another arrival must not block this task: ' + str(error))
        self.assertEqual(detail['attention_id'], first)

    def test_explicit_attention_must_not_fall_back_to_another(self):
        first = self.arrive('QA-FIRST')
        before = list(self.db.iterdump())
        with self.assertRaises(ValueError):
            reception.change_reception_status(self.db, self.sid,
                {'status': 'REVISION SISTEMA', 'attention_id': first + 5000},
                'operator', 'ADMINISTRADOR')
        self.assertEqual(before, list(self.db.iterdump()))

    def test_detail_identifies_selected_arrival_truck(self):
        first = self.arrive('QA-FIRST')
        self.arrive('QA-SECOND')
        detail = reception.reception_detail(self.db, self.sid, attention_id=first)
        self.assertEqual(detail.get('selected_attention_truck_guide'), 'QA-FIRST')
        self.assertEqual(detail['truck_guide'], 'QA-SECOND')
        self.assertEqual(detail['attentions'][0].get('truck_guide'), 'QA-FIRST')

    def test_saved_physical_arrival_does_not_lock_bl_to_old_zone(self):
        self.arrive('QA-FIRST', locate=False)
        guide = reception.create_scanner_truck_guide(self.db, 'operator', 'ADMINISTRADOR')['truck_guide']
        try:
            result = reception.add_scanned_truck_bl(self.db, guide, 'QA-INDEPENDENT', 'operator', 'ADMINISTRADOR')
        except ValueError as error:
            self.fail('A saved earlier arrival must not block a later truck: ' + str(error))
        self.assertTrue(result['added'])

    def test_unconfirmed_previous_scan_truck_still_blocks_reassignment(self):
        first = reception.create_scanner_truck_guide(self.db, 'operator', 'ADMINISTRADOR')['truck_guide']
        second = reception.create_scanner_truck_guide(self.db, 'operator', 'ADMINISTRADOR')['truck_guide']
        reception.add_scanned_truck_bl(self.db, first, 'QA-INDEPENDENT', 'operator', 'ADMINISTRADOR')
        with self.assertRaises(ValueError):
            reception.add_scanned_truck_bl(self.db, second, 'QA-INDEPENDENT', 'operator', 'ADMINISTRADOR')

    def test_revert_only_checks_its_attention_not_other_counting_arrival(self):
        first = self.arrive('QA-FIRST')
        second = self.arrive('QA-SECOND')
        self.db.execute("UPDATE reception_attentions SET app_status='REVISION SISTEMA' WHERE id=?", (second,))
        self.db.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA' WHERE id=?", (self.sid,))
        try:
            reception.revert_truck_guide(self.db, 'QA-FIRST', 'operator', 'ADMINISTRADOR',
                                        'PENDIENTE', reason='Wrong first arrival QA')
        except PermissionError as error:
            self.fail('Another attention cannot block reversing untouched arrival: ' + str(error))
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_attentions WHERE id=?',
                                        (second,)).fetchone()[0], 'REVISION SISTEMA')
        self.assertTrue(self.db.execute('SELECT condition_status FROM reception_attentions WHERE id=?',
                                       (first,)).fetchone()[0].startswith('ANULADA'))

    def test_reversal_preflights_all_bls_before_voiding_any_scan(self):
        self.arrive('QA-FIRST')
        other = self.db.execute('''INSERT INTO reception_shipments
            (bl_awb,app_status,created_at,updated_at) VALUES ('QA-OTHER','REVISION SISTEMA','qa','qa')''').lastrowid
        self.db.execute('''INSERT INTO reception_truck_bl_manifest
            (truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at) VALUES ('QA-FIRST',?,1,'qa','qa','qa')''', (other,))
        receipt = self.db.execute('''INSERT INTO reception_receipts
            (shipment_id,sequence_no,received_packages,truck_guide,username,received_at)
            VALUES (?,1,1,'QA-FIRST','qa','qa')''', (other,)).lastrowid
        shipment = self.db.execute('SELECT * FROM reception_shipments WHERE id=?', (other,)).fetchone()
        reception._create_reception_attention(self.db, shipment, receipt, 'qa', 'REVISION SISTEMA')
        self.db.execute('''INSERT INTO reception_truck_bl_arrivals
            (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
            VALUES ('QA-FIRST',?,1,'qa-other','qa','qa')''', (other,))
        self.db.execute('''INSERT INTO reception_truck_package_scans
            (truck_guide,shipment_id,package_code,normalized_code,scanned_by,scanned_at)
            VALUES ('QA-FIRST',?,'QA-PIECE','QA-PIECE','qa','qa')''', (self.sid,))
        before = list(self.db.iterdump())
        with self.assertRaises(PermissionError):
            reception.revert_truck_guide(self.db, 'QA-FIRST', 'qa', 'ADMINISTRADOR',
                                        reason='Atomic batch check QA')
        self.assertEqual(before, list(self.db.iterdump()))

    def test_reopening_one_attention_recalculates_only_its_count_contribution(self):
        first = self.arrive('QA-FIRST')
        second = self.arrive('QA-SECOND')
        self.db.execute("UPDATE reception_attentions SET app_status='REVISION SISTEMA'")
        self.db.execute("UPDATE reception_shipments SET app_status='REVISION SISTEMA'")
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=3 WHERE attention_id=?', (first,))
        self.db.execute('UPDATE reception_attention_lines SET verified_qty=4 WHERE attention_id=?', (second,))
        reception._sync_reception_line_totals(self.db, self.sid)
        reception.rewind_reception_stage(self.db, self.sid,
            {'attention_id': second, 'status': 'ARRIBADO', 'reason': 'Reopen this arrival to correct a package'},
            'operator', 'ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT received_qty FROM reception_lines WHERE id=?', (self.lid,)).fetchone()[0], 3)


if __name__ == '__main__':
    unittest.main()
