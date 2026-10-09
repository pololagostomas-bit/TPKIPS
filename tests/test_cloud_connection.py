"""Synthetic OAuth and Excel tests; no corporate account or production data."""
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from openpyxl import Workbook
from backend import app, password_policy as policy
from backend.services import cloud_auth as auth, cloud_sync as sync

TENANT = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
CLIENT = '11111111-2222-3333-4444-555555555555'


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GRAPH_TOKEN_CACHE_PATH': str(Path(self.folder.name)/'cache.json'),
            'GRAPH_TENANT_ID':TENANT, 'GRAPH_CLIENT_ID':CLIENT, 'GRAPH_CLIENT_SECRET':''})
        self.env.start()
        self.client = Mock()
        self.cache = Mock(has_state_changed=True)
        self.cache.serialize.return_value = '{"AccessToken":{"fake":"test-only"}}'
        self.factory = patch.object(auth, 'client', return_value=(self.client,self.cache))
        self.factory.start()
        self.client.initiate_device_flow.return_value = {'user_code':'QA-CODE','device_code':'SECRET-DEVICE',
            'expires_at':time.time()+300,'interval':5}

    def tearDown(self):
        self.factory.stop(); self.env.stop(); self.folder.cleanup()

    def pending(self):
        public = auth.begin('owner')
        with auth.locked():
            state = auth.read_state('pending.json'); state['next_poll']=0; auth.write_state('pending.json',state)
        return public

    def test_code_is_public_but_device_token_and_cache_are_not(self):
        result = self.pending()
        self.assertNotIn('SECRET-DEVICE',json.dumps(result))
        self.assertNotIn('device_code',json.dumps(auth.status()))
        self.assertEqual(result['verification_uri'],'https://microsoft.com/devicelogin')

    def test_only_owner_can_poll_or_cancel(self):
        flow = self.pending()
        for operation in [auth.poll,auth.cancel]:
            with self.assertRaises(auth.CloudAuthError): operation('other',flow['flow_id'])
        self.client.acquire_token_by_device_flow.assert_not_called()

    def test_second_flow_cannot_overwrite_pending(self):
        self.pending()
        with self.assertRaises(auth.CloudAuthError): auth.begin('other')

    def test_expired_code_is_removed(self):
        flow=self.pending()
        with patch.object(auth.time,'time',return_value=time.time()+1000):
            with self.assertRaises(auth.CloudAuthError): auth.poll('owner',flow['flow_id'])
        self.assertFalse(auth.read_state('pending.json'))

    def test_poll_respects_microsoft_interval(self):
        flow=auth.begin('owner')
        self.assertEqual(auth.poll('owner',flow['flow_id']),{'state':'pending'})
        self.client.acquire_token_by_device_flow.assert_not_called()

    def test_pending_is_not_success_and_does_not_save_cache(self):
        flow=self.pending(); self.client.acquire_token_by_device_flow.return_value={'error':'authorization_pending'}
        self.assertEqual(auth.poll('owner',flow['flow_id'])['state'],'pending')
        self.assertFalse(auth.cache_path().exists())

    def test_authorization_stays_server_side_and_disconnect_removes_it(self):
        flow=self.pending()
        self.client.acquire_token_by_device_flow.return_value={'access_token':'SECRET-ACCESS',
            'id_token_claims':{'tid':TENANT,'preferred_username':'fake@contoso.test'}}
        self.client.get_accounts.return_value=[{'home_account_id':'qa-account'}]
        result=auth.poll('owner',flow['flow_id'])
        self.assertEqual(result,{'state':'authorized'})
        self.assertTrue(auth.status()['authorized'])
        self.assertNotIn('SECRET-ACCESS',json.dumps(result))
        if os.name!='nt': self.assertEqual(auth.cache_path().stat().st_mode & 0o777,0o600)
        auth.disconnect(); self.assertFalse(auth.status()['authorized'])

    def test_wrong_tenant_cannot_save_cache(self):
        flow=self.pending()
        self.client.acquire_token_by_device_flow.return_value={'access_token':'fake', 'id_token_claims':{'tid':CLIENT}}
        with self.assertRaises(auth.CloudAuthError): auth.poll('owner',flow['flow_id'])
        self.assertFalse(auth.cache_path().exists())

    def test_silent_refresh_selects_saved_account_not_first_account(self):
        with auth.locked(): auth.write_state('account.json',{'home_account_id':'selected'})
        self.client.get_accounts.return_value=[{'home_account_id':'wrong'},{'home_account_id':'selected'}]
        self.client.acquire_token_silent.return_value={'access_token':'fake-token'}
        self.assertEqual(auth.access_token(),'fake-token')
        self.assertEqual(self.client.acquire_token_silent.call_args.kwargs['account']['home_account_id'],'selected')
        self.client.acquire_token_interactive.assert_not_called()

    def test_missing_or_revoked_account_never_opens_browser(self):
        self.client.get_accounts.return_value=[]
        with self.assertRaises(auth.CloudAuthError): auth.access_token()
        self.client.acquire_token_interactive.assert_not_called()
        self.client.initiate_device_flow.assert_not_called()

    def test_invalid_app_id_is_rejected(self):
        with self.assertRaises(auth.CloudAuthError): auth.configure('https://untrusted.test')

    def test_upstream_raw_error_is_not_exposed(self):
        flow=self.pending(); self.client.acquire_token_by_device_flow.return_value={
            'error':'access_denied','error_description':'PRIVATE-CREDENTIAL'}
        with self.assertRaises(auth.CloudAuthError) as result: auth.poll('owner',flow['flow_id'])
        self.assertNotIn('PRIVATE-CREDENTIAL',str(result.exception))


class CloudIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.old_db=app.DB_PATH
        app.DB_PATH=Path(self.folder.name)/'qa.db'
        self.env=patch.dict(os.environ, {'TRITON_AUTH_MODE':'local','TRITON_BOOTSTRAP_ADMIN_USERNAME':'admin.qa',
            'TRITON_BOOTSTRAP_ADMIN_PASSWORD':'synthetic-password-2026','WMS_CLOUD_AUTO_SYNC':'0',
            'GRAPH_TOKEN_CACHE_PATH':str(Path(self.folder.name)/'microsoft/cache.json'),
            'GRAPH_CLIENT_ID':'','GRAPH_TENANT_ID':TENANT,
            'GRAPH_SHARE_URL_IMPORTATION':'https://contoso.sharepoint.com/fake.xlsx',
            'GRAPH_SHARE_URL_ACCOUNTING':'','GRAPH_SHARE_URL_DISPATCH':'','GRAPH_SHARE_URL_STOCK':'',
            'POWERBI_STOCK_REPORT_ID':'fake-report'})
        self.env.start();policy.prepare()
        with app.db() as connection:
            token,_=app.identity.login(connection,'admin.qa','synthetic-password-2026')
            self.cookie=app.identity.COOKIE+'='+token
            app.identity.save(connection,{'username':'picker.qa','display_name':'QA', 'role':'PICKER',
                'password':'synthetic-picker-password'},'admin.qa',app.ROLES)

    def tearDown(self):
        self.env.stop();app.DB_PATH=self.old_db;self.folder.cleanup()

    def call(self,path,data=None,cookie=None,csrf=True):
        raw=json.dumps(data).encode() if data is not None else b''
        parsed=urlsplit(path)
        env={'PATH_INFO':parsed.path,'QUERY_STRING':parsed.query,'REQUEST_METHOD':'POST' if data is not None else 'GET',
            'wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw)), 'HTTP_COOKIE':cookie if cookie is not None else self.cookie,
            'HTTP_X_ROLE':'ADMINISTRADOR','HTTP_X_USER':'admin.qa','REMOTE_ADDR':'127.0.0.1'}
        if csrf:env['HTTP_X_WMS_REQUEST']='1'
        result={}
        def capture(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
        result['body']=b''.join(policy.application(env,capture))
        return result

    def test_admin_status_and_mobile_page(self):
        result=self.call('/api/cloud-connection/status');self.assertEqual(result['status'],200)
        body=json.loads(result['body']);self.assertFalse(body['authorized'])
        self.assertEqual(body['sources'][1]['pending'],'Modelo y permisos de Power BI')
        self.assertNotIn('sharepoint',result['body'].decode())
        self.assertEqual(self.call('/cloud-connection')['status'],200)

    def test_history_requires_admin_and_supports_safe_filters(self):
        sync._record(app,'importation','unchanged','Sin cambios.')
        result=self.call('/api/cloud-connection/history?source_type=importation&limit=1')
        self.assertEqual(result['status'],200)
        self.assertEqual(len(json.loads(result['body'])['items']),1)
        self.assertEqual(self.call('/api/cloud-connection/history',cookie='')['status'],401)
        self.assertEqual(self.call('/api/cloud-connection/history?limit=500')['status'],400)
        self.assertEqual(self.call('/api/cloud-connection/history',{})['status'],405)
        with app.db() as connection:token,_=app.identity.login(connection,'picker.qa','synthetic-picker-password')
        self.assertEqual(self.call('/api/cloud-connection/history',cookie=app.identity.COOKIE+'='+token)['status'],403)

    def test_purchase_panel_and_status_are_admin_only(self):
        self.assertEqual(self.call('/purchase-alerts')['status'], 200)
        self.assertEqual(self.call('/api/purchase-alerts/status')['status'], 200)
        self.assertEqual(self.call('/api/purchase-alerts/status', cookie='')['status'], 401)
        with app.db() as connection:
            token, _ = app.identity.login(connection, 'picker.qa', 'synthetic-picker-password')
        self.assertEqual(self.call('/api/purchase-alerts/status', cookie=app.identity.COOKIE + '=' + token)['status'], 403)

    def test_purchase_mutations_require_csrf_confirmation_and_changed_password(self):
        self.assertEqual(self.call('/api/purchase-alerts/settings', {}, csrf=False)['status'], 403)
        self.assertEqual(self.call('/api/purchase-alerts/send', {})['status'], 400)
        with app.db() as connection:
            connection.execute("UPDATE users SET must_change_password=1, temporary_password_expires_at=? WHERE username='admin.qa'", (time.time()+300,))
        self.assertEqual(self.call('/api/purchase-alerts/status')['status'], 403)

    def test_purchase_config_is_shared_without_operational_changes(self):
        before = self.call('/api/purchase-alerts/status')['body']
        self.assertNotIn('sharepoint', before.decode())
        result = self.call('/api/purchase-alerts/settings', {'sender':'owner@contoso.test','to':['buyer@contoso.test']})
        self.assertEqual(result['status'], 200)
        self.assertFalse(json.loads(result['body'])['settings']['enabled'])

    @patch.dict('os.environ', {'WMS_CLOUD_DISPATCH_MODE':'manual'})
    def test_ov_is_manual_and_not_reported_as_missing_link(self):
        payload=json.loads(self.call('/api/cloud-connection/status')['body'])
        ov=payload['sources'][0]
        self.assertEqual(ov['source_type'],'dispatch')
        self.assertEqual(ov['mode'],'manual')
        self.assertEqual(ov['pending'],'Carga manual')
        self.assertFalse(ov['configured'])

    def test_unauthenticated_cannot_use_forged_admin_headers(self):
        for path in ['/api/cloud-connection/status','/api/cloud-connection/start']:
            self.assertEqual(self.call(path,cookie='')['status'],401)

    def test_picker_is_forbidden_even_with_forged_role(self):
        with app.db() as connection:
            token,_=app.identity.login(connection,'picker.qa','synthetic-picker-password')
        self.assertEqual(self.call('/api/cloud-connection/status',cookie=app.identity.COOKIE+'='+token)['status'],403)

    def test_csrf_and_required_password_change_block_connection(self):
        self.assertEqual(self.call('/api/cloud-connection/start',{},csrf=False)['status'],403)
        with app.db() as connection:
            connection.execute("UPDATE users SET must_change_password=1,temporary_password_expires_at=? WHERE username='admin.qa'",(time.time()+600,))
        self.assertEqual(self.call('/api/cloud-connection/start',{})['status'],403)

    def source(self, quantity=2):
        workbook=Workbook();sheet=workbook.active
        sheet.append(['GUIA DE IMPORTACION','CODIGO','OV','MODO DE TRANSPORTE','CANTIDAD'])
        sheet.append(['QA-AWB','SKU-QA','QA-OV','AEREO',quantity])
        content=io.BytesIO();workbook.save(content);workbook.close()
        return {'source_type':'importation','filename':'qa.xlsx','content':content.getvalue(),
            'modified_at':'2026-09-01T21:00:00Z'}

    def test_repeat_hash_does_not_create_fake_new_cutoff_and_preserves_admin_state(self):
        source=self.source()
        with patch.object(sync.cloud_excel,'download_cloud_excels',return_value=[source]):
            result,code=sync.sync(app,'admin.qa');self.assertEqual(code,200,result)
            with app.db() as connection:
                connection.execute("UPDATE reception_shipments SET app_status='CERRADO',received_packages=3 WHERE bl_awb='QA-AWB'")
            source['modified_at']='2026-09-02T21:00:00Z'
            result,code=sync.sync(app,'admin.qa');self.assertEqual(code,200)
            self.assertEqual(result['sources'][0]['state'],'unchanged')
        with app.db() as connection:
            row=connection.execute("SELECT app_status,received_packages FROM reception_shipments WHERE bl_awb='QA-AWB'").fetchone()
            self.assertEqual(tuple(row),('CERRADO',3))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM data_imports').fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT cutoff_at FROM data_imports').fetchone()[0],'2026-09-01T16:00:00')

    def test_changed_file_preserves_admin_state_and_never_adds_stock(self):
        initial=self.source()
        with patch.object(sync.cloud_excel,'download_cloud_excels',return_value=[initial]):self.assertEqual(sync.sync(app,'admin.qa')[1],200)
        with app.db() as connection:
            connection.execute("UPDATE reception_shipments SET app_status='CERRADO',received_packages=3 WHERE bl_awb='QA-AWB'")
        revised=self.source(4);revised['modified_at']='2026-09-02T21:00:00Z'
        with patch.object(sync.cloud_excel,'download_cloud_excels',return_value=[revised]):self.assertEqual(sync.sync(app,'admin.qa')[1],200)
        with app.db() as connection:
            self.assertEqual(tuple(connection.execute("SELECT app_status,received_packages FROM reception_shipments WHERE bl_awb='QA-AWB'").fetchone()),('CERRADO',3))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM inventory_stock').fetchone()[0],0)

    def test_bad_excel_does_not_claim_success_or_modify_business_data(self):
        source=self.source();source['content']=b'not an excel'
        with patch.object(sync.cloud_excel,'download_cloud_excels',return_value=[source]):
            payload,code=sync.sync(app,'admin.qa');self.assertEqual(code,502);self.assertTrue(payload['failures'])
        with app.db() as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM data_imports').fetchone()[0],0)

    def test_one_source_failure_does_not_prevent_the_other(self):
        sources=[{'source_type':'accounting'},{'source_type':'importation'}]
        with patch.object(sync.cloud_excel,'configured_sources',return_value=sources), patch.object(
            sync.cloud_excel,'download_cloud_excels',side_effect=[sync.cloud_excel.CloudExcelError('Denied'),[self.source()]]):
            result,code=sync.sync(app,'admin.qa')
        self.assertEqual(code,502);self.assertEqual(len(result['sources']),1);self.assertEqual(len(result['failures']),1)


if __name__=='__main__':unittest.main()
