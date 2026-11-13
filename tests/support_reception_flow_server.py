"""Isolated reception states/roles; no cloud, carrier or mail workers."""
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
scratch=Path(tempfile.mkdtemp(prefix='reception-flow-qa-'))
os.environ.update(TRITON_AUTH_MODE='local',TRITON_DB_PATH=str(scratch/'qa.sqlite'),
    TRITON_BOOTSTRAP_ADMIN_USERNAME='qa.reader',TRITON_BOOTSTRAP_ADMIN_PASSWORD='QA-password-only-123!',
    TRITON_COOKIE_SECURE='0',WMS_CLOUD_AUTO_SYNC='0',WMS_PURCHASE_ALERT_WORKER='0',
    WMS_DHL_ENABLED='0',TRITON_MAIL_ENABLED='0',WMS_TRANSFER_WORKER='0')
from backend import app,password_policy,wsgi
from backend.services import reception
from tests.test_reception_partial_count_http import seed_partial

password_policy.prepare()
with app.db() as db:
    for user,role in [('qa.assistant','ASISTENTE_RECEPCION'),('qa.auxiliary','AUXILIAR_RECEPCION')]:
        app.identity.save(db,{'username':user,'display_name':user,'role':role,
            'password':'QA-password-only-123!'},'qa.reader',app.ROLES)
    for index,state in enumerate(reception.RECEPTION_STATES,1):
        sid,aid,ids=seed_partial(db,'QA-FLOW-'+str(index),scanned=10)
        db.execute("UPDATE reception_shipments SET app_status=?,fr_number=NULL,current_assistant='qa.assistant',current_auxiliary='qa.auxiliary' WHERE id=?",(state,sid))
        db.execute("UPDATE reception_attentions SET app_status=?,current_assistant='qa.assistant',current_auxiliary='qa.auxiliary',system_quantities_initialized=1 WHERE id=?",(state,aid))
        db.execute("UPDATE reception_lines SET brand='BOBCAT',description='Repuesto de prueba' WHERE shipment_id=?",(sid,))
        if state=='PROGRAMADO':
            db.execute('DELETE FROM reception_attention_lines WHERE attention_id=?',(aid,))
            db.execute('DELETE FROM reception_attentions WHERE id=?',(aid,))
            db.execute('UPDATE reception_shipments SET received_packages=0,first_arrival_at=NULL WHERE id=?',(sid,))
            db.execute('UPDATE reception_lines SET received_qty=0,np_scanned_at=NULL WHERE shipment_id=?',(sid,))
        if state=='CERRADO':
            db.execute("UPDATE reception_attentions SET completed_at='2026-11-13 12:00:00' WHERE id=?",(aid,))
        reception._write_history(db,sid,'QA','app_status','PROGRAMADO',state,'qa.reader')
wsgi.application=password_policy.application
print('QA ONLY http://127.0.0.1:'+sys.argv[1],flush=True)
wsgi.serve('127.0.0.1',int(sys.argv[1]))
