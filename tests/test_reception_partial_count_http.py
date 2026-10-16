"""HTTP transaction, assignee and retry contract on a temporary database."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import app
from backend.services import reception


def seed_partial(db, bl='QA-PARTIAL-HTTP', scanned=9):
    sid=db.execute('''INSERT INTO reception_shipments
        (bl_awb,app_status,received_packages,fr_number,current_assistant,current_auxiliary,
         first_arrival_at,created_at,updated_at)
        VALUES (?,'REVISION SISTEMA',1,'QA-FR','receiver','auxiliary',?,?,?)''',
        (bl,'2026-10-16 08:00:00','2026-10-16 08:00:00','2026-10-16 08:00:00')).lastrowid
    for number in range(10):
        db.execute('''INSERT INTO reception_lines
            (shipment_id,np_code,description,expected_qty) VALUES (?,?,?,1)''',
            (sid,f'NP-{number:02d}',f'Repuesto de prueba {number}'))
    shipment=db.execute('SELECT * FROM reception_shipments WHERE id=?',(sid,)).fetchone()
    attention=reception._create_reception_attention(db,shipment,None,'receiver','REVISION SISTEMA')['id']
    db.execute('''UPDATE reception_attention_lines SET verified_qty=1,
        count_location_saved=1,count_location_manual=1 WHERE attention_id=?''',(attention,))
    ids=[row[0] for row in db.execute('SELECT id FROM reception_lines WHERE shipment_id=? ORDER BY id',(sid,))]
    for lid in ids[:scanned]:
        db.execute('''UPDATE reception_attention_lines SET np_scanned_at='2026-10-16 08:00:00',
            np_scanned_by='receiver' WHERE attention_id=? AND reception_line_id=?''',(attention,lid))
    reception._sync_reception_line_totals(db,sid)
    return sid,attention,ids


class PartialCountHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd,name=tempfile.mkstemp(prefix='wms-partial-http-',suffix='.db');os.close(fd)
        cls.path=Path(name)
        cls.env=patch.dict(os.environ,{'TRITON_AUTH_MODE':'demo','TRITON_MAIL_ENABLED':'0'})
        cls.database=patch.object(app,'DB_PATH',cls.path)
        cls.env.start();cls.database.start();app.init_db()
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
        cls.database.stop();cls.env.stop()
        for suffix in ('','-wal','-shm'):Path(str(cls.path)+suffix).unlink(missing_ok=True)

    def setUp(self):
        with app.db() as db:self.sid,self.attention,self.ids=seed_partial(db,self.id())
        self.data={'confirmed':True,'attention_id':self.attention,'line_ids':[self.ids[-1]]}

    def post(self, data=None, user='receiver', role='ASISTENTE_RECEPCION'):
        return urlopen(Request(self.base+f'/api/receptions/{self.sid}/count/partial',
            data=json.dumps(self.data if data is None else data).encode(),
            headers={'Content-Type':'application/json','X-User':user,'X-Role':role}))

    def test_endpoint_advances_nine_and_retry_does_not_duplicate_history(self):
        for attempt in range(2):
            with self.post() as response:result=json.load(response)
            self.assertEqual(result['app_status'],'EM')
            self.assertEqual(sum(bool(line['np_scanned_at']) for line in result['lines']),9)
            self.assertEqual(result['lines'][-1]['attention_verified_qty'],0)
        with app.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reception_history WHERE shipment_id=? AND event_type='CONTEO PARCIAL'",(self.sid,)).fetchone()[0],1)

    def test_role_and_assignment_are_checked_in_endpoint(self):
        for role,user in [('PICKER','receiver'),('ASISTENTE_RECEPCION','stranger')]:
            with self.assertRaises(HTTPError) as error:self.post(user=user,role=role)
            self.assertEqual(error.exception.code,403)

    def test_changed_missing_list_is_json_error_without_overwriting_new_scan(self):
        with app.db() as db:
            db.execute("UPDATE reception_attention_lines SET np_scanned_at='2026-10-16 09:00:00' WHERE attention_id=? AND reception_line_id=?",(self.attention,self.ids[-1]))
        with self.assertRaises(HTTPError) as error:self.post()
        self.assertEqual(error.exception.code,400)
        self.assertIn('lecturas cambiaron',json.load(error.exception)['error'])
        with app.db() as db:
            self.assertEqual(db.execute('SELECT verified_qty FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',(self.attention,self.ids[-1])).fetchone()[0],1)

    def test_fr_failure_rolls_back_zero_and_partial_audit(self):
        with app.db() as db:db.execute('UPDATE reception_shipments SET fr_number=NULL WHERE id=?',(self.sid,))
        with self.assertRaises(HTTPError) as error:self.post()
        self.assertEqual(error.exception.code,403)
        with app.db() as db:
            row=db.execute('SELECT verified_qty,np_unreceived_reason FROM reception_attention_lines WHERE attention_id=? AND reception_line_id=?',(self.attention,self.ids[-1])).fetchone()
            self.assertEqual(tuple(row),(1,None))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reception_history WHERE shipment_id=? AND event_type='CONTEO PARCIAL'",(self.sid,)).fetchone()[0],0)


if __name__=='__main__':unittest.main()
