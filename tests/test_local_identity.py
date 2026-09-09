"""Integration tests of sessions and existing business routes through WSGI."""
import io
import json
import os
import uuid
import unittest
from unittest.mock import patch
from backend import app, wsgi


class LocalIdentityTest(unittest.TestCase):
    def setUp(self):
        self.original_db=app.DB_PATH
        self.path=app.ROOT/'qa'/'runtime'/('auth-'+uuid.uuid4().hex+'.db')
        app.DB_PATH=self.path
        self.environment=patch.dict(os.environ,{'TRITON_AUTH_MODE':'local','TRITON_MAIL_ENABLED':'0',
            'TRITON_BOOTSTRAP_ADMIN_USERNAME':'admin.qa','TRITON_BOOTSTRAP_ADMIN_PASSWORD':'qa-password-2026'})
        self.environment.start()
        wsgi.prepare()

    def tearDown(self):
        self.environment.stop()
        app.DB_PATH=self.original_db
        self.path.unlink(missing_ok=True)

    def call(self,path,body=None,cookie='',role='',csrf=True):
        content=json.dumps(body).encode() if body is not None else b''
        path,_,query=path.partition('?')
        environ={'PATH_INFO':path,'QUERY_STRING':query,'REQUEST_METHOD':'POST' if body is not None else 'GET',
            'wsgi.input':io.BytesIO(content),'CONTENT_LENGTH':str(len(content)),
            'CONTENT_TYPE':'application/json','REMOTE_ADDR':'127.0.0.1','HTTP_COOKIE':cookie,
            'HTTP_X_ROLE':role,'HTTP_X_USER':'admin.qa'}
        if csrf:environ['HTTP_X_WMS_REQUEST']='1'
        result={}
        def response(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
        raw=b''.join(wsgi.application(environ,response))
        result['body']=json.loads(raw) if raw and result['headers'].get('Content-Type','').startswith('application/json') else raw
        return result

    def login(self,username='admin.qa',password='qa-password-2026'):
        result=self.call('/api/login',dict(username=username,password=password))
        self.assertEqual(result['status'],200,result)
        return result['headers']['Set-Cookie'].split(';')[0]

    def create_picker(self,cookie):
        result=self.call('/api/users',dict(username='picker.qa',display_name='Picker de prueba',role='PICKER',shift='NOCHE',password='picker-password-2026'),cookie)
        self.assertEqual(result['status'],200,result)
        self.assertNotIn('password_hash',result['body'])

    def test_session_roles_deactivation_and_persistence(self):
        self.assertEqual(self.call('/api/me',role='ADMINISTRADOR')['status'],401)
        self.assertEqual(self.call('/')['status'],303)
        admin=self.login(); self.create_picker(admin)
        picker=self.login('picker.qa','picker-password-2026')
        self.assertEqual(self.call('/api/me',cookie=picker,role='ADMINISTRADOR')['body']['role'],'PICKER')
        for url in ['/api/users','/api/notifications','/api/reports/workload','/api/receptions']:
            self.assertEqual(self.call(url,cookie=picker,role='ADMINISTRADOR')['status'],403,url)
        wsgi.prepare()
        self.assertEqual(self.call('/api/me',cookie=admin)['status'],200)
        self.assertEqual(len(self.call('/api/users',cookie=admin)['body']['users']),2)
        self.assertEqual(self.call('/api/users/picker.qa/deactivate',{},admin)['status'],200)
        self.assertEqual(self.call('/api/me',cookie=picker)['status'],401)
        with app.db() as connection:
            self.assertGreater(connection.execute('SELECT COUNT(*) FROM user_audit').fetchone()[0],3)

    def test_password_role_change_revokes_and_last_admin_protected(self):
        admin=self.login(); self.create_picker(admin)
        picker=self.login('picker.qa','picker-password-2026')
        update=self.call('/api/users',dict(username='picker.qa',display_name='Nuevo nombre',role='GUIADOR',shift='DÍA'),admin)
        self.assertEqual(update['status'],200)
        self.assertEqual(self.call('/api/me',cookie=picker)['status'],401)
        self.assertEqual(self.call('/api/users/admin.qa/deactivate',{},admin)['status'],400)
        self.assertEqual(self.call('/api/users',dict(username='admin.qa',display_name='Admin',role='PICKER'),admin)['status'],400)
        self.assertEqual(self.call('/api/users',dict(username='bad',display_name='Sin clave',role='PICKER'),admin)['status'],400)
        self.assertEqual(self.call('/api/logout',{},admin)['status'],200)
        self.assertEqual(self.call('/api/me',cookie=admin)['status'],401)

    def test_csrf_throttling_and_cookie(self):
        self.assertEqual(self.call('/api/login',dict(username='admin.qa',password='qa-password-2026'),csrf=False)['status'],403)
        result=self.call('/api/login',dict(username='admin.qa',password='qa-password-2026'))
        self.assertIn('HttpOnly',result['headers']['Set-Cookie'])
        self.assertIn('SameSite=Strict',result['headers']['Set-Cookie'])
        for _ in range(5):self.assertEqual(self.call('/api/login',dict(username='wrong',password='incorrect'))['status'],401)
        with app.db() as connection:
            self.assertEqual(connection.execute('SELECT failures FROM login_attempts').fetchone()[0],5)

    def test_reception_creation_query_does_not_change_inventory(self):
        admin=self.login()
        with app.db() as connection:
            before=[tuple(r) for r in connection.execute('SELECT * FROM inventory_stock')]
        response=self.call('/api/receptions',dict(bl_awb='BL-LOCAL-QA',transport_type='AEREO'),admin)
        self.assertEqual(response['status'],201,response)
        result=self.call('/api/receptions?search=BL-LOCAL-QA',cookie=admin)
        self.assertEqual(result['status'],200)
        self.assertEqual(len(result['body']),1)
        self.assertEqual(self.call('/api/reports/workload?period=week',cookie=admin)['body']['targets']['period_ovs'],100)
        self.assertEqual(self.call('/api/notifications',cookie=admin)['body']['configured'],False)
        with app.db() as connection:
            self.assertEqual(before,[tuple(r) for r in connection.execute('SELECT * FROM inventory_stock')])


if __name__=='__main__':unittest.main()
