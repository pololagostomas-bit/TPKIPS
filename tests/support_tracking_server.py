"""Synthetic-only browser fixture. Never opens an operational database."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--synthetic',action='store_true',required=True);parser.add_argument('--port',type=int,default=50737);args=parser.parse_args()
    if not 1024 <= args.port <= 65535:raise ValueError('Invalid QA port')
    with tempfile.TemporaryDirectory(prefix='triton-tracking-qa-') as folder:
        os.environ.update(TRITON_DB_PATH=str(Path(folder)/'qa.db'),TRITON_AUTH_MODE='local',TRITON_COOKIE_SECURE='0',TRITON_MAIL_ENABLED='0',WMS_CLOUD_AUTO_SYNC='0',WMS_TRANSFER_WORKER='0',TRITON_BOOTSTRAP_ADMIN_USERNAME='admin.qa',TRITON_BOOTSTRAP_ADMIN_PASSWORD='synthetic-admin-password')
        from backend import app,password_policy
        from backend.services import tracking
        from openpyxl import Workbook
        from waitress import serve
        password_policy.prepare()
        with app.db() as db:
            app.identity.save(db,{'username':'tracking.qa','display_name':'Comercial · prueba','role':'CONSULTA_TRACKING','password':'synthetic-tracking-password'},'admin.qa',app.ROLES)
            wb=Workbook();sheet=wb.active;sheet.title='IMPORTACIONES'
            sheet.append(['OV','ORDEN DE COMPRA','CODIGO','GUIA DE IMPORTACION','DESCRIPCION','MARCA','CANTIDAD SOLICITADA','CANTIDAD FACTURADA','CANTIDAD PENDIENTE','PEDIDO TRITON','PEDIDO FABRICA','FECHA DE SOLICITUD DE IMP OV','FECHA DE PEDIDO','FECHA DE FACTURA','FECHA RECOJO','FECHA CALLAO','FECHA TRITON ESTIMADA','FECHA CONFIRMADA TRITON','FECHA COSTEO','N° FACTURA','MODO DE TRANSPORTE'])
            sheet.append(['OV-DEMO-0421','12345','REP-001','BL-DEMO-01','Kit de sellos hidráulicos','TRITON',10,10,0,'IP-DEMO-01','FAB-DEMO-01','2026-11-02','2026-11-04','2026-11-10','2026-11-12','2026-11-18','2026-11-20','2026-11-22',None,'FAC-DEMO-01','MARITIMO'])
            sheet.append(['OV-DEMO-0421','12345','REP-002','BL-DEMO-02','Bomba de dirección · entrega pendiente','TRITON',2,2,0,'IP-DEMO-02','FAB-DEMO-02','2026-11-02','2026-11-05','2026-11-15',None,None,'2026-12-04','2026-12-06'])
            sheet.append(['STOCK','54321','REP-STOCK-03','','Filtro de mantenimiento','TRITON',15,0,15,'IP-DEMO-STOCK'])
            sheet.append(['COT-DEMO-03','PRE-900001','','','Referencia documental en cotización','TRITON'])
            tracking.store_workbook(db,wb,'synthetic-importations.xlsx','2026-11-23T14:00:00-05:00');wb.close()
            db.execute("INSERT INTO reception_shipments(bl_awb,app_status,transport_type,created_at,updated_at) VALUES('BL-DEMO-01','ARRIBADO','MARITIMO','2026-11-19','2026-11-19')")
            sid=db.execute("SELECT id FROM reception_shipments WHERE bl_awb='BL-DEMO-01'").fetchone()[0]
            db.execute("INSERT INTO reception_lines(shipment_id,source_sheet,ov_number,oc_number,np_code,ip_reference,description,expected_qty,requested_qty,received_qty) VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,'IMPORTACIONES','OV-DEMO-0421','12345','REP-001','IP-DEMO-01','Kit de sellos hidráulicos',10,10,3))
            db.execute("INSERT INTO reception_receipts(shipment_id,sequence_no,received_packages,username,received_at) VALUES(?,1,1,'tracking.qa','2026-11-19T09:00:00-05:00')",(sid,))
        print('Synthetic Tracking QA ready',args.port,flush=True)
        serve(password_policy.application,host='127.0.0.1',port=args.port,threads=2)

if __name__=='__main__':main()
