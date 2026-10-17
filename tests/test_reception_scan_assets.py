"""Exercise the real asset routes without initializing or opening any database."""
import threading
import hashlib
from pathlib import Path
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
                ('wms-camera.js', 'application/javascript', 'WmsCamera'),
                ('wms-camera.css', 'text/css', '.wms-camera-dialog'),
                ('html5-qrcode.min.js', 'application/javascript', 'Html5Qrcode'),
                ('html5-qrcode.LICENSE.txt', 'text/plain', 'Apache License'),
            ):
                with self.subTest(asset=name):
                    with urlopen(f'http://127.0.0.1:{server.server_port}/assets/{name}?v=qa') as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(mime, response.headers['Content-Type'])
                        self.assertIn('no-store', ','.join(response.headers.get_all('Cache-Control', [])))
                        self.assertIn(marker, response.read().decode('utf-8'))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_local_decoder_is_the_verified_unmodified_pinned_bundle(self):
        source = Path(__file__).resolve().parents[1] / 'frontend/static/html5-qrcode.min.js'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
            '660b12437b1d747e3e68b8be0685c08cb728140110ad213f167b14b66f8b1d8e')
