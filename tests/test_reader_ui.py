import io
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend import app

ROOT = Path(__file__).resolve().parents[1]


class ReaderUiTests(unittest.TestCase):
    def test_assets_are_public_static_only_with_no_cache(self):
        for name, mime in [('reader-ui.js', 'application/javascript'), ('reader-ui.css', 'text/css')]:
            with self.subTest(name=name):
                statuses, headers, output = [], {}, io.BytesIO()
                request = SimpleNamespace(path='/assets/' + name + '?v=qa',
                    send_response=statuses.append, send_header=headers.__setitem__,
                    end_headers=lambda: None, wfile=output)
                app.Handler.do_GET(request)
                self.assertEqual(statuses, [200])
                self.assertEqual(headers['Content-Type'], mime + '; charset=utf-8')
                self.assertEqual(headers['Cache-Control'], 'no-cache')
                self.assertEqual(output.getvalue(), (ROOT / 'frontend/static' / name).read_bytes())

    def test_all_reader_modules_use_the_same_ui(self):
        for name in ['reception', 'inventory', 'login', 'change-password', 'cloud-connection', 'purchase-alerts']:
            with self.subTest(name=name):
                source = (ROOT / 'frontend/templates' / (name + '.html')).read_text(encoding='utf-8')
                self.assertEqual(source.count('/assets/reader-ui.css'), 1)
                self.assertEqual(source.count('/assets/reader-ui.js'), 1)
        statuses, output = [], io.BytesIO()
        request = SimpleNamespace(path='/', send_response=statuses.append, send_header=lambda *args: None,
            end_headers=lambda: None, wfile=output)
        app.Handler.do_GET(request)
        self.assertEqual(statuses, [200])
        self.assertEqual(output.getvalue().count(b'/assets/reader-ui.css'), 1)
        self.assertEqual(output.getvalue().count(b'/assets/reader-ui.js'), 1)


if __name__ == '__main__':
    unittest.main()
