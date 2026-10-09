"""Private temporary databases, synthetic files and mocked Microsoft only."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
from backend.services import cloud_auth, cloud_excel, cloud_sync as sync


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'history.db'
        self.app = self.make_app(self.path)
        self.sources = [{'source_type':'importation','filename':'qa-import.xlsx'}]
        self.source = {**self.sources[0], 'content':b'fake-excel', 'modified_at':'2026-10-09T20:00:00Z'}
        self.auth = {'configured':True,'authorized':True,'pending':False,'authorization_at':0}
        self.patches = [patch.object(sync.cloud_excel,'configured_sources',return_value=self.sources),
            patch.object(sync.cloud_excel,'download_cloud_excels',return_value=[self.source]),
            patch.object(sync.cloud_auth,'status',side_effect=lambda:dict(self.auth)),
            patch.dict(os.environ, {'WMS_CLOUD_AUTO_SYNC':'1','WMS_CLOUD_INTERVAL_SECONDS':'300',
                                   'WMS_CLOUD_DISPATCH_MODE':'manual'})]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.folder.cleanup()

    def make_app(self, path):
        @contextmanager
        def db():
            connection=sqlite3.connect(path);connection.row_factory=sqlite3.Row
            try:
                with connection:yield connection
            finally:connection.close()
        with db() as connection:
            sync.init_schema(connection)
            connection.execute('CREATE TABLE data_imports(id INTEGER PRIMARY KEY,source_type TEXT,file_hash TEXT,cutoff_at TEXT)')
        def importer(content, filename, source, cutoff, *args, **kwargs):
            with db() as connection:
                connection.execute('INSERT INTO data_imports(source_type,file_hash,cutoff_at) VALUES(?,?,?)',
                    (source,hashlib.sha256(content).hexdigest(),cutoff))
            return {'rows':2}
        return SimpleNamespace(db=db,import_daily_excel=Mock(side_effect=importer))

    def records(self, query=''):
        return sync.history(self.app,query)['items']

    def record(self, state='unchanged', source='importation', **kwargs):
        sync._record(self.app,source,state,'Synthetic result',**kwargs)

    def test_updated_then_unchanged_are_two_events_but_one_import(self):
        self.assertEqual(sync.sync(self.app,'admin.qa')[1],200)
        first=sync.status(self.app)['sources'][2]
        self.assertEqual(sync.sync(self.app,'system.cloud-sync',origin='automatic')[1],200)
        records=self.records()
        self.assertEqual([r['state'] for r in records],['unchanged','updated'])
        self.assertEqual(records[0]['origin'],'automatic')
        self.assertEqual(records[1]['import_id'],1)
        self.assertEqual(records[1]['rows_count'],2)
        self.assertEqual(records[0]['cutoff_at'],'2026-10-09T15:00:00')
        self.assertEqual(sync.status(self.app)['sources'][2]['updated_at'],first['updated_at'])
        self.app.import_daily_excel.assert_called_once()

    def test_failed_file_preserves_last_success_and_redacts_raw_error(self):
        sync.sync(self.app,'admin.qa')
        previous=sync.status(self.app)['sources'][2]
        with patch.object(sync.cloud_excel,'download_cloud_excels',side_effect=cloud_excel.CloudExcelError(
                'https://private.test?token=PRIVATE-CREDENTIAL','forbidden')):
            result,code=sync.sync(self.app,'admin.qa')
        self.assertEqual(code,502)
        self.assertEqual(result['failures'][0]['error_code'],'forbidden')
        latest=sync.status(self.app)['sources'][2]
        self.assertEqual(latest['success_at'],previous['success_at'])
        self.assertEqual(latest['updated_at'],previous['updated_at'])
        self.assertNotIn('PRIVATE-CREDENTIAL',json.dumps(self.records()))
        self.assertTrue(self.records()[0]['action'])

    def test_parser_failure_still_distinguishes_successful_remote_access(self):
        self.app.import_daily_excel.side_effect=ValueError('PRIVATE-CELL')
        self.assertEqual(sync.sync(self.app,'admin.qa')[1],502)
        row=self.records()[0]
        self.assertEqual(row['error_code'],'import_error')
        self.assertTrue(row['remote_accessed'])
        self.assertEqual(sync.status(self.app)['connection']['state'],'verified')
        self.assertNotIn('PRIVATE-CELL',json.dumps(row))

    def test_failed_download_keeps_real_last_known_filename_not_placeholder(self):
        self.sources[0]['filename']='wrong-placeholder.xlsx'
        sync.sync(self.app,'admin.qa')
        with patch.object(sync.cloud_excel,'download_cloud_excels',side_effect=cloud_excel.CloudExcelError('Timeout','network')):
            sync.sync(self.app,'admin.qa')
        self.assertEqual(self.records()[0]['filename'],'qa-import.xlsx')
        self.assertEqual(sync.status(self.app)['sources'][2]['filename'],'qa-import.xlsx')

    def test_history_persists_and_is_per_operational_database(self):
        self.record()
        other=self.make_app(Path(self.folder.name)/'other.db')
        self.assertEqual(sync.history(other,'')['items'],[])
        with self.app.db() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM cloud_sync_history').fetchone()[0],1)

    def test_filters_and_cursor_remain_stable_when_new_entries_arrive(self):
        for i in range(6): self.record('error' if i%2 else 'updated')
        first=sync.history(self.app,'state=updated&limit=2')
        self.assertEqual([r['id'] for r in first['items']],[5,3])
        self.record('updated')
        second=sync.history(self.app,'state=updated&limit=2&before='+str(first['next_before']))
        self.assertEqual([r['id'] for r in second['items']],[1])
        self.assertIsNone(second['next_before'])
        self.assertEqual(self.records('source_type=accounting'),[])

    def test_history_rejects_invalid_or_duplicate_filters(self):
        for query in ['source_type=bad','state=bad','limit=0','limit=101','before=-1',
                      'before=9223372036854775808','limit=x','token=private','state=error&state=updated']:
            with self.subTest(query=query),self.assertRaises(ValueError):sync.history(self.app,query)

    def test_retention_is_bounded_without_deleting_imports(self):
        sync.sync(self.app,'admin.qa')
        old=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
        with self.app.db() as connection:connection.execute('UPDATE cloud_sync_history SET checked_at=?',(old,))
        with patch.object(sync,'HISTORY_LIMIT',3):
            for _ in range(5):self.record()
        self.assertEqual(len(self.records()),3)
        with self.app.db() as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM data_imports').fetchone()[0],1)

    def test_legacy_status_migrates_idempotently_without_inventing_history(self):
        with self.app.db() as connection:
            connection.execute('DROP TABLE cloud_sync_status')
            connection.execute('CREATE TABLE cloud_sync_status(source_type TEXT PRIMARY KEY,checked_at TEXT,success_at TEXT,state TEXT,detail TEXT)')
            connection.execute("INSERT INTO cloud_sync_status VALUES('importation','2026-10-08T10:00:00','2026-10-08T10:00:00','updated','Legacy')")
            sync.init_schema(connection);sync.init_schema(connection)
            row=dict(connection.execute('SELECT * FROM cloud_sync_status').fetchone())
        self.assertEqual(row['detail'],'Legacy')
        self.assertIsNone(row['updated_at'])
        self.assertEqual(self.records(),[])

    def test_saved_authorization_is_not_reported_as_verified(self):
        self.assertEqual(sync.status(self.app)['connection']['state'],'unverified')
        self.assertEqual(sync.status(self.app)['monitor']['state'],'starting')

    def test_revoked_authorization_is_visible_despite_saved_cache(self):
        sync.sync(self.app,'admin.qa')
        with patch.object(sync.cloud_excel,'download_cloud_excels',side_effect=cloud_excel.CloudExcelError('Unauthorized','authorization_required')):
            sync.sync(self.app,'admin.qa')
        self.assertEqual(sync.status(self.app)['connection']['state'],'authorization_required')
        self.assertTrue(sync.status(self.app)['authorized'])
        self.auth['authorization_at']=sync.time.time()+1
        self.assertEqual(sync.status(self.app)['connection']['state'],'unverified')

    def test_network_failure_does_not_claim_expired_account(self):
        with patch.object(sync.cloud_excel,'download_cloud_excels',side_effect=cloud_excel.CloudExcelError('Timeout','network')):
            sync.sync(self.app,'admin.qa')
        result=sync.status(self.app)
        self.assertEqual(result['connection']['state'],'unavailable')
        self.assertTrue(result['authorized'])

    def test_stale_worker_and_source_are_visible(self):
        sync.sync(self.app,'admin.qa')
        old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        sync._runtime(self.app,heartbeat_at=old,worker_state='waiting',next_check_at=old)
        with self.app.db() as connection:connection.execute('UPDATE cloud_sync_status SET checked_at=?',(old,))
        result=sync.status(self.app)
        self.assertEqual(result['monitor']['state'],'stale')
        self.assertEqual(result['sources'][2]['health'],'stale')

    def test_unauthorized_worker_records_blocked_without_downloading(self):
        self.auth['authorized']=False
        sync._worker_cycle(self.app)
        row=self.records()[0]
        self.assertEqual(row['state'],'blocked')
        self.assertFalse(row['remote_accessed'])
        sync.cloud_excel.download_cloud_excels.assert_not_called()
        result=sync.status(self.app)
        self.assertEqual(result['monitor']['state'],'blocked')
        self.assertTrue(result['monitor']['next_check_at'])

    def test_worker_failure_exposes_safe_error_and_next_check(self):
        with patch.object(sync,'sync',side_effect=RuntimeError('SECRET-TOKEN')):sync._worker_cycle(self.app)
        result=sync.status(self.app)
        self.assertEqual(result['monitor']['state'],'error')
        self.assertNotIn('SECRET-TOKEN',json.dumps(result))
        self.assertTrue(result['monitor']['next_check_at'])

    def test_missing_registration_has_configuration_diagnostic(self):
        self.auth.update(authorized=False,configured=False)
        sync._worker_cycle(self.app)
        self.assertEqual(self.records()[0]['error_code'],'configuration')
        self.assertEqual(sync.status(self.app)['connection']['state'],'not_configured')

    def test_busy_auth_cache_is_not_mislabelled_as_expired_account(self):
        with patch.object(sync.cloud_auth,'status',side_effect=cloud_auth.CloudAuthError('Busy','busy')):
            sync._worker_cycle(self.app)
            result=sync.status(self.app)
        self.assertEqual(self.records()[0]['error_code'],'busy')
        self.assertEqual(result['connection']['state'],'unavailable')
        self.assertIn('no necesitas desconectar',result['connection']['action'])

    def test_interrupted_run_is_recorded_once_after_restart(self):
        sync._runtime(self.app,running=True,active_source='importation',origin='automatic',cycle_started_at=sync._stamp())
        sync._recover_runtime(self.app);sync._recover_runtime(self.app)
        self.assertEqual(len(self.records()),1)
        self.assertEqual(self.records()[0]['state'],'interrupted')
        self.assertFalse(sync._runtime(self.app)['running'])

    def test_sync_busy_does_not_invent_an_import_or_history_entry(self):
        with sync._sync_lock:self.assertEqual(sync.sync(self.app,'admin.qa')[1],409)
        self.assertEqual(self.records(),[])

    def test_status_is_read_only_and_does_not_refresh_token_or_download(self):
        for _ in range(2):sync.status(self.app)
        sync.cloud_excel.download_cloud_excels.assert_not_called()
        self.assertEqual(self.records(),[])

    def test_force_attempt_is_identified_and_runtime_clears(self):
        sync.sync(self.app,'admin.qa',force=True)
        self.assertTrue(self.records()[0]['forced'])
        self.assertFalse(sync._runtime(self.app)['running'])


class DiagnosticTests(unittest.TestCase):
    def test_http_codes_have_typed_safe_diagnostics(self):
        for status,expected in [(401,'authorization_required'),(403,'forbidden'),(404,'file_missing'),
                                (429,'throttled'),(503,'microsoft_unavailable')]:
            with self.subTest(status=status),patch.object(cloud_excel.requests,'get',return_value=Mock(status_code=status)):
                with self.assertRaises(cloud_excel.CloudExcelError) as result:cloud_excel._graph_get('https://example.test',{})
                self.assertEqual(result.exception.code,expected)

    def test_timeout_and_auth_wrapping_preserve_categories(self):
        with patch.object(cloud_excel.requests,'get',side_effect=requests.Timeout('SECRET')):
            with self.assertRaises(cloud_excel.CloudExcelError) as result:cloud_excel._graph_get('https://example.test',{})
            self.assertEqual(result.exception.code,'network')
        with patch.object(cloud_excel.cloud_auth,'access_token',side_effect=cloud_auth.CloudAuthError('Reconnect','authorization_required')):
            with self.assertRaises(cloud_excel.CloudExcelError) as result:cloud_excel._access_token()
            self.assertEqual(result.exception.code,'authorization_required')


if __name__=='__main__':unittest.main()
