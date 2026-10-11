"""Real MSAL cache/refresh regression tests with synthetic credentials only."""
import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import msal
import requests

from backend.services import cloud_auth as auth

TENANT = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
CLIENT = '11111111-2222-3333-4444-555555555555'
AUTHORITY = 'https://login.microsoftonline.com/' + TENANT
SENDER = 'owner@contoso.test'
TOKEN = 'synthetic-access-token'


def response(data, status=200):
    return Mock(status_code=status, headers={}, text=json.dumps(data), json=lambda: data)


def account_info(uid='qa-user', tenant=TENANT):
    return base64.urlsafe_b64encode(json.dumps({'uid': uid, 'utid': tenant}).encode()).decode()


class MailCacheSessionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'GRAPH_TOKEN_CACHE_PATH': str(Path(self.folder.name) / 'cache.json'),
            'GRAPH_TENANT_ID': TENANT, 'GRAPH_CLIENT_ID': CLIENT, 'GRAPH_CLIENT_SECRET': '',
        })
        self.env.start()
        self.http = Mock()
        self.http.get.side_effect = self.discovery
        self.http.post.side_effect = AssertionError('No real OAuth request is permitted.')
        self.seed()
        self.factory = patch.object(auth, 'client', side_effect=self.client)
        self.factory_mock = self.factory.start()

    def tearDown(self):
        self.factory.stop()
        self.env.stop()
        self.folder.cleanup()

    def discovery(self, url, **_kwargs):
        self.assertEqual(url, AUTHORITY + '/v2.0/.well-known/openid-configuration')
        return response({
            'authorization_endpoint': AUTHORITY + '/oauth2/v2.0/authorize',
            'token_endpoint': AUTHORITY + '/oauth2/v2.0/token',
            'device_authorization_endpoint': AUTHORITY + '/oauth2/v2.0/devicecode',
            'issuer': AUTHORITY + '/v2.0',
        })

    def seed(self, scopes=None, expired=False, client_id=CLIENT, tenant=TENANT, uid='qa-user'):
        cache = msal.SerializableTokenCache()
        cache.add({
            'client_id': client_id,
            'scope': auth.MAIL_SCOPES if scopes is None else scopes,
            'token_endpoint': 'https://login.microsoftonline.com/' + tenant + '/oauth2/v2.0/token',
            'response': {
                'access_token': TOKEN, 'refresh_token': 'synthetic-refresh-token',
                'expires_in': 3600, 'client_info': account_info(uid, tenant),
                'id_token_claims': {'tid': tenant, 'oid': 'qa-local-account', 'preferred_username': SENDER},
            },
        }, now=time.time() - 7200 if expired else time.time())
        with auth.locked():
            auth.save_cache(cache)
            auth.write_state('account.json', {'home_account_id': 'qa-user.' + TENANT,
                                            'mail_username': SENDER})

    def client(self):
        cache = msal.SerializableTokenCache()
        cache.deserialize(auth.cache_path().read_text(encoding='utf-8'))
        application = msal.PublicClientApplication(CLIENT, authority=AUTHORITY,
            token_cache=cache, http_client=self.http, instance_discovery=False)
        return application, cache

    def mail_token(self):
        return auth.access_token(auth.MAIL_SCOPES, SENDER)

    def test_real_msal_cache_hit_has_no_scope_but_is_reusable(self):
        application, _cache = self.client()
        result = application.acquire_token_silent(auth.MAIL_SCOPES, application.get_accounts()[0])
        self.assertEqual(result['token_source'], 'cache')
        self.assertNotIn('scope', result)
        before = auth.cache_path().read_bytes()
        for _ in range(3):
            self.assertEqual(self.mail_token(), TOKEN)
        self.assertEqual(auth.cache_path().read_bytes(), before)
        self.http.post.assert_not_called()
        self.assertGreaterEqual(self.factory_mock.call_count, 3)

    def test_expired_access_is_silently_refreshed_and_new_cache_is_reusable(self):
        self.seed(expired=True)
        self.http.post.side_effect = None
        self.http.post.return_value = response({
            'access_token': 'synthetic-renewed-token', 'expires_in': 3600,
            'scope': ' '.join(auth.MAIL_SCOPES), 'refresh_token': 'synthetic-renewed-refresh',
            'client_info': account_info(),
        })
        self.assertEqual(self.mail_token(), 'synthetic-renewed-token')
        self.assertEqual(self.mail_token(), 'synthetic-renewed-token')
        self.http.post.assert_called_once()
        self.assertEqual(self.http.post.call_args.args[0], AUTHORITY + '/oauth2/v2.0/token')

    def test_wrong_sender_cannot_use_saved_mail_token(self):
        with self.assertRaises(auth.CloudAuthError):
            auth.access_token(auth.MAIL_SCOPES, 'other@contoso.test')
        self.http.post.assert_not_called()

    def test_explicit_narrower_grant_is_rejected_even_with_mail_in_cache(self):
        with patch.object(msal.PublicClientApplication, 'acquire_token_silent',
                          return_value={'access_token': TOKEN, 'scope': 'Files.ReadWrite', 'token_source': 'cache'}):
            with self.assertRaises(auth.CloudAuthError):
                self.mail_token()

    def test_file_only_cached_token_is_not_accepted_as_mail_permission(self):
        self.seed(scopes=auth.SCOPES)
        with patch.object(msal.PublicClientApplication, 'acquire_token_silent',
                          return_value={'access_token': TOKEN, 'token_source': 'cache'}):
            with self.assertRaises(auth.CloudAuthError):
                self.mail_token()

    def test_cache_proof_must_match_returned_token_and_authority(self):
        cases = [('token', {}, 'different-synthetic-token'),
                 ('client', {'client_id': TENANT}, TOKEN),
                 ('tenant', {'tenant': CLIENT}, TOKEN),
                 ('account', {'uid': 'other-user'}, TOKEN),
                 ('expired', {'expired': True}, TOKEN)]
        for label, options, returned in cases:
            with self.subTest(case=label):
                self.seed(**options)
                with patch.object(msal.PublicClientApplication, 'get_accounts', return_value=[{
                        'home_account_id': 'qa-user.' + TENANT, 'username': SENDER}]), \
                     patch.object(msal.PublicClientApplication, 'acquire_token_silent',
                         return_value={'access_token': returned, 'token_source': 'cache'}):
                    with self.assertRaises(auth.CloudAuthError):
                        self.mail_token()

    def test_cached_proof_does_not_replace_missing_scope_in_a_fresh_response(self):
        with patch.object(msal.PublicClientApplication, 'acquire_token_silent',
                          return_value={'access_token': TOKEN, 'token_source': 'identity_provider'}):
            with self.assertRaises(auth.CloudAuthError):
                self.mail_token()

    def test_revoked_refresh_requires_authorization_without_exposing_raw_error(self):
        self.seed(expired=True)
        self.http.post.side_effect = None
        self.http.post.return_value = response({'error': 'invalid_grant',
                                               'error_description': 'PRIVATE-UPSTREAM-DETAIL'}, 400)
        with self.assertRaises(auth.CloudAuthError) as result:
            self.mail_token()
        self.assertNotIn('PRIVATE-UPSTREAM-DETAIL', str(result.exception))
        self.assertTrue(auth.cache_path().exists())

    def test_refresh_network_error_is_not_a_request_for_new_consent(self):
        self.seed(expired=True)
        self.http.post.side_effect = requests.ConnectionError('PRIVATE-NETWORK-DETAIL')
        before = auth.cache_path().read_bytes()
        with self.assertRaises(auth.CloudAuthError) as result:
            self.mail_token()
        self.assertEqual(result.exception.code, 'network')
        self.assertNotIn('PRIVATE-NETWORK-DETAIL', str(result.exception))
        self.assertEqual(auth.cache_path().read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
