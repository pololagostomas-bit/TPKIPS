"""Fictitious SQLite/local-auth tests. Mail and Microsoft authorization are mocked."""
import hashlib
import io
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from backend import app, password_policy
from backend.services import reception, reception_transfer as transfer


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='wms-transfer-test-'))
        cls.seed = cls.root / 'seed.sqlite'
        with patch.object(app, 'DB_PATH', cls.seed), patch.dict(os.environ, {'TRITON_AUTH_MODE':'demo'}):
            app.init_db()
            with app.db() as db:
                password_policy.init_schema(db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def setUp(self):
        self.path = self.root / (secrets.token_hex(6) + '.sqlite')
        shutil.copyfile(self.seed, self.path)
        self.env = patch.dict(os.environ, {'TRITON_AUTH_MODE':'local','WMS_TRANSFER_WORKER':'0','TRITON_MAIL_ENABLED':'0'})
        self.env.start()
        self.db_patch = patch.object(app, 'DB_PATH', self.path)
        self.db_patch.start()
        self.addCleanup(self.env.stop);self.addCleanup(self.db_patch.stop)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.sid = self.db.execute("""INSERT INTO reception_shipments(bl_awb,app_status,em_number,created_at,updated_at)
            VALUES('QA-BL','SOLICITUD TRANSFERENCIA','QA-EM','2026-10-13','2026-10-13')""").lastrowid
        self.aid = self.db.execute("""INSERT INTO reception_attentions(shipment_id,sequence_no,app_status,condition_status,created_at,updated_at)
            VALUES(?,1,'SOLICITUD TRANSFERENCIA','EN PROCESO','2026-10-13','2026-10-13')""", (self.sid,)).lastrowid
        self.config = {'enabled':True,'sender':'sender@example.test','recipient':'recipient@example.test','public_origin':'https://wms.example.test'}
        transfer.save_settings(self.db, self.config)
        self.db.commit()

    def token(self, aid=None):
        aid = self.aid if aid is None else aid
        transfer.enqueue(self.db, self.sid, aid)
        raw = secrets.token_urlsafe(32)
        self.db.execute("""UPDATE reception_transfer_requests SET status='ACCEPTED',token_hash=?,expires_at=?
            WHERE id=(SELECT MAX(id) FROM reception_transfer_requests)""",
            (hashlib.sha256(raw.encode()).hexdigest(), time.time()+3600))
        self.db.commit()
        return raw

    def request(self, path, method='POST', data=None, extra=None):
        body = json.dumps(data or {}).encode()
        environ = {'REQUEST_METHOD':method,'PATH_INFO':path,'QUERY_STRING':'',
            'wsgi.input':io.BytesIO(body),'CONTENT_LENGTH':str(len(body)),'CONTENT_TYPE':'application/json',
            'REMOTE_ADDR':'127.0.0.1','HTTP_X_WMS_REQUEST':'1','HTTP_SEC_FETCH_SITE':'same-origin',
            'SERVER_NAME':'localhost','SERVER_PORT':'80','wsgi.url_scheme':'http',**(extra or {})}
        captured = {}
        def start(status, headers):
            captured.update(status=int(status.split()[0]),headers=dict(headers))
        output = b''.join(password_policy.application(environ,start))
        return captured['status'], captured['headers'], output

    def test_configuration_fails_closed_and_rejects_host_header_style_urls(self):
        for origin in ['http://wms.example.test','https://user:pw@wms.example.test','https://wms.example.test/evil','https://wms.example.test?x=1','https://wms.example.test#token=x']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                transfer.save_settings(self.db,{**self.config,'public_origin':origin})
        for mail in ['one@example.test; two@example.test','name <one@example.test>','a@b.test\r\nBcc: x@y.test']:
            with self.assertRaises(ValueError):
                transfer.save_settings(self.db,{**self.config,'recipient':mail})
        with self.assertRaises(ValueError):
            transfer.save_settings(self.db,{**self.config,'enabled':True,'sender':''})

    def test_inspection_does_not_confirm_and_exposes_only_scoped_summary(self):
        raw = self.token()
        result = transfer.inspect_token(self.db,raw)
        self.assertEqual(set(result),{'confirmed','bl_awb','em_number','attention','expires_at'})
        self.assertFalse(result['confirmed'])
        self.assertEqual(self.db.execute('SELECT transfer_assistant_checked FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],0)

    def test_expiry_unknown_and_bad_tokens_reject_without_mutation(self):
        raw = self.token()
        for value, now in [(raw,time.time()+7200),('x'*43,time.time()),(None,time.time()),('bad',time.time())]:
            with self.assertRaises(ValueError): transfer.inspect_token(self.db,value,now)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_history WHERE event_type=\'TRANSFERENCIA\'').fetchone()[0],0)

    def test_strict_check_one_use_and_no_automatic_bl_closure(self):
        raw = self.token()
        for value in [False,'true',1,None]:
            with self.assertRaises(ValueError): transfer.confirm_token(self.db,raw,value)
        self.assertTrue(transfer.confirm_token(self.db,raw,True)['confirmed'])
        self.assertTrue(transfer.confirm_token(self.db,raw,True)['confirmed'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='TRANSFERENCIA'").fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],transfer.STAGE)
        self.assertNotIn(raw,'\n'.join(self.db.iterdump()))

    def test_second_arrival_is_not_confirmed_by_first_or_shared_flag(self):
        raw = self.token()
        other = self.db.execute("""INSERT INTO reception_attentions(shipment_id,sequence_no,app_status,condition_status,created_at,updated_at)
            VALUES(?,2,'SOLICITUD TRANSFERENCIA','EN PROCESO','2026-10-13','2026-10-13')""",(self.sid,)).lastrowid
        transfer.confirm_token(self.db,raw,True)
        self.assertEqual(self.db.execute('SELECT transfer_assistant_checked FROM reception_attentions WHERE id=?',(other,)).fetchone()[0],0)
        with self.assertRaises(PermissionError):
            reception.change_reception_status(self.db,self.sid,{'attention_id':other,'status':'CERRADO'},'qa','ADMINISTRADOR')

    def test_admin_override_requires_admin_reason_and_preserves_audit(self):
        self.token()
        for role, data, error in [('ASISTENTE_RECEPCION',{'checked':True},PermissionError),
                                  ('ADMINISTRADOR',{'checked':True},ValueError),
                                  ('ADMINISTRADOR',{'checked':'true','reason':'QA reason'},ValueError)]:
            with self.assertRaises(error): reception.confirm_reception_transfer(self.db,self.sid,data,'qa',role)
        reception.confirm_reception_transfer(self.db,self.sid,{'checked':True,'reason':'QA SAP verificado','attention_id':self.aid},'qa','ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT transfer_assistant_checked FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT status FROM reception_transfer_requests').fetchone()[0],'REVOKED')

    def test_reopen_revokes_token_and_new_cycle_uses_new_request(self):
        raw = self.token()
        reception.rewind_reception_stage(self.db,self.sid,{'status':'VALIDACION','reason':'QA revalidar','attention_id':self.aid},'qa','ADMINISTRADOR')
        with self.assertRaises(ValueError): transfer.inspect_token(self.db,raw)
        reception.change_reception_status(self.db,self.sid,{'status':transfer.STAGE,'validation_result':'CONFORME','attention_id':self.aid},'qa','ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_transfer_requests').fetchone()[0],2)
        with self.assertRaises(ValueError): transfer.confirm_token(self.db,raw,True)

    def test_new_transition_enqueues_once_without_legacy_mail_or_backfill(self):
        self.db.execute("UPDATE reception_shipments SET app_status='VALIDACION' WHERE id=?",(self.sid,))
        self.db.execute("UPDATE reception_attentions SET app_status='VALIDACION' WHERE id=?",(self.aid,))
        reception.change_reception_status(self.db,self.sid,{'status':transfer.STAGE,'validation_result':'CONFORME','attention_id':self.aid},'qa','ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_transfer_requests').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_notifications WHERE notification_type='SOLICITUD_TRANSFERENCIA'").fetchone()[0],0)
        transfer.init_schema(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reception_transfer_requests').fetchone()[0],1)

    def test_guest_routes_do_not_open_wms_or_settings(self):
        for path in ['/api/receptions','/api/reception-transfer/settings','/api/reception-transfer/status','/api/users','/api/reception-brand-logo']:
            status,_,_ = self.request(path,'GET')
            self.assertEqual(status,401,path)
        status,headers,body = self.request('/transfer-confirmation','GET')
        self.assertEqual(status,200)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')
        self.assertNotIn('Set-Cookie',headers)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertNotIn(b'api/receptions',body)
        self.assertEqual(self.request('/api/transfer-confirmation/confirm','GET')[0],405)

    def test_mail_center_reads_existing_session_without_tokens_or_network_or_sending(self):
        raw = self.token()
        with patch('backend.services.cloud_auth.status',return_value={'authorized':True,'mail_username':self.config['sender']}) as status, \
             patch('backend.services.cloud_auth.access_token') as auth, patch.object(transfer.requests,'post') as post:
            data = transfer.mail_status(self.db)
        self.assertEqual(data['connection_state'],'REGISTERED')
        self.assertEqual(data['rows'][0]['bl_awb'],'QA-BL')
        self.assertEqual(data['rows'][0]['status'],'ACCEPTED')
        serialized = json.dumps(data)
        self.assertNotIn(raw,serialized)
        self.assertNotIn('token_hash',serialized)
        self.assertNotIn(hashlib.sha256(raw.encode()).hexdigest(),serialized)
        status.assert_called_once();auth.assert_not_called();post.assert_not_called()
        with patch('backend.services.cloud_auth.status',return_value={'authorized':True,'mail_username':'other@example.test'}):
            self.assertEqual(transfer.mail_status(self.db)['connection_state'],'REQUIRED')

    def test_mail_status_http_is_admin_only_no_store_and_read_only(self):
        for role in ('ADMINISTRADOR','ASISTENTE_RECEPCION'):
            username='qa.'+role.lower()
            app.identity.save(self.db,{'username':username,'display_name':'QA','role':role,
                              'password':'QA-password-only-123!'},'qa',app.ROLES)
            token,_=app.identity.login(self.db,username,'QA-password-only-123!')
            self.db.commit()
            cookie=app.identity.COOKIE+'='+token
            with patch('backend.services.cloud_auth.status',return_value={'authorized':False,'mail_username':''}):
                status,headers,body=self.request('/api/reception-transfer/status','GET',extra={'HTTP_COOKIE':cookie})
            self.assertEqual(status,200 if role=='ADMINISTRADOR' else 403)
            self.assertEqual(headers['Cache-Control'],'no-store')
            if status==200:
                self.assertEqual(json.loads(body)['connection_state'],'REQUIRED')
                self.assertEqual(self.request('/api/reception-transfer/status','POST',extra={'HTTP_COOKIE':cookie})[0],405)

    def test_http_guest_requires_custom_header_json_size_and_same_site(self):
        raw = self.token()
        route = '/api/transfer-confirmation/confirm'
        data = {'token':raw,'checked':True}
        self.assertEqual(self.request(route,data=data,extra={'HTTP_SEC_FETCH_SITE':'cross-site'})[0],403)
        self.assertEqual(self.request(route,data=data,extra={'HTTP_X_WMS_REQUEST':''})[0],403)
        self.assertEqual(self.request(route,data=data,extra={'CONTENT_TYPE':'text/plain'})[0],400)
        self.assertEqual(self.request(route,data=data,extra={'CONTENT_LENGTH':'5000'})[0],400)
        self.assertEqual(self.request('/api/transfer-confirmation/inspect',data={'token':raw})[0],200)
        self.assertEqual(self.request(route,data=data)[0],200)
        self.assertEqual(self.request(route,data=data)[0],200)

    def test_rate_limit_survives_invalid_tokens_and_does_not_trust_forwarded_ip(self):
        for _ in range(60): self.assertEqual(self.request('/api/transfer-confirmation/inspect',data={'token':'bad'})[0],410)
        self.assertEqual(self.request('/api/transfer-confirmation/inspect',data={'token':'bad'},extra={'HTTP_X_FORWARDED_FOR':'1.2.3.4'})[0],429)

    def test_concurrent_confirmations_only_write_one_event(self):
        raw = self.token()
        def confirm():
            with app.db() as db:
                db.execute('BEGIN IMMEDIATE')
                return transfer.confirm_token(db,raw,True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:confirm(),range(2)))
        self.assertTrue(all(result['confirmed'] for result in results))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='TRANSFERENCIA'").fetchone()[0],1)

    def run_worker(self, response=202, authorization_error=False):
        with patch('backend.services.cloud_auth.access_token',side_effect=ValueError('QA') if authorization_error else None,return_value='qa-access-token') as auth, patch.object(transfer.requests,'post') as post:
            post.return_value = Mock(status_code=response)
            transfer.worker_cycle(app)
            return auth,post

    def test_worker_uses_silent_scoped_mail_and_hash_only_no_historic_send(self):
        self.run_worker()[1].assert_not_called()
        transfer.enqueue(self.db,self.sid,self.aid);self.db.commit()
        auth,post = self.run_worker()
        auth.assert_called_once()
        self.assertEqual(auth.call_args.kwargs['expected_username'],self.config['sender'])
        self.assertEqual(post.call_args.args[0],'https://graph.microsoft.com/v1.0/me/sendMail')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        payload = post.call_args.kwargs['json']
        text = payload['message']['body']['content']
        self.assertIn('/transfer-confirmation#token=',text)
        raw = text.split('#token=')[1].split('"')[0]
        self.assertNotIn(raw,'\n'.join(self.db.iterdump()))
        row = self.db.execute('SELECT * FROM reception_transfer_requests').fetchone()
        self.assertEqual(row['status'],'ACCEPTED')
        self.assertEqual(row['token_hash'],hashlib.sha256(raw.encode()).hexdigest())
        self.run_worker()[1].assert_not_called()

    def test_auth_block_waits_and_does_not_issue_token(self):
        transfer.enqueue(self.db,self.sid,self.aid);self.db.commit()
        _,post = self.run_worker(authorization_error=True)
        post.assert_not_called()
        row = self.db.execute('SELECT * FROM reception_transfer_requests').fetchone()
        self.assertEqual(row['status'],'BLOCKED');self.assertIsNone(row['token_hash'])

    def test_delivered_link_still_works_after_an_ambiguous_mail_response(self):
        raw = self.token()
        self.db.execute("UPDATE reception_transfer_requests SET status='REVIEW'")
        self.assertFalse(transfer.inspect_token(self.db,raw)['confirmed'])
        self.assertTrue(transfer.confirm_token(self.db,raw,True)['confirmed'])

    def test_ambiguous_or_rejected_mail_never_retries_automatically(self):
        for failure in [requests.Timeout('QA'),Mock(status_code=403)]:
            with self.subTest(failure=type(failure).__name__):
                self.db.execute('DELETE FROM reception_transfer_requests')
                transfer.enqueue(self.db,self.sid,self.aid);self.db.commit()
                with patch('backend.services.cloud_auth.access_token',return_value='qa'),patch.object(transfer.requests,'post') as post:
                    if isinstance(failure,Exception): post.side_effect=failure
                    else: post.return_value=failure
                    transfer.worker_cycle(app)
                    self.assertIn(self.db.execute('SELECT status FROM reception_transfer_requests').fetchone()[0],('REVIEW','ERROR'))
                    transfer.worker_cycle(app)
                    self.assertEqual(post.call_count,1)


if __name__ == '__main__':
    unittest.main()
