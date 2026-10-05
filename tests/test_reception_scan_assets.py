"""Exercise the real asset routes without initializing or opening any database."""
import threading
import unittest
from urllib.request import urlopen
from backend import app


class ReceptionScanAssetsTests(unittest.TestCase):
    def test_scanner_scripts_and_style_are_served_with_cache_busting(self):
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for name, mime, marker in (
                ('reception-scan.js', 'application/javascript', 'WmsTruckScan'),
                ('reception-np-scan.js', 'application/javascript', 'WmsNpScan'),
                ('reception-scan.css', 'text/css', '.scan-workspace'),
            ):
                with self.subTest(asset=name):
                    with urlopen(f'http://127.0.0.1:{server.server_port}/assets/{name}?v=qa') as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(mime, response.headers['Content-Type'])
                        self.assertIn(marker, response.read().decode('utf-8'))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
