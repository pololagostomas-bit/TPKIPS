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

    def test_bulk_confirmation_validates_all_then_saves_only_this_arrivals_received_np(self):
        with app.db() as db:
            db.execute("UPDATE reception_attention_lines SET verified_qty=1,final_location='COUNT-B' WHERE attention_id=? AND reception_line_id=?",(self.aid,self.ids[1]))
        route=f'/api/receptions/{self.sid}/location-lines'
        locations=[{'line_id':lid,'final_location':value,'confirmed':True,'previous_location':previous,'previous_confirmed':False}
            for lid,value,previous in [(self.ids[0],'FINAL-A','COUNT-OLD'),(self.ids[1],'','COUNT-B')]]
        body={'attention_id':self.aid,'locations':locations}
        self.assertEqual(self.call(route,body,cookie=self.worker_cookie)['status'],400)
        with app.db() as db:
            row=db.execute('SELECT final_location,final_location_confirmed FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',(self.aid,self.ids[0])).fetchone()
            self.assertEqual(tuple(row),('COUNT-OLD',0))
        locations[1]['final_location']='FINAL-B'
        result=self.call(route,body,cookie=self.worker_cookie)
        self.assertEqual(result['status'],200)
        data=json.loads(result['body']);self.assertEqual(data['app_status'],'UBICACION')
        rows={line['id']:line for line in data['lines']}
        self.assertEqual([(rows[lid]['final_location'],rows[lid]['final_location_confirmed']) for lid in self.ids[:2]],[('FINAL-A',1),('FINAL-B',1)])
        self.assertTrue(all(not rows[lid]['final_location_confirmed'] for lid in self.ids[2:]))
