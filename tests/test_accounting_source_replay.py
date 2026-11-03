"""One parser replay for an already registered source, not a new Excel cutoff."""
import hashlib
import unittest
from backend.services import cloud_sync as sync
from tests import test_cloud_history as fixtures


class SourceReplayTests(unittest.TestCase):
    setUp=fixtures.HistoryTests.setUp
    tearDown=fixtures.HistoryTests.tearDown
    make_app=fixtures.HistoryTests.make_app

    def test_unchanged_cut_reprocesses_once_without_duplicating_import(self):
        self.sources[0]['source_type']='accounting';self.source['source_type']='accounting'
        with self.app.db() as c:
            c.execute('CREATE TABLE reception_accounting_refs(id INTEGER PRIMARY KEY)')
            c.execute('INSERT INTO data_imports(source_type,file_hash,cutoff_at) VALUES(?,?,?)',
                ('accounting',hashlib.sha256(self.source['content']).hexdigest(),'2026-10-09T15:00:00'))
        def import_source(*args,**kwargs):
            self.assertTrue(kwargs.get('force'))
            with self.app.db() as c:
                c.execute('CREATE TABLE reception_accounting_source_state(id INTEGER PRIMARY KEY,revision INTEGER)')
                c.execute('INSERT INTO reception_accounting_source_state VALUES(1,1)')
            return {'rows':1}
        self.app.import_daily_excel.side_effect=import_source
        first,status=sync.sync(self.app,'qa')
        self.assertEqual(status,200)
        self.app.import_daily_excel.assert_called_once()
        second,status=sync.sync(self.app,'qa')
        self.assertEqual(status,200)
        self.assertEqual(second['sources'][0]['state'],'unchanged')
        self.app.import_daily_excel.assert_called_once()
        with self.app.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM data_imports').fetchone()[0],1)

    def test_failed_replay_is_not_marked_done_or_skipped_on_retry(self):
        self.sources[0]['source_type']='accounting';self.source['source_type']='accounting'
        with self.app.db() as c:
            c.execute('CREATE TABLE reception_accounting_refs(id INTEGER PRIMARY KEY)')
            c.execute('INSERT INTO data_imports(source_type,file_hash,cutoff_at) VALUES(?,?,?)',
                ('accounting',hashlib.sha256(self.source['content']).hexdigest(),'2026-10-09T15:00:00'))
        self.app.import_daily_excel.side_effect=ValueError('synthetic parser failure')
        self.assertEqual(sync.sync(self.app,'qa')[1],502)
        self.assertEqual(sync.sync(self.app,'qa')[1],502)
        self.assertEqual(self.app.import_daily_excel.call_count,2)
