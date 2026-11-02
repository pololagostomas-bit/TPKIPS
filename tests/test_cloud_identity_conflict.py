"""Typed identity conflicts never masquerade as bad Excel columns or leak cells."""
import json
import unittest
from backend.services import cloud_sync as sync
from backend.services.reception_line_identity import ImportLineConflict
from tests import test_cloud_history as fixtures


class CloudIdentityTests(unittest.TestCase):
    setUp=fixtures.HistoryTests.setUp
    tearDown=fixtures.HistoryTests.tearDown
    make_app=fixtures.HistoryTests.make_app
    records=fixtures.HistoryTests.records

    def test_conflict_is_typed_redacted_and_preserves_success(self):
        self.assertEqual(sync.sync(self.app,'qa')[1],200)
        before=self.records()[0]
        self.source['content']=b'changed synthetic cut'
        self.app.import_daily_excel.side_effect=ImportLineConflict('PRIVATE-CELL private-buyer row123')
        payload,status=sync.sync(self.app,'qa')
        self.assertEqual(status,502)
        self.assertEqual(payload['failures'][0]['error_code'],'identity_conflict')
        current=self.records()[0]
        self.assertEqual(current['error_code'],'identity_conflict')
        self.assertNotIn('PRIVATE-CELL',json.dumps([payload,self.records()]))
        with self.app.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM data_imports').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT updated_at FROM cloud_sync_status').fetchone()[0],before['checked_at'])
