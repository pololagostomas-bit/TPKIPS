import copy
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from backend.services import dhl_tracking as dhl, reception

AWB = '1234567890'
OTHER = '1234567891'
PIECES = ['JD000000000000000001', 'JD000000000000000002']
NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc).timestamp()


def payload(awb=AWB, delivered=False):
    return {'shipments': [{'id': awb, 'service': 'express',
        'status': {'statusCode': 'delivered' if delivered else 'transit', 'timestamp': '2026-10-13T06:00:00-05:00'},
        'details': {'totalNumberOfPieces': 2, 'pieceIds': PIECES}}]}


class DhlTrackingTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / 'qa.sqlite'
        self.key_file = Path(self.scratch.name) / 'test-key.secret'
        self.key_file.write_text('fictitious-test-key-not-a-real-key', encoding='ascii')
        self.env = patch.dict(os.environ, {'WMS_DHL_ENABLED': '1', 'DHL_API_KEY_FILE': str(self.key_file),
            'WMS_DHL_DAILY_BUDGET': '200', 'WMS_DHL_REFRESH_HOURS': '8'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.depth = 0
        self.app = SimpleNamespace(db=self.db)
        with self.db() as connection:
            reception.init_reception_schema(connection)
            dhl.init_schema(connection)
            self.shipment = self.insert(connection, AWB)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        self.depth += 1
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self.depth -= 1
            connection.close()

    def insert(self, connection, awb, scheduled='2026-10-13', state='PROGRAMADO', transport='COURIER'):
        return connection.execute("""INSERT INTO reception_shipments
            (bl_awb, scheduled_date, app_status, transport_type, expected_packages, created_at, updated_at)
            VALUES (?,?,?,?,7,'2026-10-13','2026-10-13')""", (awb, scheduled, state, transport)).lastrowid

    def cycle(self, now=NOW, data=None):
        def fetch(awb, key, stamp):
            self.assertEqual(self.depth, 0, 'Network must run outside app DB contexts')
            return dhl.parse_response(data or payload(awb), awb, stamp)
        with patch.object(dhl, 'fetch_tracking', side_effect=fetch) as fetch_mock:
            result = dhl.worker_cycle(self.app, now, date(2026, 10, 13))
        return result, fetch_mock.call_count

    def test_truck_progress_prefers_cached_dhl_total_without_network_or_wms_quantity_edit(self):
        self.cycle()
        with self.db() as connection, patch.object(dhl.time,'time',return_value=NOW), patch.object(dhl,'fetch_tracking') as fetch:
            guide = reception.create_scanner_truck_guide(connection,'qa','ADMINISTRADOR')['truck_guide']
            reception.add_scanned_truck_bl(connection,guide,AWB,'qa','ADMINISTRADOR')
            data = reception.scan_truck_package(connection,guide,self.shipment,PIECES[0],'qa','ADMINISTRADOR')
            summary = reception.truck_guide_summary(connection,guide,'qa','ADMINISTRADOR')
            self.assertEqual(data['bl_context']['package_progress']['expected'],2)
            self.assertEqual(data['bl_context']['package_progress']['source'],'DHL')
            self.assertEqual(summary['bls'][0]['package_progress']['expected'],2)
            self.assertEqual(connection.execute('SELECT expected_packages FROM reception_shipments WHERE id=?',(self.shipment,)).fetchone()[0],7)
            fetch.assert_not_called()

    def test_current_month_and_nearby_only_not_excel_import_timestamps(self):
        with self.db() as connection:
            self.insert(connection, '1234567892', '2026-09-30')
            self.insert(connection, '1234567893', '2026-10-19')
            self.insert(connection, '1234567899', '2026-08-01')
            self.insert(connection, '1234567894', '2026-10-13', 'CERRADO')
            self.insert(connection, '1234567895', '2026-10-13', transport='MARITIMO')
            self.insert(connection, '1234567896', None)
            self.insert(connection, 'NOT-AN-AWB', '2026-10-13')
            monday = self.insert(connection, '1234567897', '2026-10-12')
            sunday = self.insert(connection, '1234567898', '2026-10-18')
            dhl.maintain(connection, NOW, date(2026, 10, 13))
            self.assertEqual({r[0] for r in connection.execute('SELECT awb FROM dhl_tracking_jobs')},
                             {AWB, '1234567893', '1234567897', '1234567898'})
            self.assertTrue(monday and sunday)

    def test_prefetch_cap_prioritizes_nearby_and_crosses_month_boundary(self):
        with self.db() as connection:
            for index in range(105):
                self.insert(connection, str(2000000000 + index), '2026-10-30')
            nearby = '3000000000'
            self.insert(connection, nearby, '2026-11-01')
            dhl.maintain(connection, NOW, date(2026,10,31))
            queued = {r[0] for r in connection.execute('SELECT awb FROM dhl_tracking_jobs')}
            self.assertEqual(len(queued), 100)
            self.assertIn(nearby, queued)

    def test_daily_refresh_clamps_legacy_eight_hour_setting(self):
        self.assertEqual(dhl.refresh_seconds(),86400)
        self.cycle()
        self.assertEqual(self.cycle(NOW+12*3600),(False,0))
        self.assertEqual(self.cycle(NOW+86400),(True,1))

    def test_on_demand_old_open_guide_closed_not_queued(self):
        with self.db() as connection:
            old = self.insert(connection, OTHER, '2025-01-01')
            closed = self.insert(connection, '1234567892', '2025-01-01', 'CERRADO')
            self.assertTrue(dhl.enqueue(connection, old, NOW))
            self.assertFalse(dhl.enqueue(connection, closed, NOW))
            dhl.enqueue(connection, old, NOW + 999)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM dhl_tracking_jobs').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT next_at FROM dhl_tracking_jobs').fetchone()[0], NOW)

    def test_cache_many_local_reads_zero_extra_requests_and_no_receipt_changes(self):
        with self.db() as connection:
            before = dict(connection.execute('SELECT * FROM reception_shipments WHERE id=?', (self.shipment,)).fetchone())
        self.assertEqual(self.cycle(), (True, 1))
        for _ in range(12):
            with self.db() as connection:
                dhl.enqueue(connection, self.shipment, NOW + 60)
                status = dhl.shipment_status(connection, self.shipment, NOW + 60)
                self.assertEqual(status['total_pieces'], 2)
                self.assertEqual(status['known_pieces'], 2)
                self.assertEqual(dhl.verify_piece(connection, self.shipment, PIECES[0], NOW), 'verified')
        self.assertEqual(self.cycle(NOW + 60), (False, 0))
        with self.db() as connection:
            self.assertEqual(dict(connection.execute('SELECT * FROM reception_shipments WHERE id=?', (self.shipment,)).fetchone()), before)
            self.assertEqual(dhl.status(connection, NOW)['calls_today'], 1)

    def test_wrong_awb_and_unknown_dhl_piece_are_rejected_without_receipt(self):
        self.cycle()
        with self.db() as connection:
            other_id = self.insert(connection, OTHER)
            guide = reception.create_scanner_truck_guide(connection, 'qa', 'ADMINISTRADOR')['truck_guide']
            reception.add_scanned_truck_bl(connection, guide, OTHER, 'qa', 'ADMINISTRADOR')
            with self.assertRaisesRegex(ValueError, AWB):
                reception.scan_truck_package(connection, guide, other_id, PIECES[0], 'qa', 'ADMINISTRADOR')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM reception_truck_package_scans').fetchone()[0], 0)
            changes = connection.total_changes
            for code in ['OTHER-CARRIER-001', 'other-carrier-001']:
                with self.assertRaisesRegex(ValueError, 'no verificado'):
                    reception.scan_truck_package(connection, guide, other_id, code, 'qa', 'ADMINISTRADOR')
            self.assertEqual(connection.total_changes, changes)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM reception_truck_package_scans').fetchone()[0], 0)

    def test_rate_budget_and_restart_keep_counters(self):
        with self.db() as connection:
            self.insert(connection, OTHER)
        self.cycle()
        self.assertEqual(self.cycle(NOW + 5), (False, 0))
        with self.db() as connection:
            connection.execute('UPDATE dhl_tracking_runtime SET calls=200')
        self.assertEqual(self.cycle(NOW + 6), (False, 0))
        with self.db() as connection:
            dhl.retry_authorization(connection)
            dhl.init_schema(connection)
            self.assertEqual(dhl.status(connection, NOW)['calls_today'], 200)
        # New UTC date resets only the effective daily counter.
        self.assertEqual(self.cycle(NOW + 86400), (True, 1))

    def test_per_guide_daily_limit(self):
        with self.db() as connection:
            dhl.enqueue(connection, self.shipment, NOW)
            connection.execute("UPDATE dhl_tracking_jobs SET calls=10,day='2026-10-13'")
        self.assertEqual(self.cycle(), (False, 0))

    def test_authorization_stops_globally_and_redacts(self):
        with patch.object(dhl, 'fetch_tracking', side_effect=dhl.TrackingError('authorization')) as fetch:
            self.assertTrue(dhl.worker_cycle(self.app, NOW, date(2026, 10, 13)))
            self.assertFalse(dhl.worker_cycle(self.app, NOW + 6, date(2026, 10, 13)))
            self.assertEqual(fetch.call_count, 1)
        with self.db() as connection:
            status = dhl.status(connection, NOW)
            self.assertEqual(status['state'], 'authorization')
            self.assertNotIn('key_digest', status)
            self.assertNotIn(self.key_file.read_text(), json.dumps(status))
            with patch.object(dhl.time, 'time', return_value=NOW + 11):
                dhl.retry_authorization(connection)
        self.assertEqual(self.cycle(NOW + 12), (True, 1))

    def test_quota_backoff_and_network_errors_keep_cache(self):
        self.cycle()
        with self.db() as connection:
            other = self.insert(connection, OTHER)
            dhl.enqueue(connection, other, NOW + 6)
        with patch.object(dhl, 'fetch_tracking', side_effect=dhl.TrackingError('quota')):
            self.assertTrue(dhl.worker_cycle(self.app, NOW + 6, date(2026, 10, 13)))
        self.assertEqual(self.cycle(NOW + 3600), (False, 0))
        with self.db() as connection:
            self.assertEqual(dhl.shipment_status(connection, self.shipment, NOW + 3600)['total_pieces'], 2)

    def test_delivered_purges_even_disabled_missing_key_does_not_refetch(self):
        self.cycle(data=payload(delivered=True))
        self.assertEqual(self.cycle(NOW + 9 * 3600), (False, 0))
        later = NOW + 31 * 86400
        with patch.dict(os.environ, {'WMS_DHL_ENABLED': '0'}):
            self.assertEqual(self.cycle(later), (False, 0))
        with self.db() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM dhl_tracking_pieces').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM dhl_tracking_cache').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT state FROM dhl_tracking_jobs').fetchone()[0], 'expired')
        self.assertEqual(self.cycle(later + 6), (False, 0))

    def test_lease_recovery_and_cross_week_active_guide(self):
        self.cycle()
        with self.db() as connection:
            connection.execute("UPDATE dhl_tracking_jobs SET state='running',lease_until=?,next_at=?", (NOW + 90, NOW + 90))
        self.assertEqual(self.cycle(NOW + 91), (False, 0))
        self.assertEqual(self.cycle(NOW + 3600), (True, 1))
        self.assertEqual(self.cycle(NOW + 7 * 86400), (True, 1))

    def test_missing_configuration_no_http_and_safe_status(self):
        self.key_file.unlink()
        self.assertEqual(self.cycle(), (False, 0))
        with self.db() as connection:
            self.assertEqual(dhl.status(connection, NOW)['state'], 'configuration')
            status = dhl.shipment_status(connection, self.shipment, NOW)
            self.assertIn('clave', status['error'])
            self.assertFalse(status['pending'])

    def test_response_schema_is_conservative_and_missing_total_unknown(self):
        source = payload()
        source['shipments'][0]['details'] = {}
        result = dhl.parse_response(source, AWB, NOW)
        self.assertIsNone(result['total_pieces'])
        self.assertEqual(result['pieces'], [])
        for change in ('wrong_awb', 'wrong_service', 'invalid_total', 'invalid_piece', 'duplicate_awb'):
            with self.subTest(change=change):
                source = copy.deepcopy(payload())
                item = source['shipments'][0]
                if change == 'wrong_awb': item['id'] = OTHER
                if change == 'wrong_service': item['service'] = 'freight'
                if change == 'invalid_total': item['details']['totalNumberOfPieces'] = True
                if change == 'invalid_piece': item['details']['pieceIds'] = ['<script>']
                if change == 'duplicate_awb': source['shipments'].append(copy.deepcopy(item))
                with self.assertRaises(dhl.TrackingError): dhl.parse_response(source, AWB, NOW)

    def test_piece_normalization_is_specific_and_preserves_numeric_tail(self):
        for code in ('JD000001', 'JJD000001', '(J)JD000001', ' jjd 000001 '):
            with self.subTest(code=code):
                self.assertEqual(dhl.piece_code(code), 'JD000001')
                self.assertEqual(dhl.piece_aliases(code), ('JD000001', 'JJD000001', '(J)JD000001',
                    '*JD000001*', '*JJD000001*', '*(J)JD000001*'))
        for code in ('JVGL000001', 'JJDABC', 'JJJD000001', 'JJD000001X', 'JD-000001', '0012345678'):
            with self.subTest(code=code):
                self.assertEqual(dhl.piece_code(code), code)
                self.assertEqual(dhl.piece_aliases(code), (code,))
        self.assertNotEqual(dhl.piece_code('JJD00001'), dhl.piece_code('JD000001'))

    def test_response_deduplicates_aliases_before_validating_piece_total(self):
        source = copy.deepcopy(payload())
        source['shipments'][0]['details']['pieceIds'] = [PIECES[0], 'J' + PIECES[0], 'j' + PIECES[1].lower()]
        self.assertEqual(dhl.parse_response(source, AWB, NOW)['pieces'], PIECES)
        self.assertEqual(self.cycle(data=source), (True, 1))
        with self.db() as connection:
            self.assertEqual([r[0] for r in connection.execute('SELECT piece_id FROM dhl_tracking_pieces ORDER BY piece_id')], PIECES)

    def test_cached_aliases_for_same_owner_resolve_locally_but_conflicts_block(self):
        self.cycle()
        with self.db() as connection:
            connection.execute('INSERT INTO dhl_tracking_pieces(piece_id,awb) VALUES (?,?)', ('J' + PIECES[0], AWB))
            for code in (PIECES[0], 'J' + PIECES[0], '(J)' + PIECES[0]):
                self.assertEqual(dhl.piece_owner(connection, code, NOW), AWB)
            connection.execute('INSERT INTO dhl_tracking_cache(awb,status_code,checked_at,expires_at) VALUES (?,\'transit\',?,?)',
                               (OTHER, NOW, NOW + 86400))
            connection.execute('UPDATE dhl_tracking_pieces SET awb=? WHERE piece_id=?', (OTHER, 'J' + PIECES[0]))
            for code in (PIECES[0], 'J' + PIECES[0]):
                with self.assertRaisesRegex(ValueError, 'mas de una guia'):
                    dhl.piece_owner(connection, code, NOW)
                with self.assertRaisesRegex(ValueError, 'mas de una guia'):
                    dhl.verify_piece(connection, self.shipment, code, NOW)
            connection.execute('UPDATE dhl_tracking_cache SET expires_at=? WHERE awb=?', (NOW, OTHER))
            self.assertEqual(dhl.piece_owner(connection, 'J' + PIECES[0], NOW), AWB)
            connection.execute('UPDATE dhl_tracking_cache SET expires_at=?', (NOW,))
            self.assertIsNone(dhl.piece_owner(connection, 'J' + PIECES[0], NOW))

    def test_worker_alias_collision_preserves_legacy_cache_and_ownership(self):
        self.cycle()
        with self.db() as connection:
            connection.execute('UPDATE dhl_tracking_pieces SET piece_id=? WHERE piece_id=?', ('J' + PIECES[0], PIECES[0]))
            other = self.insert(connection, OTHER)
            dhl.enqueue(connection, other, NOW + 6)
            before = list(connection.execute('SELECT * FROM dhl_tracking_cache'))
        self.assertEqual(self.cycle(NOW + 6, payload(OTHER)), (True, 1))
        with self.db() as connection:
            self.assertEqual(list(connection.execute('SELECT * FROM dhl_tracking_cache')), before)
            self.assertEqual(dhl.piece_owner(connection, PIECES[0], NOW), AWB)
            self.assertEqual(connection.execute('SELECT error_code FROM dhl_tracking_jobs WHERE awb=?', (OTHER,)).fetchone()[0], 'conflict')

    def test_fetch_uses_header_no_redirect_and_safe_errors(self):
        for status, code in ((401,'authorization'), (403,'authorization'), (429,'quota'), (404,'not_found'), (500,'network')):
            with self.subTest(status=status), patch.object(dhl, 'build_opener') as opener:
                opener.return_value.open.side_effect = HTTPError(dhl.ENDPOINT, status, 'PRIVATE SECRET', {}, None)
                with self.assertRaises(dhl.TrackingError) as error:
                    dhl.fetch_tracking(AWB, 'test-value', NOW)
                self.assertEqual(error.exception.code, code)
                self.assertNotIn('PRIVATE', str(error.exception))
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('Dhl-api-key'), 'test-value')
                self.assertNotIn('test-value', request.full_url)
                self.assertIsNone(dhl._NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_collision_never_overwrites_other_guide(self):
        self.cycle()
        with self.db() as connection:
            other = self.insert(connection, OTHER)
            dhl.enqueue(connection, other, NOW + 6)
        self.cycle(NOW + 6, payload(OTHER))
        with self.db() as connection:
            self.assertEqual(connection.execute('SELECT awb FROM dhl_tracking_pieces WHERE piece_id=?', (PIECES[0],)).fetchone()[0], AWB)
            self.assertEqual(connection.execute('SELECT error_code FROM dhl_tracking_jobs WHERE awb=?', (OTHER,)).fetchone()[0], 'conflict')

    def test_backup_excludes_external_tracking_without_changing_source(self):
        from backend.maintenance import create_backup
        self.cycle(data=payload(delivered=True))
        with self.db() as connection:
            connection.execute('CREATE TABLE orders (id INTEGER PRIMARY KEY)')
            connection.execute('CREATE TABLE users (id INTEGER PRIMARY KEY)')
            # A physical observation belongs to the WMS, independently of DHL.
            connection.execute('CREATE TABLE qa_physical (code TEXT)')
            connection.execute('INSERT INTO qa_physical VALUES (?)', (PIECES[0],))
        backup = create_backup(self.path, Path(self.scratch.name) / 'backups')
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM dhl_tracking_cache').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM dhl_tracking_pieces').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT code FROM qa_physical').fetchone()[0], PIECES[0])
        connection.close()
        with self.db() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM dhl_tracking_cache').fetchone()[0], 1)

    def test_delivered_without_valid_date_not_retained(self):
        source = payload(delivered=True)
        source['shipments'][0]['status'].pop('timestamp')
        result = dhl.parse_response(source, AWB, NOW)
        self.assertEqual(result['expires_at'], NOW)
        source['shipments'][0]['events'] = [{'statusCode':'delivered','timestamp':'2026-10-12T10:00:00-05:00'}]
        result = dhl.parse_response(source, AWB, NOW)
        self.assertLess(result['expires_at'], NOW + 30 * 86400)

    def test_multiple_workers_share_inflight_lease(self):
        with self.db() as connection:
            self.insert(connection, OTHER)
        def fetch(awb, key, now):
            self.assertEqual(self.depth, 0)
            self.assertFalse(dhl.worker_cycle(self.app, NOW + 6, date(2026,10,13)))
            return dhl.parse_response(payload(awb), awb, now)
        with patch.object(dhl,'fetch_tracking',side_effect=fetch) as network:
            self.assertTrue(dhl.worker_cycle(self.app,NOW,date(2026,10,13)))
            self.assertEqual(network.call_count,1)

    def test_api_permissions_csrf_and_local_only_status(self):
        import io
        from backend import app, wsgi
        def call(path, method='GET', role='ADMINISTRADOR', headers=None):
            body = json.dumps({'shipment_id':self.shipment}).encode()
            environ = {'PATH_INFO':path, 'REQUEST_METHOD':method, 'wsgi.input':io.BytesIO(body),
                       'CONTENT_LENGTH':str(len(body)), 'HTTP_X_ROLE':role, 'HTTP_X_USER':'qa'}
            environ.update(headers or {})
            captured = {}
            content = b''.join(wsgi.application(environ, lambda status, values: captured.update(status=status,headers=values)))
            return captured['status'][:3], content
        with patch.object(app,'DB_PATH',self.path), patch.dict(os.environ,{'TRITON_AUTH_MODE':'demo'}), patch.object(dhl,'fetch_tracking') as network:
            self.assertEqual(call('/api/dhl-tracking/status',role='PICKER')[0],'403')
            self.assertEqual(call('/api/dhl-tracking/status',role='ASISTENTE_RECEPCION')[0],'403')
            self.assertEqual(call('/api/dhl-tracking/status')[0],'200')
            self.assertEqual(call('/api/dhl-tracking/shipment','POST')[0],'403')
            self.assertEqual(call('/api/dhl-tracking/shipment','POST',headers={'HTTP_X_WMS_REQUEST':'1','HTTP_SEC_FETCH_SITE':'cross-site'})[0],'403')
            self.assertEqual(call('/api/dhl-tracking/shipment','POST',headers={'HTTP_X_WMS_REQUEST':'1'})[0],'200')
            self.assertEqual(call('/api/dhl-tracking/retry','POST',role='AUXILIAR_RECEPCION',headers={'HTTP_X_WMS_REQUEST':'1'})[0],'403')
            self.assertEqual(call('/assets/dhl-status.js')[0],'200')
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
