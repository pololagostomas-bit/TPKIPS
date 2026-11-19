from datetime import datetime
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from openpyxl import Workbook
from backend import app
from backend.services import sts_source
from tests.test_dispatch_sts import PHOTO


HEADERS = ['Tipo_Doc','Número de documento','Status de Documento','Nº de Línea',
    'Número de artículo','Descripción artículo/serv.','Grupo de Articulo',
    'Alm Origen','Alm Destino','Cantidad','FechaCrea_ST','HoraCrea_ST',
    'Nº de Llamada','Nº de Reporte de Servicio']


def row(doc=1001,line=1,np='QA-01',quantity=3,status='Abierto',origin=1,destination='02',group='REPUESTOS',call=1):
    return ['SOL TRANSF',doc,status,line,np,'Pieza sintética',group,origin,destination,
        quantity,datetime(2026,10,1),930,call,call]


def workbook(rows):
    book=Workbook();sheet=book.active;sheet.append(HEADERS)
    for item in rows:sheet.append(item)
    buffer=BytesIO();book.save(buffer);book.close();return buffer.getvalue()


class STSSourceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=app.DB_PATH
        app.DB_PATH=Path(self.folder.name)/'qa.sqlite3';app.init_db()
        with app.db() as db:
            stamp=app.now()
            db.execute("INSERT INTO users(username,display_name,role,active,created_at,updated_at) VALUES('picker','Picker','PICKER_GUIADOR',1,?,?)",(stamp,stamp))
            db.execute("INSERT INTO inventory_stock(item_key,warehouse_key,item_code,warehouse,snapshot_qty,snapshot_day,snapshot_at,is_current,updated_at) VALUES('QA01','1','QA-01','1',10,?,?,1,?)",(stamp[:10],stamp,stamp))

    def tearDown(self):
        app.DB_PATH=self.previous;self.folder.cleanup()

    def load(self,rows,hour=9,complete=False):
        return app.import_daily_excel(workbook(rows),'sts.xlsx','sts',f'2026-11-18T{hour:02d}:00:00',
            'admin','ADMINISTRADOR',sts_complete_snapshot=complete)

    def test_source_repeated_calls_do_not_duplicate_real_sap_lines(self):
        result=self.load([row(),row(call=2),row(line=2),row(doc=2002,status='Cerrado'),row(doc=3003,origin=2)])
        self.assertEqual(result['sts'],1);self.assertEqual(result['lines'],2)
        self.assertEqual(result['repeated_rows'],1)
        order=app.order_payload('STS-SAP-1001')
        self.assertEqual(len(order['lines']),2)
        self.assertEqual(sum(line['required_qty'] for line in order['lines']),6)
        self.assertEqual(order['source_order_date'],'2026-10-01 09:30:00')
        self.assertIsNone(app.order_payload('STS-SAP-2002'))
        with app.db() as db:self.assertEqual(db.execute('SELECT snapshot_qty FROM inventory_stock').fetchone()[0],10)

    def test_same_line_keeps_its_id_when_excel_order_or_metadata_change(self):
        self.load([row(),row(line=2,np='QA-02')])
        old={line['source_row']:line['id'] for line in app.order_payload('STS-SAP-1001')['lines']}
        self.load([row(line=2,np='QA-02'),row(quantity=4)],hour=10)
        new={line['source_row']:line['id'] for line in app.order_payload('STS-SAP-1001')['lines']}
        self.assertEqual(old,new)

    def test_absent_partial_stays_pending_complete_marks_source_only(self):
        self.load([row(),row(doc=1002)],complete=True)
        self.load([row()],hour=10)
        self.assertTrue(app.order_payload('STS-SAP-1002')['source_present'])
        self.load([row()],hour=11,complete=True)
        old=app.order_payload('STS-SAP-1002')
        self.assertFalse(old['source_present']);self.assertEqual(old['lines'],[])
        self.assertNotEqual(old['app_status'],'ENTREGADO')
        with app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM delivery_evidence').fetchone()[0],0)

    def test_closed_known_request_preserves_work_and_photo(self):
        self.load([row()])
        aid=app.create_attention('STS-SAP-1001','admin','ADMINISTRADOR')['id']
        app.assign_attention_responsibles(aid,'picker','picker','admin','ADMINISTRADOR')
        app.change_attention_status(aid,'EN PICKING','picker','PICKER_GUIADOR')
        from backend.services import dispatch_operations as ops
        ops.scan(app,aid,'QA-01','picker','PICKER_GUIADOR');ops.finish_picking(app,aid,'picker','PICKER_GUIADOR')
        app.change_attention_status(aid,'EN GUIADO','picker','PICKER_GUIADOR')
        with app.db() as db:app.save_delivery_evidence(db,aid,PHOTO,'picker','PICKER_GUIADOR')
        self.load([row(status='Cerrado')],hour=10)
        with app.db() as db:
            attention=app.attention_payload(db,aid)
            self.assertEqual(attention['app_status'],'EN GUIADO')
            self.assertEqual(attention['lines'][0]['picked_qty'],3)
            self.assertIsNotNone(attention['delivery_evidence'])

    def test_wrong_file_conflicts_old_cut_and_permissions_do_not_change_data(self):
        self.load([row()])
        with self.assertRaises(ValueError):self.load([row(),row(quantity=5)],hour=10,complete=True)
        with self.assertRaises(ValueError):self.load([row(quantity=5)],hour=8)
        with self.assertRaises(PermissionError):
            app.import_daily_excel(workbook([row()]),'sts.xlsx','sts','2026-11-18T10:00:00','picker','PICKER')
        self.assertEqual(app.order_payload('STS-SAP-1001')['lines'][0]['required_qty'],3)

    def test_numeric_np_and_headers_keep_literal_code(self):
        parsed=sts_source.parse_workbook(workbook([row(np='00123'),row(line=2,np=123)]))
        self.assertEqual({line['item_code'] for document in parsed['open'].values() for line in document['lines'].values()},{'00123','123'})

    def begin(self):
        self.load([row()])
        aid=app.create_attention('STS-SAP-1001','admin','ADMINISTRADOR')['id']
        app.assign_attention_responsibles(aid,'picker','picker','admin','ADMINISTRADOR')
        app.change_attention_status(aid,'EN PICKING','picker','PICKER_GUIADOR')
        return aid

    def test_plan_refreshes_before_work_but_freezes_active_attention(self):
        self.load([row()])
        aid=app.create_attention('STS-SAP-1001','admin','ADMINISTRADOR')['id']
        self.load([row(quantity=4)],hour=10)
        with app.db() as db:self.assertEqual(app.attention_payload(db,aid)['lines'][0]['planned_qty'],4)
        app.assign_attention_responsibles(aid,'picker','picker','admin','ADMINISTRADOR')
        app.change_attention_status(aid,'EN PICKING','picker','PICKER_GUIADOR')
        self.load([row(quantity=5)],hour=11)
        with app.db() as db:self.assertEqual(app.attention_payload(db,aid)['lines'][0]['planned_qty'],4)
        with self.assertRaises(ValueError):self.load([row(np='WRONG')],hour=12)
        self.assertEqual(app.order_payload('STS-SAP-1001')['lines'][0]['required_qty'],5)

    def test_same_cut_can_be_upgraded_to_complete_without_duplicate_or_downgrade(self):
        self.load([row(),row(doc=1002)])
        content=workbook([row()])
        def load(complete=False):
            return app.import_daily_excel(content,'sts.xlsx','sts','2026-11-18T10:00:00','admin','ADMINISTRADOR',sts_complete_snapshot=complete)
        load();self.assertTrue(load()['duplicate'])
        self.assertNotIn('duplicate',load(True))
        self.assertFalse(app.order_payload('STS-SAP-1002')['source_present'])
        self.assertTrue(load()['complete_snapshot'])
        with app.db() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM data_imports WHERE source_type='sts'").fetchone()[0],2)

    def test_missing_source_line_only_deactivates_on_complete_snapshot(self):
        self.load([row(),row(line=2,np='QA-02')])
        self.load([row()],hour=10)
        self.assertEqual(len(app.order_payload('STS-SAP-1001')['lines']),2)
        self.load([row()],hour=11,complete=True)
        self.assertEqual(len(app.order_payload('STS-SAP-1001')['lines']),1)
        self.assertEqual(len(app.order_payload('STS-SAP-1001')['attended_lines']),1)

    def test_next_ov_cut_preserves_imported_sts_and_does_not_seed_attention(self):
        from tests.test_daily_operations import dispatch
        self.load([row()])
        app.import_daily_excel(dispatch([('QA-OV',1,'QA-02',2,5,'ABIERTO')]),'ov.xlsx','dispatch',
            '2026-11-18T10:00:00','admin','ADMINISTRADOR')
        result=app.order_payload('STS-SAP-1001')
        self.assertTrue(result['source_present']);self.assertEqual(result['attentions'],[])

    def test_delivery_remains_subtracted_after_new_cut_and_missing_sts_keeps_receipt(self):
        from backend.services import dispatch_operations as ops
        aid=self.begin()
        with app.db() as db:line=app.attention_payload(db,aid)['lines'][0]['id']
        ops.confirm_line(app,aid,line,1,'Envío parcial','picker','PICKER_GUIADOR')
        ops.finish_picking(app,aid,'picker','PICKER_GUIADOR')
        app.change_attention_status(aid,'EN GUIADO','picker','PICKER_GUIADOR')
        app.change_attention_status(aid,'GUIADO FINALIZADO','picker','PICKER_GUIADOR')
        with app.db() as db:app.save_delivery_evidence(db,aid,PHOTO,'picker','PICKER_GUIADOR')
        ops.ship(app,aid,{'guide_reference':'QA-GUIA'},'picker','PICKER_GUIADOR')
        self.load([row()],hour=10,complete=True)
        self.assertEqual(app.order_payload('STS-SAP-1001')['dispatch_context']['pending_qty'],2)
        self.load([row(doc=1002)],hour=11,complete=True)
        self.assertIn('STS-SAP-1001',[item['sap_ov'] for item in app.orders_payload(document_kind='STS')])
        ops.receive(app,aid,{'request_key':'QA-RECEIPT','receiver':'Receptor','evidence':PHOTO,
            'lines':[{'id':line,'quantity':1}]},'admin','ADMINISTRADOR')
        self.assertNotIn('STS-SAP-1001',[item['sap_ov'] for item in app.orders_payload(document_kind='STS')])
        self.assertEqual(app.order_payload('STS-SAP-1001')['shipments'][0]['state'],'RECIBIDO')

    def test_inactive_draft_leaves_queue_but_is_searchable_and_manual_sts_survives(self):
        from backend.services import dispatch_operations as ops
        with app.db() as db:ops.save_branch(db,{'code':'02','name':'Sucursal QA'},'admin','ADMINISTRADOR')
        manual=ops.create_request(app,{'request_key':'manual','kind':'STS','destination':'02','due_date':'2026-12-01',
            'lines':[{'item_code':'QA-01','quantity':1}]},'admin','ADMINISTRADOR')['sap_ov']
        self.load([row()]);app.create_attention('STS-SAP-1001','admin','ADMINISTRADOR')
        self.load([row(status='Cerrado')],hour=10,complete=True)
        visible=[item['sap_ov'] for item in app.orders_payload(document_kind='STS')]
        self.assertNotIn('STS-SAP-1001',visible);self.assertIn(manual,visible)
        self.assertEqual(app.orders_payload(search='STS-SAP-1001')[0]['sap_ov'],'STS-SAP-1001')

    def test_invalid_or_out_of_scope_file_cannot_clear_queue(self):
        self.load([row()])
        for rows in ([],[row(origin=2)],[row(np='=FORMULA')],[row(quantity=float('inf'))]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.load(rows,hour=10,complete=True)
        self.assertTrue(app.order_payload('STS-SAP-1001')['source_present'])

    def test_headers_can_move_and_closed_history_can_have_multiple_destinations(self):
        book=Workbook();sheet=book.active;sheet.append(['Reporte']);sheet.append(list(reversed(HEADERS)))
        for r in [row(),row(doc=2002,status='Cerrado'),row(doc=2002,line=2,status='Cerrado',destination='03')]:sheet.append(list(reversed(r)))
        buffer=BytesIO();book.save(buffer);book.close()
        parsed=sts_source.parse_workbook(buffer.getvalue())
        self.assertEqual(set(parsed['open']),{'1001'});self.assertEqual(set(parsed['closed']),{'2002'})


if __name__=='__main__':unittest.main()
