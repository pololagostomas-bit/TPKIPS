"""Authenticated progress writes with a temporary DB and synthetic identities."""
import json
import unittest
from backend import app
from tests import test_cloud_connection as cloud_fixture
from tests.test_reception_partial_count_http import seed_partial


class LocationProgressHTTPTests(unittest.TestCase):
    tearDown=cloud_fixture.CloudIntegrationTests.tearDown
    call=cloud_fixture.CloudIntegrationTests.call

    def setUp(self):
        cloud_fixture.CloudIntegrationTests.setUp(self)
        with app.db() as db:
            self.sid,self.aid,self.ids=seed_partial(db)
            db.execute("UPDATE reception_shipments SET app_status='UBICACION' WHERE id=?",(self.sid,))
            db.execute("UPDATE reception_attentions SET app_status='UBICACION' WHERE id=?",(self.aid,))
            db.execute("UPDATE reception_attention_lines SET verified_qty=0,np_unreceived_reason='Not received' WHERE attention_id=? AND reception_line_id<>?",(self.aid,self.ids[0]))
            db.execute("UPDATE reception_attention_lines SET final_location='COUNT-OLD',final_location_confirmed=0 WHERE attention_id=? AND reception_line_id=?",(self.aid,self.ids[0]))
            app.identity.save(db,{'username':'receiver','display_name':'QA worker','role':'ASISTENTE_RECEPCION',
                'password':'synthetic-worker-password'},'admin.qa',app.ROLES)
            token,_=app.identity.login(db,'receiver','synthetic-worker-password')
            self.worker_cookie=app.identity.COOKIE+'='+token

    def test_row_save_persists_then_guards_stale_requests_and_allows_validated_progress(self):
        route=f'/api/receptions/{self.sid}/location-lines'
        body={'attention_id':self.aid,'locations':[{'line_id':self.ids[0],'final_location':'REAL-BIN',
            'confirmed':True,'previous_location':'COUNT-OLD','previous_confirmed':False}]}
        self.assertEqual(self.call(route,body,cookie='')['status'],401)
        result=self.call(route,body,cookie=self.worker_cookie)
        self.assertEqual(result['status'],200)
        current=self.call(f'/api/receptions/{self.sid}?attention_id={self.aid}',cookie=self.worker_cookie)
        line=next(l for l in json.loads(current['body'])['lines'] if l['id']==self.ids[0])
        self.assertEqual((line['final_location'],line['final_location_confirmed']),('REAL-BIN',1))
        self.assertEqual(self.call(route,body,cookie=self.worker_cookie)['status'],400)
        self.assertEqual(self.call(f'/api/receptions/{self.sid}/status',{'attention_id':self.aid,'status':'VALIDACION'},cookie=self.worker_cookie)['status'],200)
        self.assertEqual(self.call(route,body,cookie=self.worker_cookie)['status'],403)
