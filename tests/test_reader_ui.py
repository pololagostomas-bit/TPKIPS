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

    def test_guidance_is_semantic_and_never_hides_operational_feedback(self):
        css=(ROOT / 'frontend/static/reader-ui.css').read_text(encoding='utf-8')
        shell=(ROOT / 'frontend/static/workspace-shell.css').read_text(encoding='utf-8')
        for source in [css,shell]:
            self.assertIn('.help-guidance:not(.error):not(.warning):not(.success):not([role=alert])',source)
        self.assertNotIn('body.hide-guidance .section-note',shell)
        script=(ROOT / 'frontend/static/reader-ui.js').read_text(encoding='utf-8')
        self.assertIn("['/inventory','/cloud-connection','/purchase-alerts']",script)
        self.assertIn("fetch('/api/account',{cache:'no-store'})",script)

    def test_transit_and_credits_have_operationally_correct_locations(self):
        shell=(ROOT / 'frontend/static/workspace-shell.js').read_text(encoding='utf-8')
        template=(ROOT / 'frontend/templates/reception.html').read_text(encoding='utf-8')
        self.assertIn('data-transit-overview',shell)
        self.assertIn('Camiones visibles',shell)
        self.assertNotIn('Busca o elige un registro',shell)
        self.assertNotIn('function placeCredits',shell)
        self.assertNotIn('guidanceNoticePhrases',shell)
        self.assertNotIn('Revisión José',template)
        self.assertNotIn('Carga manual del MVP',template)


if __name__ == '__main__':
    unittest.main()
