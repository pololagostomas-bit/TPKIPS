"""Disposable outbox; no real mailbox, Docker call or external HTTP."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest


@unittest.skipUnless(os.name=='posix','Linux server supervisor')
class LinkMailTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('infrastructure.deployment.tunnel_mail'),
                             'Link-change notifications are not implemented')
        from infrastructure.deployment import tunnel_mail
        self.mail=tunnel_mail
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'enabled':True,'sender':'sender@example.invalid','to':['owner@example.invalid'],
                     'cc':['sender@example.invalid']}
        self.sent=[]

    def guard(self,url='https://qa-first.trycloudflare.com/login',now=2000,**fields):
        return {'status':'HEALTHY','available':True,'checked_at':now,'verified_at':now,
                'link':url,'generation':'2026-10-26T03:00:00Z',**fields}

    def deliver(self,payload):
        self.sent.append(payload)
        return {'state':'ACCEPTED','http_status':202}

    def run_mail(self,url='https://qa-first.trycloudflare.com/login',now=2000,**options):
        return self.mail.run(self.root,self.config,self.guard(url,now),now=now,
                             delivery=options.pop('delivery',self.deliver),
                             verify=options.pop('verify',lambda state:True),**options)

    def rows(self):
        with closing(sqlite3.connect(self.root/'deliveries.sqlite3')) as db:
            db.row_factory=sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM deliveries ORDER BY id')]

    def test_initial_link_is_baselined_silently_and_unchanged_link_never_sends(self):
        self.assertEqual(self.run_mail()['state'],'BASELINED')
        for now in (2060,86400):self.assertEqual(self.run_mail(now=now)['state'],'UNCHANGED')
        self.assertEqual(self.sent,[])

    def test_changed_verified_url_sends_once_to_personal_and_copies_sender(self):
        self.run_mail()
        result=self.run_mail('https://qa-new.trycloudflare.com/login',2060)
        self.assertEqual(result['state'],'ACCEPTED')
        self.assertEqual(len(self.sent),1)
        payload=self.sent[0]
        self.assertEqual(payload['to'],['owner@example.invalid'])
        self.assertEqual(payload['cc'],['sender@example.invalid'])
        self.assertIn('https://qa-new.trycloudflare.com/login',payload['html'])
        self.assertNotIn('qa-first',payload['html'])
        for now in (2120,86400):self.run_mail('https://qa-new.trycloudflare.com/login',now)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.rows()[0]['state'],'ACCEPTED')

    def test_unhealthy_stale_future_or_untrusted_link_cannot_notify(self):
        self.run_mail()
        for changes in ({'available':False},{'status':'RESTARTED'},{'checked_at':1000},
                        {'verified_at':1000},{'checked_at':3000},{'link':'https://example.invalid/login'}):
            state=self.guard('https://qa-new.trycloudflare.com/login',2060,**changes)
            result=self.mail.run(self.root,self.config,state,now=2060,delivery=self.deliver,verify=lambda state:True)
            self.assertEqual(result['state'],'UNAVAILABLE')
        self.assertEqual(self.sent,[])
        self.assertEqual(self.rows(),[])

    def test_failed_current_tunnel_recheck_does_not_advance_baseline(self):
        self.run_mail()
        self.assertEqual(self.run_mail('https://qa-new.trycloudflare.com/login',2060,verify=lambda state:False)['state'],'UNVERIFIED')
        self.assertEqual(self.sent,[])
        self.assertEqual(self.rows(),[])
        self.assertEqual(self.run_mail('https://qa-new.trycloudflare.com/login',2120)['state'],'ACCEPTED')

    def test_generation_change_without_url_change_is_silent(self):
        self.run_mail()
        state=self.guard(generation='2026-10-26T04:00:00Z')
        self.mail.run(self.root,self.config,state,now=2000,delivery=self.deliver,verify=lambda state:True)
        self.assertEqual(self.sent,[])

    def test_missing_authorization_has_backoff_and_can_resume_same_change(self):
        self.run_mail();url='https://qa-new.trycloudflare.com/login'
        calls=[]
        def blocked(payload):calls.append(payload);return {'state':'BLOCKED'}
        self.assertEqual(self.run_mail(url,2060,delivery=blocked)['state'],'BLOCKED')
        self.assertEqual(self.run_mail(url,2120,delivery=blocked)['state'],'WAITING')
        self.assertEqual(len(calls),1)
        self.assertEqual(self.run_mail(url,3000)['state'],'ACCEPTED')
        self.assertEqual(len(self.rows()),1)
        self.assertIn(self.rows()[0]['event_key'],self.sent[0]['html'])

    def test_ambiguous_send_and_crash_are_not_retried(self):
        self.run_mail();url='https://qa-new.trycloudflare.com/login'
        def ambiguous(payload):raise TimeoutError('QA send outcome unknown')
        self.assertEqual(self.run_mail(url,2060,delivery=ambiguous)['state'],'REVIEW')
        self.assertEqual(self.run_mail(url,3000)['state'],'REVIEW')
        self.assertEqual(self.sent,[])
        self.assertEqual(self.rows()[0]['state'],'REVIEW')
        def crash(payload):
            self.assertEqual(self.rows()[-1]['state'],'SENDING')
            raise SystemExit('QA process interrupted after reservation')
        with self.assertRaises(SystemExit):self.run_mail('https://qa-third.trycloudflare.com/login',3060,delivery=crash)
        self.assertEqual(self.run_mail('https://qa-third.trycloudflare.com/login',4000)['state'],'REVIEW')
        self.assertEqual(self.sent,[])

    def test_latest_link_supersedes_unsent_old_link_and_returning_url_is_a_new_change(self):
        first='https://qa-first.trycloudflare.com/login';second='https://qa-second.trycloudflare.com/login'
        self.run_mail(first)
        self.run_mail(second,2060,delivery=lambda payload:{'state':'BLOCKED'})
        self.run_mail(first,2120)
        self.assertEqual(len(self.sent),1)
        self.assertIn(first,self.sent[0]['html'])
        self.assertEqual([row['state'] for row in self.rows()],['SUPERSEDED','ACCEPTED'])

    def test_overlapping_processes_share_lock_and_send_once(self):
        self.run_mail();url='https://qa-new.trycloudflare.com/login'
        started=threading.Event();release=threading.Event()
        def slow(payload):
            started.set();self.assertTrue(release.wait(5));return self.deliver(payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.run_mail,url,2060,delivery=slow)
            self.assertTrue(started.wait(5))
            try:self.assertEqual(self.run_mail(url,2060)['state'],'ALREADY_RUNNING')
            finally:release.set()
            self.assertEqual(first.result()['state'],'ACCEPTED')
        self.assertEqual(len(self.sent),1)

    def test_disabled_or_invalid_recipient_configuration_cannot_send(self):
        self.config['enabled']=False
        self.assertEqual(self.run_mail()['state'],'DISABLED')
        self.config['enabled']=True;self.config['to']=['bad\naddress@example.invalid']
        with self.assertRaises(ValueError):self.run_mail()
        self.assertEqual(self.sent,[])

    def test_existing_mail_function_receives_html_and_classifies_results_without_resending(self):
        package=self.root/'backend'/'services';package.mkdir(parents=True)
        (package.parent/'__init__.py').touch();(package/'__init__.py').touch()
        (package/'cloud_auth.py').write_text('''MAIL_SCOPES=['qa-mail']
class CloudAuthError(Exception):pass
def access_token(scopes,expected_username):
    if scopes!=['qa-mail'] or expected_username!='sender@example.invalid':raise CloudAuthError()
    return 'QA'
''')
        (package/'purchase_alerts.py').write_text('''import json
from pathlib import Path
from types import SimpleNamespace
def _post_mail(token,payload):
    assert token=='QA'
    Path('sent.json').write_text(json.dumps(payload))
    return SimpleNamespace(status_code=payload['qa_status'])
''')
        body={'sender':'sender@example.invalid','html':'<p>QA link</p>',
              'to':['owner@example.invalid'],'cc':['sender@example.invalid'],'subject':'QA'}
        for code,wanted in ((202,'ACCEPTED'),(429,'THROTTLED'),(401,'BLOCKED'),
                            (403,'BLOCKED'),(400,'REJECTED'),(408,'REVIEW'),(503,'REVIEW'),(302,'REVIEW')):
            with self.subTest(code=code):
                result=subprocess.run([sys.executable,'-c',self.mail.REMOTE],cwd=self.root,
                    input=json.dumps({**body,'qa_status':code}),text=True,capture_output=True,check=True)
                self.assertEqual(json.loads(result.stdout),{'state':wanted,'http_status':code})
        sent=json.loads((self.root/'sent.json').read_text())
        self.assertEqual(sent['html'],'<p>QA link</p>')
        self.assertEqual(sent['to'],['owner@example.invalid'])
        (self.root/'sent.json').unlink()
        for extra,wanted in (({'check':True},'AUTHORIZED'),({'sender':'other@example.invalid'},'BLOCKED')):
            result=subprocess.run([sys.executable,'-c',self.mail.REMOTE],cwd=self.root,
                input=json.dumps({**body,**extra}),text=True,capture_output=True,check=True)
            self.assertEqual(json.loads(result.stdout),{'state':wanted})
            self.assertFalse((self.root/'sent.json').exists())
