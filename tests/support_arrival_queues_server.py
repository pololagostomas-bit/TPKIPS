"""Synthetic arrival queues only; no production data or external workers."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix='wms-arrival-queues-qa-'))
os.environ.update(TRITON_AUTH_MODE='demo',TRITON_DB_PATH=str(scratch/'qa.db'),TRITON_MAIL_ENABLED='0')
from backend import app
from backend.services.reception_sla import LIMA
from backend.wsgi import serve
from tests.test_reception_work import shipment, complete_refs, STAMP

app.DB_PATH = scratch/'qa.db'
app.init_db()
today = datetime.now(LIMA).date()
with app.db() as db:
    for bl,day,fr,status,arrival in (
            ('QA-PAST',today-timedelta(days=1),None,'PROGRAMADO',None),
            ('QA-FR-FUTURE',today+timedelta(days=7),'QA-FR','PROGRAMADO',None),
            ('QA-TODAY',today,None,'PROGRAMADO',None),
            ('QA-FUTURE',today+timedelta(days=7),None,'PROGRAMADO',None),
            ('QA-NO-DATE',None,None,'PROGRAMADO',None),
            ('QA-IN-PROCESS',None,None,'UBICACION',STAMP),
            ('QA-CLOSED',today-timedelta(days=30),'QA-FR','CERRADO',None)):
        sid = shipment(db,bl=bl,status=status,arrival=arrival,ips='')
        db.execute('UPDATE reception_shipments SET scheduled_date=?,fr_number=? WHERE id=?',
                   (day.isoformat() if day else None,fr,sid))
    sid = shipment(db,bl='QA-REF-FR',ips='IP-101')
    complete_refs(db,sid,1)
    guide = 'QA-TRUCK-EXISTING'
    db.execute('''INSERT INTO reception_truck_guides
        (guide_code,guide_status,is_confirmed,source_type,created_by,created_at,updated_at)
        VALUES (?,'PENDIENTE',1,'ADMINISTRADOR','qa',?,?)''',(guide,STAMP,STAMP))
    db.execute('''INSERT INTO reception_truck_bl_manifest
        (truck_guide,shipment_id,planned_packages,created_by,created_at,updated_at)
        VALUES (?,?,1,'qa',?,?)''',(guide,sid,STAMP,STAMP))
print('QA ONLY '+str(scratch),flush=True)
serve('127.0.0.1',int(sys.argv[1]))
