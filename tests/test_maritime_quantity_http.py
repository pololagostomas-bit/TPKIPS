"""Authenticated HTTP boundary for maritime counts, disposable WMS fixture."""
import json
import unittest
from backend import app
from backend.services import reception
from tests import test_cloud_connection as fixtures


class MaritimeQuantityHTTPTests(unittest.TestCase):
    setUp = fixtures.CloudIntegrationTests.setUp
    tearDown = fixtures.CloudIntegrationTests.tearDown
    call = fixtures.CloudIntegrationTests.call

    def test_route_rejects_missing_auth_csrf_and_forged_roles(self):
        with app.db() as c:
            sid=c.execute("""INSERT INTO reception_shipments(bl_awb,transport_type,created_at,updated_at)
                VALUES('QA-SEA','MARITIMO','2026-10-24','2026-10-24')""").lastrowid
            guide=reception.create_scanner_truck_guide(c,'admin.qa','ADMINISTRADOR')['truck_guide']
            reception.add_scanned_truck_bl(c,guide,'QA-SEA','admin.qa','ADMINISTRADOR')
            token,_=app.identity.login(c,'picker.qa','synthetic-picker-password')
        url='/api/receptions/truck-guide/maritime-quantity'
        body={'truck_guide':guide,'shipment_id':sid,'quantity':8,'version':0}
        self.assertEqual(self.call(url,body,cookie='')['status'],401)
        self.assertEqual(self.call(url,body,csrf=False)['status'],403)
        self.assertEqual(self.call(url,body,cookie=app.identity.COOKIE+'='+token)['status'],403)
        saved=self.call(url,body)
        self.assertEqual(saved['status'],200,saved['body'])
        self.assertEqual(json.loads(saved['body'])['count'],8)
        self.assertTrue(json.loads(self.call(url,body)['body'])['duplicate'])
        self.assertEqual(self.call(url,{**body,'quantity':9})['status'],400)
