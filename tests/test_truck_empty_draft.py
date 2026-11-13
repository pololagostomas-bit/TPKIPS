"""Leaving an unused scanner preparation must not cancel saved work."""
import sqlite3
import subprocess
import unittest
from pathlib import Path

from backend.services import reception as r
from backend.services.truck_controls import cancel_truck_guide


class EmptyTruckDraftTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        r.init_reception_schema(self.db)
        self.guide = r.create_scanner_truck_guide(self.db, 'owner', 'ASISTENTE_RECEPCION')['truck_guide']
        self.sid = self.db.execute('''INSERT INTO reception_shipments
            (bl_awb,created_at,updated_at) VALUES ('QA-EMPTY','2026-11-13','2026-11-13')''').lastrowid

    def discard(self, username='owner', role='ASISTENTE_RECEPCION', **kwargs):
        return cancel_truck_guide(self.db, self.guide, username, role, empty_only=kwargs.get('flag', True))

    def test_empty_discard_is_idempotent_and_preserves_header(self):
        self.assertTrue(self.discard()['cancelled'])
        before = list(self.db.iterdump())
        self.assertTrue(self.discard()['cancelled'])
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.db.execute('SELECT guide_status FROM reception_truck_guides').fetchone()[0], 'CANCELADA')

    def test_existing_associations_even_inactive_or_voided_block_discard(self):
        statements = [
            ('''INSERT INTO reception_truck_bl_manifest
                (truck_guide,shipment_id,planned_packages,operational_active,created_by,created_at,updated_at)
                VALUES (?,?,0,0,'qa','qa','qa')''', (self.guide, self.sid)),
            ('''INSERT INTO reception_truck_manifest
                (truck_guide,shipment_id,expected_packages,created_at) VALUES (?,?,0,'qa')''', (self.guide, self.sid)),
            ('''INSERT INTO reception_truck_bl_arrivals
                (truck_guide,shipment_id,received_packages,arrival_key,username,arrived_at)
                VALUES (?,?,0,'QA','qa','qa')''', (self.guide, self.sid)),
            ('''INSERT INTO reception_receipts
                (truck_guide,shipment_id,sequence_no,received_packages,username,received_at)
                VALUES (?,?,1,0,'qa','qa')''', (self.guide, self.sid)),
            ('''INSERT INTO reception_truck_package_scans
                (truck_guide,shipment_id,package_code,normalized_code,scan_status,scanned_by,scanned_at)
                VALUES (?,?,'QA','QA','ANULADO','qa','qa')''', (self.guide, self.sid)),
            ('UPDATE reception_shipments SET truck_guide=? WHERE id=?', (self.guide, self.sid)),
            ('''INSERT INTO reception_truck_arrivals (truck_guide,username,received_at,updated_at)
                VALUES (?,'qa','qa','qa')''', (self.guide,)),
            ('''INSERT INTO reception_truck_locations (truck_guide,location_text,package_count)
                VALUES (?,'QA-LEGACY',0)''', (self.guide,)),
        ]
        for sql, args in statements:
            with self.subTest(sql=sql):
                self.db.execute('SAVEPOINT evidence')
                self.db.execute(sql, args)
                before = list(self.db.iterdump())
                self.assertFalse(self.discard(role='ADMINISTRADOR')['cancelled'])
                self.assertEqual(list(self.db.iterdump()), before)
                self.db.execute('ROLLBACK TO evidence'); self.db.execute('RELEASE evidence')

    def test_planned_or_started_header_is_not_an_empty_preparation(self):
        for field, value in [('planned_packages', 1), ('carrier_reference', 'QA-CARRIER'),
                             ('count_enabled_at', '2026-11-13'), ('guide_status', 'EN_CURSO'),
                             ('confirmed_by', 'qa.admin'), ('display_code', 'CAMION-QA-01')]:
            with self.subTest(field=field):
                self.db.execute('SAVEPOINT header')
                self.db.execute(f'UPDATE reception_truck_guides SET {field}=?', (value,))
                before = list(self.db.iterdump())
                self.assertFalse(self.discard()['cancelled'])
                self.assertEqual(list(self.db.iterdump()), before)
                self.db.execute('ROLLBACK TO header'); self.db.execute('RELEASE header')

    def test_other_owner_invalid_role_and_invalid_flag_are_rejected(self):
        for username, role, flag, error in [
            ('other', 'ASISTENTE_RECEPCION', True, PermissionError),
            ('owner', 'AUXILIAR_RECEPCION', True, PermissionError),
            ('owner', 'ASISTENTE_RECEPCION', 'true', ValueError),
        ]:
            with self.subTest(username=username, role=role, flag=flag):
                before = list(self.db.iterdump())
                with self.assertRaises(error): self.discard(username, role, flag=flag)
                self.assertEqual(list(self.db.iterdump()), before)

    def test_http_stale_empty_request_cannot_cancel_a_now_linked_bl(self):
        from tests import test_reception_package_access as fixtures
        case = fixtures.PackageAccessTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        before = case.snapshot()
        status, result = case.request('/api/receptions/truck-guide/cancel', 'POST',
            'ADMINISTRADOR', {'truck_guide': case.guide, 'empty_only': True})
        self.assertEqual(status, 200)
        self.assertFalse(result['cancelled'])
        self.assertEqual(case.snapshot(), before)

    def test_empty_preparation_navigation_in_browser_control(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('truck_empty_draft_dom.cjs'))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
