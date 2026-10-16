"""Synthetic history/partial-arrival UI fixture; never an operational database."""
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
scratch=Path(tempfile.mkdtemp(prefix='wms-retired-qa-'))
os.environ.update(TRITON_AUTH_MODE='demo',TRITON_DB_PATH=str(scratch/'qa.db'),TRITON_MAIL_ENABLED='0')
from backend import app
from backend.services.reception_closure import reconcile_closure
from tests.test_reception_pilot_correction import seed_pilot,STAMP
from backend.wsgi import serve

app.DB_PATH=scratch/'qa.db'
app.init_db()
with app.db() as db:
    for index,bl in enumerate(('QA-HISTORY-RETIRED','QA-LIVE-PARTIAL')):
        sid,line,receipt,attention,ref,guide=seed_pilot(db,bl=bl)
        db.execute("UPDATE reception_shipments SET app_status='PROGRAMADO',received_packages=0 WHERE id=?",(sid,))
        db.execute('UPDATE reception_receipts SET received_packages=0 WHERE shipment_id=?',(sid,))
        db.execute("UPDATE reception_attentions SET app_status='CERRADO',condition_status='ANULADA PRUEBA RETIRADA' WHERE shipment_id=?",(sid,))
        db.execute('UPDATE reception_lines SET received_qty=0 WHERE shipment_id=?',(sid,))
        db.execute('UPDATE reception_attention_lines SET verified_qty=0 WHERE attention_id=?',(attention,))
        if index==0:
            for sequence in (2,3,4):
                retired_guide=guide+'-'+str(sequence)
                db.execute('''INSERT INTO reception_truck_guides
                    (guide_code,guide_status,archived_at,archive_reason,created_by,created_at,updated_at)
                    VALUES (?,'CANCELADA',?,'Retiro de pruebas QA','qa',?,?)''',
                    (retired_guide,STAMP,STAMP,STAMP))
                rid=db.execute('''INSERT INTO reception_receipts
                    (shipment_id,sequence_no,received_packages,truck_guide,username,received_at)
                    VALUES (?,?,0,?,'qa',?)''',(sid,sequence,retired_guide,STAMP)).lastrowid
                db.execute('''INSERT INTO reception_attentions
                    (shipment_id,sequence_no,receipt_id,app_status,condition_status,created_at,updated_at)
                    VALUES (?,?,?,'CERRADO','ANULADA PRUEBA RETIRADA',?,?)''',(sid,sequence,rid,STAMP,STAMP))
            reconcile_closure(db,sid,{'confirmed':True,'historical':True,'reason':'Historico sintetico confirmado QA'},
                              'qa.admin','ADMINISTRADOR',return_detail=False)
        else:
            for sequence in (2,3):
                rid=db.execute('''INSERT INTO reception_receipts
                    (shipment_id,sequence_no,received_packages,username,received_at)
                    VALUES (?,?,1,'qa',?)''',(sid,sequence,STAMP)).lastrowid
                db.execute('''INSERT INTO reception_attentions
                    (shipment_id,sequence_no,receipt_id,app_status,created_at,updated_at)
                    VALUES (?,?,?,'REVISION SISTEMA',?,?)''',(sid,sequence,rid,STAMP,STAMP))
print('QA ONLY '+str(scratch),flush=True)
serve('127.0.0.1',int(sys.argv[1]))
