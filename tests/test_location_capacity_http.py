import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from backend import app, wsgi


class LocationCapacityHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mode = patch.dict(os.environ, {'TRITON_AUTH_MODE':'demo'})
        self.path = patch.object(app, 'DB_PATH', self.root / 'qa.sqlite')
        self.mode.start();self.path.start();app.init_db()

    def tearDown(self):
        self.path.stop();self.mode.stop();self.temp.cleanup()

    def request(self, url, method='GET', payload=None, role='ADMINISTRADOR', extra=None):
        parsed = urlsplit(url)
        body = json.dumps(payload).encode() if payload is not None else b''
        environ = {'REQUEST_METHOD':method,'PATH_INFO':parsed.path,'QUERY_STRING':parsed.query,
            'wsgi.input':BytesIO(body),'CONTENT_LENGTH':str(len(body)),'CONTENT_TYPE':'application/json',
            'SERVER_NAME':'localhost','SERVER_PORT':'80','wsgi.url_scheme':'http',
            'HTTP_X_USER':'qa.user','HTTP_X_ROLE':role,'HTTP_X_WMS_REQUEST':'1',**(extra or {})}
        status, headers = [], {}
        def start(value, fields, *args):
            status.append(int(value.split()[0]));headers.update(fields)
        content = b''.join(wsgi.application(environ, start))
        return status[0], headers, json.loads(content) if 'application/json' in headers.get('Content-Type','') else content

    def test_upload_preview_persists_on_server_and_is_readable_from_another_session(self):
        status, _, preview = self.request('/api/locations/preview','POST',{'text':'QA-01\nQA-02'})
        self.assertEqual(status, 200)
        self.assertEqual(self.request('/api/locations')[2]['total'], 0)
        status, _, _ = self.request('/api/locations/import','POST',{
            'text':'QA-01\nQA-02','reason':'Carga de prueba','digest':preview['digest'],'revision':preview['revision']})
        self.assertEqual(status, 200)
        status, headers, data = self.request('/api/locations',role='PICKER')
        self.assertEqual(status, 200);self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(data['total'], 2)
        self.assertEqual(self.request('/api/locations/history?code=QA-01')[2]['items'][0]['reason'], 'Carga de prueba')

    def test_roles_page_static_assets_and_invalid_requests(self):
        for route in ('/api/locations/preview','/api/locations/import'):
            self.assertEqual(self.request(route,'POST',{'text':'QA-01'},role='PICKER')[0], 403)
        self.assertEqual(self.request('/api/locations/history?code=QA-01',role='PICKER')[0], 403)
        self.assertEqual(self.request('/api/locations?offset=bad')[0], 400)
        self.assertEqual(self.request('/api/locations',role='INVALID')[0], 403)
        self.assertEqual(self.request('/api/locations/labels','POST',{'codes':['MISSING']},role='PICKER')[0], 400)
        status, headers, page = self.request('/locations',role='PICKER')
        self.assertEqual(status, 200);self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn(b'capacityPrint', page)
        for route in ('/assets/location-capacity.js','/assets/location-labels.js','/assets/location-capacity.css','/assets/location-labels.css'):
            self.assertEqual(self.request(route)[0], 200)
        with patch.dict(os.environ, {'TRITON_AUTH_MODE':'local'}):
            self.assertIn(self.request('/api/locations')[0], (401,403))


if __name__ == '__main__':
    unittest.main()
