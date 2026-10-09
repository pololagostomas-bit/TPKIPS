"""Synthetic purchase reports; no corporate recipients, files or mail delivery."""
import io
import json
import os
import tempfile
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from openpyxl import Workbook

from backend.services import purchase_alerts as alerts, cloud_auth as auth


def workbook(rows, archive=None):
    book = Workbook()
    sheet = book.active
    sheet.title = 'BUYER'
    sheet.append(['ORDEN DE COMPRA', 'PEDIDO TRITON'])
    for row in rows:
        sheet.append(row)
    if archive is not None:
        sheet = book.create_sheet('ANIBAL.23.04')
        sheet.append(['ORDEN DE COMPRA', 'PEDIDO TRITON'])
        for row in archive:
            sheet.append(row)
    target = io.BytesIO()
    book.save(target)
    book.close()
    return target.getvalue()


def clock(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'WMS_PURCHASE_ALERT_DB': str(Path(self.folder.name) / 'reports.sqlite3'),
            'GRAPH_TOKEN_CACHE_PATH': str(Path(self.folder.name) / 'cache.json'),
            'GRAPH_TENANT_ID': '', 'GRAPH_CLIENT_ID': '', 'WMS_PURCHASE_ALERT_WORKER': '0'})
        self.env.start()
        self.token = patch.object(auth, 'access_token', return_value='synthetic-token')
        self.token_mock = self.token.start()
        self.post = patch.object(alerts, '_post_mail', return_value=Mock(status_code=202))
        self.post_mock = self.post.start()
        self.fetch = patch.object(alerts, 'fetch_snapshot', side_effect=lambda _config: self.snapshot)
        self.fetch_mock = self.fetch.start()
        self.now = clock('2026-10-09T13:00:00')  # Friday 08:00 Lima.
        self.set_rows([['PRE-100001', 'IP-1']])
        alerts.save({'sender': 'owner@contoso.test', 'sender_name': 'Owner',
                     'to': ['Buyer <buyer@contoso.test>'], 'cc': ['cc@contoso.test'],
                     'enabled': True}, 'admin.qa')

    def tearDown(self):
        self.fetch.stop(); self.post.stop(); self.token.stop(); self.env.stop(); self.folder.cleanup()

    def set_rows(self, rows):
        self.snapshot = alerts.read_cases(workbook(rows), ['ANIBAL.23.04'])
        self.snapshot.update(checked_at=alerts._stamp(clock('2026-10-09T13:00:00')), modified_at='2026-10-09T12:59:00Z')

    def test_literal_rule_and_excluded_archive_no_guide_or_part_required(self):
        rows = [['12345', 'IP-1'], ['123456', 'IP-2'], ['pre-7', 'IP-3'],
                ['PRE-8', ''], ['123456', '   '], ['12345 / 54321', 'IP-4'],
                [12345.0, 'IP-5'], [123456.0, 'IP-6'], [None, 'IP-7'], ['1234', 'IP-8']]
        result = alerts.read_cases(workbook(rows, [['PRE-900', 'OLD-IP']]), ['ANIBAL.23.04'])
        self.assertEqual({item['ip'] for item in result['cases']}, {'IP-2', 'IP-3', 'IP-4', 'IP-6'})
        self.assertEqual(result['excluded_sheets'], ['ANIBAL.23.04'])

    def test_grouping_preserves_source_rows(self):
        result = alerts.read_cases(workbook([['PRE-1', 'IP-1'], ['PRE-1', 'IP-1']]), [])
        self.assertEqual(len(result['cases']), 1)
        self.assertEqual(result['cases'][0]['rows'], 2)
        self.assertEqual([item['row'] for item in result['cases'][0]['sources']], [2, 3])

    def test_formula_without_cached_value_and_excel_error_fail_closed(self):
        for value in ['=1+1', '#VALUE!']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                alerts.read_cases(workbook([[value, 'IP-1']]), [])

    def test_preview_never_sends_or_marks_initial_report_delivered(self):
        result = alerts.run(force=True, now=self.now)
        self.assertIn('IP-1', result['preview']['html'])
        self.post_mock.assert_not_called()
        self.assertFalse(alerts.status()['state'].get('started'))
        self.assertTrue(alerts.run(now=self.now + 3600)['sent'])

    def test_disabled_and_empty_reports_do_not_send(self):
        alerts.save({'enabled': False}, 'admin.qa')
        self.assertTrue(alerts.run(now=self.now)['skipped'])
        alerts.run(force=True, now=self.now)
        self.post_mock.assert_not_called()
        alerts.save({'enabled': True}, 'admin.qa')
        self.set_rows([['12345', 'IP-1']])
        self.assertFalse(alerts.run(now=self.now)['sent'])
        self.post_mock.assert_not_called()

    def test_first_run_and_repeat_in_another_app_share_delivery_state(self):
        self.assertTrue(alerts.run(now=self.now)['sent'])
        self.assertTrue(alerts.run(now=self.now + 1)['skipped'])
        self.assertFalse(alerts.run(now=self.now + 3600)['sent'])
        self.assertEqual(self.post_mock.call_count, 1)
        self.assertEqual(len(alerts.status()['history']), 1)

    def test_incremental_includes_new_and_existing_pending(self):
        alerts.save({'daily_time': '11:00'}, 'admin.qa')
        alerts.run(now=self.now)
        self.set_rows([['PRE-100001', 'IP-1'], ['PRE-100002', 'IP-2']])
        result = alerts.run(now=self.now + 3600)
        self.assertEqual(result['new_count'], 1)
        payload = self.post_mock.call_args.args[1]
        self.assertIn('Casos adicionados', payload['html'])
        self.assertIn('Demas pendientes', payload['html'])
        self.assertIn('IP-1', payload['html']); self.assertIn('IP-2', payload['html'])
        self.assertFalse(alerts.run(now=self.now + 7200)['sent'])

    def test_new_case_is_reported_even_when_total_count_does_not_increase(self):
        alerts.run(now=self.now)
        self.set_rows([['PRE-100002', 'IP-2']])
        self.assertEqual(alerts.run(now=self.now + 3600)['new_count'], 1)
        self.assertEqual(self.post_mock.call_count, 2)

    def test_resolution_alone_is_silent_and_reappearance_is_new(self):
        alerts.run(now=self.now)
        self.set_rows([['12345', 'IP-1']])
        self.assertFalse(alerts.run(now=self.now + 3600)['sent'])
        self.set_rows([['PRE-100001', 'IP-1']])
        self.assertTrue(alerts.run(now=self.now + 7200)['sent'])

    def test_daily_runs_at_lima_10_once_and_includes_all_pending(self):
        alerts.run(now=self.now)
        before = clock('2026-10-09T14:59:00')
        self.assertFalse(alerts.run(now=before)['sent'])
        self.assertTrue(alerts.run(now=clock('2026-10-09T15:00:00'))['sent'])
        self.assertTrue(alerts.run(now=clock('2026-10-09T15:00:30'))['skipped'])
        self.assertEqual(self.post_mock.call_count, 2)
        self.assertEqual(alerts.status()['history'][0]['kind'], 'daily')

    def test_weekend_does_not_send_daily_but_new_cases_still_alert(self):
        alerts.run(now=self.now)
        self.assertFalse(alerts.run(now=clock('2026-10-10T15:00:00'))['sent'])
        self.set_rows([['PRE-100001', 'IP-1'], ['PRE-100002', 'IP-2']])
        self.assertTrue(alerts.run(now=clock('2026-10-10T16:00:00'))['sent'])

    def test_configurable_interval_time_and_days(self):
        alerts.save({'interval_minutes': 5, 'daily_time': '08:05', 'weekdays': [4]}, 'admin.qa')
        alerts.run(now=self.now)
        self.assertTrue(alerts.run(now=self.now + 299)['skipped'])
        self.assertTrue(alerts.run(now=self.now + 300)['sent'])

    def test_downloading_failure_preserves_snapshot_and_does_not_send(self):
        alerts.run(now=self.now)
        before = alerts.status()['state']['snapshot']
        self.fetch_mock.side_effect = ValueError('PRIVATE-CELL')
        with self.assertRaises(ValueError) as error:
            alerts.run(now=self.now + 3600)
        self.assertNotIn('PRIVATE-CELL', str(error.exception))
        self.assertEqual(alerts.status()['state']['snapshot'], before)
        self.assertEqual(self.post_mock.call_count, 1)

    def test_missing_previously_known_sheet_does_not_resolve_cases(self):
        alerts.run(now=self.now)
        self.snapshot['sheets'] = ['OTHER']
        self.snapshot['cases'] = []
        with self.assertRaises(ValueError): alerts.run(now=self.now + 3600)
        self.assertEqual(len(alerts.status()['state']['snapshot']['cases']), 1)

    def test_no_consent_does_not_consume_first_report_or_daily_report(self):
        self.token_mock.side_effect = auth.CloudAuthError('Consent required')
        with self.assertRaises(ValueError): alerts.run(now=self.now)
        self.assertEqual(alerts.status()['history'], [])
        self.token_mock.side_effect = None
        alerts.run(now=self.now + 60)
        self.token_mock.side_effect = auth.CloudAuthError('Consent required')
        with self.assertRaises(ValueError): alerts.run(now=clock('2026-10-09T15:00:00'))
        self.assertNotIn('last_daily', alerts.status()['state'])
        self.token_mock.side_effect = None
        self.assertTrue(alerts.run(now=clock('2026-10-09T15:01:00'))['sent'])

    def test_timeout_is_uncertain_and_never_automatically_repeated(self):
        self.post_mock.side_effect = requests.Timeout('PRIVATE-TOKEN')
        result = alerts.run(now=self.now)
        self.assertEqual(result['mail_status'], 'REVISAR ENVIO')
        self.assertNotIn('PRIVATE-TOKEN', json.dumps(alerts.status()))
        self.assertFalse(alerts.run(now=self.now + 3600)['sent'])
        with self.assertRaises(ValueError): alerts.run(now=clock('2026-10-09T15:00:00'))
        self.assertEqual(self.post_mock.call_count, 1)

    def test_unknown_delivery_needs_explicit_review_before_new_send(self):
        self.post_mock.side_effect = requests.Timeout()
        alerts.run(now=self.now)
        identifier = alerts.status()['history'][0]['id']
        alerts.review_delivery(identifier, False, 'admin.qa')
        self.post_mock.side_effect = None
        self.assertTrue(alerts.run(force=True, send_now=True, now=self.now + 1)['sent'])

    def test_crashed_inflight_row_is_not_retried(self):
        payload = alerts.render(alerts.settings(), self.snapshot, set(), 'initial')
        with alerts.db() as connection:
            connection.execute('INSERT INTO outbox(id,event_key,kind,created_at,status,payload) VALUES(?,?,?,?,?,?)',
                ('test', 'test', 'initial', alerts._stamp(self.now), 'ENVIANDO', json.dumps(payload)))
        with self.assertRaises(ValueError): alerts.run(now=self.now)
        self.assertEqual(alerts.status()['history'][0]['status'], 'REVISAR ENVIO')
        self.post_mock.assert_not_called()

    def test_exclusive_lock_rejects_overlapping_review(self):
        with alerts.job_lock() as acquired:
            self.assertTrue(acquired)
            with self.assertRaises(ValueError): alerts.run(force=True, now=self.now)

    def test_separate_process_cannot_send_under_another_app_lock(self):
        code = 'from backend.services import purchase_alerts as a\nwith a.job_lock() as ok: print(ok)'
        with alerts.job_lock() as acquired:
            self.assertTrue(acquired)
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'False')

    def test_daily_and_new_cases_at_same_time_produce_only_one_mail(self):
        alerts.run(now=self.now)
        self.set_rows([['PRE-100001', 'IP-1'], ['PRE-100002', 'IP-2']])
        self.assertTrue(alerts.run(now=clock('2026-10-09T15:00:00'))['sent'])
        self.assertEqual(self.post_mock.call_count, 2)
        self.assertEqual(alerts.status()['history'][0]['kind'], 'daily')

    def test_header_injection_invalid_templates_and_bad_schedule_are_rejected(self):
        bad = [{'to': ['buyer@contoso.test\r\nBcc: other@contoso.test']}, {'subject': '{fecha.__class__}'},
               {'body': '{total!r}'}, {'subject': 'Hi\nBcc'}, {'daily_time': '25:01'},
               {'interval_minutes': True}, {'interval_minutes': 4}, {'weekdays': []},
               {'weekdays': [True]}, {'timezone': 'UTC'}, {'sender': 'Name <owner@contoso.test>'}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError): alerts.save(value, 'admin.qa')

    def test_html_is_escaped_and_to_cc_are_deduplicated(self):
        config = alerts.validate({'body': '<script>bad</script>', 'to': ['buyer@contoso.test', 'BUYER@contoso.test'],
                                 'cc': ['buyer@contoso.test', 'cc@contoso.test']})
        self.assertEqual(len(config['to']), 1); self.assertEqual(len(config['cc']), 1)
        payload = alerts.render(config, self.snapshot, set())
        self.assertNotIn('<script>', payload['html'])
        self.assertIn('&lt;script&gt;', payload['html'])

    def test_graph_transport_uses_authenticated_sender_and_to_cc(self):
        self.post.stop()
        payload = alerts.render(alerts.settings(), self.snapshot, set())
        with patch.object(alerts.requests, 'post', return_value=Mock(status_code=202)) as post:
            alerts._post_mail('synthetic-token', payload)
        self.assertEqual(post.call_args.args[0], 'https://graph.microsoft.com/v1.0/me/sendMail')
        sent = post.call_args.kwargs['json']
        self.assertTrue(sent['saveToSentItems'])
        self.assertEqual(sent['message']['toRecipients'][0]['emailAddress']['address'], 'buyer@contoso.test')
        self.assertEqual(sent['message']['ccRecipients'][0]['emailAddress']['address'], 'cc@contoso.test')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_configuration_change_during_review_prevents_old_recipient_send(self):
        def change(_config):
            alerts.save({'to': ['changed@contoso.test']}, 'admin.qa')
            return self.snapshot
        self.fetch_mock.side_effect = change
        with self.assertRaises(ValueError): alerts.run(now=self.now)
        self.post_mock.assert_not_called()


class MailAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GRAPH_TOKEN_CACHE_PATH': str(Path(self.folder.name) / 'cache.json'),
            'GRAPH_TENANT_ID': 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', 'GRAPH_CLIENT_SECRET': ''})
        self.env.start()
        self.client, self.cache = Mock(), Mock(has_state_changed=False)
        self.factory = patch.object(auth, 'client', return_value=(self.client, self.cache))
        self.factory.start()
        self.client.initiate_device_flow.return_value = {'user_code': 'CODE', 'device_code': 'SECRET', 'interval': 5}

    def tearDown(self):
        self.factory.stop(); self.env.stop(); self.folder.cleanup()

    def test_mail_consent_requests_explicit_scope(self):
        auth.begin('owner', mail_sender='owner@contoso.test')
        self.assertIn('https://graph.microsoft.com/Mail.Send', self.client.initiate_device_flow.call_args.kwargs['scopes'])

    def test_wrong_sender_and_missing_mail_scope_cannot_replace_excel_account(self):
        for username, scope in [('other@contoso.test', 'Mail.Send'), ('owner@contoso.test', 'Files.ReadWrite')]:
            with self.subTest(username=username, scope=scope):
                flow = auth.begin('owner', mail_sender='owner@contoso.test')
                with auth.locked():
                    pending = auth.read_state('pending.json'); pending['next_poll'] = 0; auth.write_state('pending.json', pending)
                    auth.write_state('account.json', {'home_account_id': 'previous'})
                self.client.acquire_token_by_device_flow.return_value = {'access_token': 'SECRET', 'scope': scope,
                    'id_token_claims': {'tid': os.environ['GRAPH_TENANT_ID'], 'preferred_username': username}}
                with self.assertRaises(auth.CloudAuthError): auth.poll('owner', flow['flow_id'])
                self.assertEqual(auth.read_state('account.json')['home_account_id'], 'previous')

    def test_expected_username_is_checked_before_silent_token(self):
        with auth.locked(): auth.write_state('account.json', {'home_account_id': 'selected'})
        self.client.get_accounts.return_value = [{'home_account_id': 'selected', 'username': 'wrong@contoso.test'}]
        with self.assertRaises(auth.CloudAuthError): auth.access_token(auth.MAIL_SCOPES, 'owner@contoso.test')
        self.client.acquire_token_silent.assert_not_called()

    def test_file_only_token_cannot_be_used_for_mail(self):
        with auth.locked(): auth.write_state('account.json', {'home_account_id': 'selected'})
        self.client.get_accounts.return_value = [{'home_account_id': 'selected', 'username': 'owner@contoso.test'}]
        self.client.acquire_token_silent.return_value = {'access_token': 'SECRET', 'scope': 'Files.ReadWrite'}
        with self.assertRaises(auth.CloudAuthError): auth.access_token(auth.MAIL_SCOPES, 'owner@contoso.test')
        self.client.acquire_token_silent.return_value = {'access_token': 'SECRET', 'scope': 'Files.ReadWrite Mail.Send'}
        self.assertEqual(auth.access_token(auth.MAIL_SCOPES, 'owner@contoso.test'), 'SECRET')


if __name__ == '__main__':
    unittest.main()
