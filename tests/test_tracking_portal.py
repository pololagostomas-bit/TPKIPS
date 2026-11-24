import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import app, password_policy, wsgi

class TrackingPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.original=app.DB_PATH;app.DB_PATH=Path(self.tmp.name)/'qa.db'
        self.env=patch.dict(os.environ,{'TRITON_AUTH_MODE':'local','TRITON_COOKIE_SECURE':'0','WMS_CLOUD_AUTO_SYNC':'0','WMS_TRANSFER_WORKER':'0','TRITON_MAIL_ENABLED':'0','TRITON_BOOTSTRAP_ADMIN_USERNAME':'admin.qa','TRITON_BOOTSTRAP_ADMIN_PASSWORD':'synthetic-admin-password'})
        self.env.start();password_policy.prepare()
        with app.db() as c:
            app.identity.save(c,{'username':'viewer.qa','display_name':'Commercial QA','role':'CONSULTA_TRACKING','password':'synthetic-viewer-password'},'admin.qa',app.ROLES)

    def tearDown(self):
        app.DB_PATH=self.original;self.env.stop();self.tmp.cleanup()

    def call(self,path,body=None,cookie='',csrf=True,origin='http://tracking.test',raw=False,headers=None):
        path,_,query=path.partition('?');content=json.dumps(body).encode() if body is not None else b''
        env={'PATH_INFO':path,'QUERY_STRING':query,'REQUEST_METHOD':'POST' if body is not None else 'GET','wsgi.input':io.BytesIO(content),'CONTENT_LENGTH':str(len(content)),'CONTENT_TYPE':'application/json','REMOTE_ADDR':'127.0.0.1','HTTP_HOST':'tracking.test','wsgi.url_scheme':'http','HTTP_COOKIE':cookie,'HTTP_ORIGIN':origin}
        if csrf:env['HTTP_X_WMS_REQUEST']='1'
        env.update(headers or {});response={}
        def start(status,hs):response.update(status=int(status.split()[0]),headers=dict(hs))
        response['raw']=b''.join((wsgi.application if raw else password_policy.application)(env,start))
        response['body']=json.loads(response['raw']) if response['headers'].get('Content-Type','').startswith('application/json') else response['raw']
        return response

    def login(self,username='viewer.qa',password='synthetic-viewer-password'):
        r=self.call('/tracking/api/login',{'username':username,'password':password});self.assertEqual(r['status'],200,r['body']);return r['headers']['Set-Cookie'].split(';')[0]

    def test_shell_has_no_operational_data_and_search_requires_real_session(self):
        self.assertEqual(self.call('/tracking')['status'],200)
        r=self.call('/tracking/api/search?type=OV&number=TEST-001',headers={'HTTP_X_ROLE':'CONSULTA_TRACKING','HTTP_X_USER':'viewer.qa'})
        self.assertEqual(r['status'],401)
        self.assertEqual(self.call('/tracking/not-a-file')['status'],404)

    def test_explicit_profile_and_raw_adapter_cannot_escape(self):
        cookie=self.login()
        self.assertEqual(self.call('/tracking/api/me',cookie=cookie)['body']['username'],'viewer.qa')
        for raw in (False,True):
            for path in ('/api/users','/api/orders','/api/account'):
                self.assertIn(self.call(path,cookie=cookie,raw=raw)['status'],(401,403),(path,raw))
        admin=self.login('admin.qa','synthetic-admin-password')
        self.assertEqual(self.call('/tracking/api/search?type=OV&number=TEST-001',cookie=admin)['status'],403)

    def test_csrf_and_password_rotation_policy_are_retained(self):
        for kwargs in ({'csrf':False},{'origin':'https://attacker.invalid'}):
            self.assertEqual(self.call('/tracking/api/login',{'username':'viewer.qa','password':'synthetic-viewer-password'},**kwargs)['status'],403)
        cookie=self.login()
        with app.db() as c:c.execute("UPDATE users SET must_change_password=1,temporary_password_expires_at=9999999999 WHERE username='viewer.qa'")
        r=self.call('/tracking/api/search?type=OV&number=TEST-001',cookie=cookie)
        self.assertEqual(r['status'],403);self.assertEqual(r['body']['code'],'PASSWORD_CHANGE_REQUIRED')
        r=self.call('/tracking/api/me',cookie=cookie);self.assertTrue(r['body']['must_change_password'])

    def test_revocation_and_no_demo_header_fallback(self):
        cookie=self.login()
        with app.db() as c:c.execute("UPDATE users SET active=0 WHERE username='viewer.qa'")
        self.assertEqual(self.call('/tracking/api/me',cookie=cookie)['status'],401)
        with patch.dict(os.environ,{'TRITON_AUTH_MODE':'demo'}):
            self.assertEqual(self.call('/tracking/api/search?type=OV&number=TEST-001',cookie=cookie)['status'],503)

    def test_duplicate_query_fields_and_post_search_are_rejected(self):
        cookie=self.login()
        self.assertEqual(self.call('/tracking/api/search?type=OV&type=OC&number=TEST-001',cookie=cookie)['status'],400)
        self.assertEqual(self.call('/tracking/api/search',{},cookie=cookie)['status'],405)

    def test_tls_termination_uses_server_cookie_policy_not_forwarded_headers(self):
        with patch.dict(os.environ,{'TRITON_COOKIE_SECURE':'1'}):
            r=self.call('/tracking/api/login',{'username':'viewer.qa','password':'synthetic-viewer-password'},origin='https://tracking.test')
            self.assertEqual(r['status'],200)
            self.assertIn('; Secure',r['headers']['Set-Cookie'])
            r=self.call('/tracking/api/login',{},origin='http://tracking.test',headers={'HTTP_X_FORWARDED_PROTO':'https'})
            self.assertEqual(r['status'],403)
