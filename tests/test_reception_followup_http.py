import json
import unittest
from tests import test_reception_transfer as fixtures
from backend import app


class FollowupHttpTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.TransferTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.TransferTests.tearDownClass.__func__)
    setUp=fixtures.TransferTests.setUp
    request=fixtures.TransferTests.request

    def cookie(self,role='CONSULTA_REPUESTOS'):
        name='qa.'+role.lower()
        app.identity.save(self.db,{'username':name,'display_name':'QA','role':role,
            'password':'QA-followup-only-123!'},'qa',app.ROLES)
        token,_=app.identity.login(self.db,name,'QA-followup-only-123!')
        self.db.commit()
        return {'HTTP_COOKIE':app.identity.COOKIE+'='+token}

    def test_reader_role_exists_and_cannot_reach_operations(self):
        self.assertIn('CONSULTA_REPUESTOS',app.ROLES)
        cookie=self.cookie()
        for path in ['/api/receptions','/api/users','/api/reception-transfer/status','/api/cloud-connection/status', '/api/receptions/report','/api/daily-stock']:
            with self.subTest(path=path):self.assertEqual(self.request(path,'GET',extra=cookie)[0],403)
        for path in ['/api/receptions/1/status','/api/daily-cloud-sync','/api/account']:
            with self.subTest(path=path):self.assertEqual(self.request(path,'POST',{},extra=cookie)[0],403)

    def test_only_intended_roles_can_view(self):
        for role in ['ADMINISTRADOR','CONSULTA_REPUESTOS','ASISTENTE_RECEPCION','PICKER']:
            cookie=self.cookie(role)
            expected=200 if role in {'ADMINISTRADOR','CONSULTA_REPUESTOS'} else 403
            self.assertEqual(self.request('/api/parts-followup','GET',extra=cookie)[0],expected)
            self.assertEqual(self.request('/parts-followup','GET',extra=cookie)[0],expected)

    def test_consultation_is_get_only_and_redirects_landing(self):
        cookie=self.cookie()
        status,headers,body=self.request('/','GET',extra=cookie)
        self.assertEqual(status,303);self.assertEqual(headers['Location'],'/parts-followup')
        self.assertEqual(self.request('/api/parts-followup','POST',extra=cookie)[0],405)
        status,headers,body=self.request('/api/parts-followup','GET',extra=cookie)
        self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertIn('summary',json.loads(body))
        self.assertNotIn(b'token',body)

    def test_unauthenticated_and_spoofed_headers_cannot_view(self):
        status,headers,body=self.request('/api/parts-followup','GET',extra={'HTTP_X_ROLE':'ADMINISTRADOR','HTTP_X_USER':'qa'})
        self.assertEqual(status,401)

    def test_entering_step_five_applies_costing_already_present_in_excel(self):
        from backend.services import reception
        from openpyxl import Workbook
        receipt=self.db.execute("""INSERT INTO reception_receipts(shipment_id,sequence_no,received_packages,username,received_at)
            VALUES(?,1,1,'qa','2026-10-01T08:00:00')""",(self.sid,)).lastrowid
        self.db.execute("UPDATE reception_attentions SET receipt_id=?,app_status='VALIDACION' WHERE id=?",(receipt,self.aid))
        self.db.execute("UPDATE reception_shipments SET app_status='VALIDACION',expected_packages=1,received_packages=1 WHERE id=?",(self.sid,))
        line=self.db.execute("INSERT INTO reception_lines(shipment_id,np_code,ip_reference,expected_qty,received_qty) VALUES(?,'QA-NP','IP260001',1,1)",(self.sid,)).lastrowid
        self.db.execute('INSERT INTO reception_attention_lines(attention_id,reception_line_id,planned_qty,verified_qty) VALUES(?,?,1,1)',(self.aid,line))
        book=Workbook();sheet=book.active;sheet.title=reception.ACCOUNTING_SHEET_NAME
        sheet.append(['IP','AWB','FACTURA RESERVA','ENTRADA DE MERCANCIA','FECHA DE RECEPCION','FECHA DE EM','FECHA DE COSTEO'])
        sheet.append(['IP260001','QA-BL','QA-FR','QA-EM','2026-10-01','2026-10-02','2026-10-03'])
        reception.import_reception_accounting_workbook(self.db,book,'qa.xlsx','qa','ADMINISTRADOR')
        self.assertEqual(self.db.execute('SELECT app_status FROM reception_attentions WHERE id=?',(self.aid,)).fetchone()[0],'VALIDACION')
        result=reception.change_reception_status(self.db,self.sid,{'attention_id':self.aid,'status':'SOLICITUD TRANSFERENCIA','validation_result':'CONFORME'},'qa','ADMINISTRADOR')
        self.assertEqual(result['app_status'],'CERRADO')
        self.assertEqual(result['costing']['costing_date'],'2026-10-03')
        self.assertEqual(result['transfer_assistant_checked'],0)
