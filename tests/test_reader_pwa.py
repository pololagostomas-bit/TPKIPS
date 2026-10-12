import io
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import app, password_policy

ROOT = Path(__file__).resolve().parents[1]


class ReaderPwaTests(unittest.TestCase):
    def get(self, path):
        output, statuses, headers = io.BytesIO(), [], {}
        handler = SimpleNamespace(path=path, send_response=statuses.append,
            send_header=headers.__setitem__, end_headers=lambda: None, wfile=output)
        with patch.dict(os.environ, {'TRITON_AUTH_MODE':'demo'}), patch.object(app, 'current_user', return_value=('qa', 'ADMINISTRADOR')):
            app.Handler.do_GET(handler)
        return statuses, headers, output.getvalue()

    def test_worker_is_static_and_does_not_cache_authenticated_html(self):
        status, headers, body = self.get('/service-worker.js')
        self.assertEqual(status, [200])
        self.assertEqual(body, (ROOT / 'frontend/static/service-worker.js').read_text(encoding='utf-8').encode('utf-8'))
        self.assertNotIn(b'cache.addAll', body)
        self.assertNotIn(b'caches.match', body)
        self.assertEqual(headers['Content-Type'], 'application/javascript')

    def test_all_entry_pages_register_network_only_worker(self):
        for path in ['/', '/reception', '/inventory', '/login']:
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual(status, [200])
                self.assertEqual(body.count(b'/assets/pwa-client.js'), 1)
                self.assertNotIn(b'workspace-variant1-', body)
                self.assertEqual(b'wmsBootStatus' in body, path != '/login')
        for name in ['change-password', 'cloud-connection', 'purchase-alerts']:
            rendered = password_policy.render_page(ROOT / 'frontend/templates' / (name+'.html'))
            self.assertEqual(rendered.count(b'/assets/pwa-client.js'), 1)

    def test_shared_overlay_keeps_older_manual_html_unchanged(self):
        template = ROOT / 'frontend/templates/cloud-connection.html'
        with patch.object(app, 'reader_page', None):
            self.assertEqual(password_policy.render_page(template), template.read_bytes())

    def test_pwa_client_is_public_static_and_uncached(self):
        status, headers, body = self.get('/assets/pwa-client.js')
        self.assertEqual(status, [200])
        self.assertEqual(headers['Cache-Control'], 'no-cache')
        self.assertEqual(body, (ROOT / 'frontend/static/pwa-client.js').read_bytes())

    def test_service_worker_behavior(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is not available')
        result = subprocess.run([node, str(ROOT / 'tests/reader_pwa_dom.cjs')], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
