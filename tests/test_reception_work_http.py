"""Exercise work endpoints on a disposable DB, with mail/OAuth workers absent."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import app
from tests.test_reception_work import shipment, complete_refs


class ReceptionWorkHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd,name=tempfile.mkstemp(prefix='wms-work-http-',suffix='.db')
        os.close(fd)
        cls.path=Path(name)
        cls.env=patch.dict(os.environ,{'TRITON_AUTH_MODE':'demo'})
        cls.database=patch.object(app,'DB_PATH',cls.path)
        cls.env.start();cls.database.start()
        app.init_db()
        with app.db() as db:
            cls.documented=shipment(db,bl='TEST-DOCUMENTED')
            complete_refs(db,cls.documented)
            shipment(db,bl='TEST-OPEN')
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
        cls.database.stop();cls.env.stop()
        for suffix in ('','-wal','-shm'):
            Path(str(cls.path)+suffix).unlink(missing_ok=True)

    def get(self,path,user='demo.admin',role='ADMINISTRADOR'):
        return urlopen(Request(self.base+path,headers={'X-User':user,'X-Role':role}))

    def test_documented_bl_is_history_and_summary_matches(self):
        with self.get('/api/receptions/work') as response:
            data=json.load(response)
        self.assertEqual([row['bl_awb'] for row in data['items']],['TEST-OPEN'])
        with self.get('/api/work-summary?module=reception') as response:
            self.assertEqual(json.load(response),data['summary'])
        with self.get('/api/receptions/work?history=1&search=DOCUMENTED') as response:
            data=json.load(response)
        self.assertEqual(data['items'][0]['work_status'],'FR/EM COMPLETAS')
        with app.db() as db:
            self.assertEqual(db.execute('SELECT app_status FROM reception_shipments WHERE id=?',
                                       (self.documented,)).fetchone()[0],'PROGRAMADO')

    def test_assets_and_script_order_are_served(self):
        for name in ('reception-work.js','reception-work.css'):
            with self.get('/assets/'+name+'?v=qa') as response:
                self.assertEqual(response.status,200)
                self.assertTrue(response.read())
                self.assertEqual(response.headers['Cache-Control'],'no-cache')
        with self.get('/reception') as response:
            html=response.read().decode('utf-8')
        self.assertLess(html.index('/assets/reception-work.js'),html.index('/assets/workspace-shell.js'))

    def test_work_roles_are_enforced(self):
        with self.get('/api/receptions/work','stranger','ASISTENTE_RECEPCION') as response:
            self.assertEqual(json.load(response)['items'],[])
        with self.assertRaises(HTTPError) as error:
            self.get('/api/receptions/work','picker.test','PICKER')
        self.assertEqual(error.exception.code,403)
        self.assertIn('error',json.load(error.exception))

    def test_invalid_pagination_is_json_400(self):
        with self.assertRaises(HTTPError) as error:
            self.get('/api/receptions/work?offset=broken')
        self.assertEqual(error.exception.code,400)
        self.assertIn('error',json.load(error.exception))


if __name__=='__main__':
    unittest.main()
