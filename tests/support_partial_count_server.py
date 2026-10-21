"""Disposable ten-SKU deliveries, no external workers or operational data."""
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
scratch=Path(tempfile.mkdtemp(prefix='wms-partial-count-qa-'))
os.environ.update(TRITON_AUTH_MODE='demo',TRITON_DB_PATH=str(scratch/'qa.db'),TRITON_MAIL_ENABLED='0',
    WMS_CLOUD_AUTO_SYNC='0',WMS_PURCHASE_ALERT_WORKER='0',WMS_TRANSFER_WORKER='0',WMS_DHL_ENABLED='0')
from backend import app
from backend.services import reception
from backend.services.reception_partial_count import continue_partial_count
from backend.wsgi import serve
from tests.test_reception_partial_count_http import seed_partial

app.DB_PATH=scratch/'qa.db'
app.init_db()
with app.db() as db:
    for index in range(1,14):
        sid,attention,ids=seed_partial(db,f'QA-PARTIAL-{index}',scanned=9 if index in {6,13} else 0)
        db.execute("UPDATE reception_shipments SET current_assistant='demo.admin',current_auxiliary='demo.admin' WHERE id=?",(sid,))
        db.execute("UPDATE reception_attentions SET current_assistant='demo.admin',current_auxiliary='demo.admin',system_quantities_initialized=1 WHERE id=?",(attention,))
        if index in {6,13}:
            continue_partial_count(db,sid,{'confirmed':True,'attention_id':attention,'line_ids':[ids[-1]]},'demo.admin','ADMINISTRADOR')
            db.execute("UPDATE reception_shipments SET em_number='QA-EM' WHERE id=?",(sid,))
            db.execute("UPDATE reception_attentions SET app_status='SOLICITUD TRANSFERENCIA',transfer_assistant_checked=1 WHERE id=?",(attention,))
            reception.change_reception_status(db,sid,{'attention_id':attention,'status':'CERRADO'},'demo.admin','ADMINISTRADOR')
            if index==13:
                reception._create_reception_attention(db,
                    db.execute('SELECT * FROM reception_shipments WHERE id=?',(sid,)).fetchone(),
                    None,'demo.admin','REVISION SISTEMA')
print('QA ONLY '+str(scratch),flush=True)
serve('127.0.0.1',int(sys.argv[1]))
