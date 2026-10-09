import io
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend import app

ROOT = Path(__file__).resolve().parents[1]


class MobileWorkspaceTests(unittest.TestCase):
    def test_mobile_assets_use_existing_static_handler_and_cache_policy(self):
        for filename, mime in [('mobile-workspace.js', 'application/javascript'), ('mobile-workspace.css', 'text/css')]:
            with self.subTest(filename=filename):
                headers = {}
                status = []
                output = io.BytesIO()
                handler = SimpleNamespace(path='/assets/' + filename + '?v=test',
                    send_response=status.append, send_header=headers.__setitem__,
                    end_headers=lambda: None, wfile=output)
                app.Handler.do_GET(handler)
                self.assertEqual(status, [200])
                self.assertEqual(headers['Content-Type'], mime + '; charset=utf-8')
                self.assertEqual(headers['Cache-Control'], 'no-cache')
                self.assertEqual(output.getvalue(), (ROOT / 'frontend/static' / filename).read_bytes())
                self.assertEqual(int(headers['Content-Length']), len(output.getvalue()))

    def test_all_modules_include_shared_mobile_assets(self):
        for path in [ROOT / 'backend/app.py', ROOT / 'frontend/templates/reception.html',
                ROOT / 'frontend/templates/inventory.html']:
            source = path.read_text(encoding='utf-8')
            self.assertIn('/assets/mobile-workspace.css', source)
            self.assertIn('/assets/mobile-workspace.js', source)
