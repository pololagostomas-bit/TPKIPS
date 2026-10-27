"""Authenticated late-order plan route, with disposable database and cookies."""
import json
import unittest
from backend import app
from tests import test_cloud_connection as cloud_fixture
from tests.test_reception_partial_count_http import seed_partial


class CountPlanHTTPTests(unittest.TestCase):
    tearDown=cloud_fixture.CloudIntegrationTests.tearDown
    call=cloud_fixture.CloudIntegrationTests.call

    def setUp(self):
        cloud_fixture.CloudIntegrationTests.setUp(self)
        with app.db() as db:
            self.sid,self.aid,_=seed_partial(db)
            self.lid=db.execute('INSERT INTO reception_lines(shipment_id,np_code,expected_qty) VALUES (?,?,4)',
                                (self.sid,'QA-LATE-NP')).lastrowid

    def test_authenticated_route_adds_only_plan_and_rejects_replay_and_non_admin(self):
        route=f'/api/receptions/{self.sid}/count/include-lines'
        preview=json.loads(self.call(f'/api/receptions/{self.sid}?attention_id={self.aid}')['body'])['count_plan']
        body={'attention_id':self.aid,'line_ids':[self.lid],'state_token':preview['state_token'],
              'reason':'Review real physical arrival contents','confirmed':True}
        self.assertEqual(self.call(route,body,cookie='')['status'],401)
        with app.db() as db:
            token,_=app.identity.login(db,'picker.qa','synthetic-picker-password')
        self.assertEqual(self.call(route,body,cookie=app.identity.COOKIE+'='+token)['status'],403)
        result=self.call(route,body)
        self.assertEqual(result['status'],200)
        line=next(line for line in json.loads(result['body'])['lines'] if line['id']==self.lid)
        self.assertEqual((line['attention_planned_qty'],line['attention_verified_qty']),(4,0))
        self.assertFalse(line['np_scanned_at'])
        self.assertEqual(self.call(route,body)['status'],400)
