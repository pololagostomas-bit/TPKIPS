import base64
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from backend.services import reception, reception_brands as brands
from backend.services.traceability import init_traceability_schema
from scripts import extract_brand_logos as extraction

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9xkAAAAASUVORK5CYII=')


class ReceptionBrandTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.logo_dir = self.root / 'brand-logos'
        self.logo_dir.mkdir()
        self.env = patch.dict(os.environ, {'WMS_BRAND_LOGO_DIR':str(self.logo_dir)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.scratch.cleanup()

    def test_catalog_normalizes_regions_without_losing_unknown_or_ambiguous_brands(self):
        self.assertEqual(len(brands.BRANDS), 10)
        for name in brands.BRANDS:
            self.assertEqual(brands.brand_name(' ' + name.lower() + ' - EUROPA '), name)
        for value in ('Bobcat India', 'BOBCAT-EUROPA', 'BOBCAT / USA'):
            self.assertEqual(brands.brand_name(value), 'BOBCAT')
        for value in ('BOBCAT CROWN', 'MYBOBCAT', 'OTRA INDIA'):
            self.assertEqual(brands.brand_name(value), value)
        self.assertEqual(brands.brand_name(None), '')

    def test_image_binding_uses_named_key_and_relation_ids_not_file_or_key_order(self):
        metadata = ET.fromstring(f'''<metadata xmlns="{extraction.MAIN}" xmlns:rich="{extraction.RICH}">
            <metadataTypes><metadataType name="XLRICHVALUE"/></metadataTypes>
            <futureMetadata name="XLRICHVALUE"><bk><rich:rvb i="0"/></bk></futureMetadata>
            <valueMetadata><bk><rc t="1" v="0"/></bk></valueMetadata></metadata>''')
        values = ET.fromstring(f'<rvData xmlns="{extraction.RICH}"><rv s="0"><v>5</v><v>1</v></rv></rvData>')
        structures = ET.fromstring(f'<rvStructures xmlns="{extraction.RICH}"><s t="_localImage"><k n="CalcOrigin"/><k n="_rvRel:LocalImageIdentifier"/></s></rvStructures>')
        links = ET.fromstring(f'<richValueRels xmlns="{extraction.RICH_REL}" xmlns:r="{extraction.REL}"><rel r:id="first"/><rel r:id="second"/></richValueRels>')
        targets = {'second':'xl/media/correct.png','first':'xl/media/wrong.png'}
        cell = ET.Element('c', vm='1')
        self.assertEqual(extraction.local_image_part(None,cell,metadata,values,structures,links,targets), 'xl/media/correct.png')
        for bad in ('-1', '2'):
            values[0][1].text = bad
            with self.assertRaises(ValueError):
                extraction.local_image_part(None,cell,metadata,values,structures,links,targets)

    def test_logo_urls_version_private_bytes_and_do_not_guess_other_brand_logos(self):
        (self.logo_dir / 'bobcat.png').write_bytes(PNG)
        first = brands.label_brand('BOBCAT EUROPA', self.root / 'qa.sqlite')
        self.assertEqual(first['label_brand'], 'BOBCAT')
        self.assertIn('/api/reception-brand-logo?brand=BOBCAT&v=', first['brand_logo_url'])
        self.assertEqual(brands.label_brand('CROWN INDIA', self.root / 'qa.sqlite')['brand_logo_url'], '')
        (self.logo_dir / 'bobcat.png').write_bytes(PNG + b'changed')
        self.assertNotEqual(brands.label_brand('BOBCAT', self.root / 'qa.sqlite')['brand_logo_url'], first['brand_logo_url'])

    def test_invalid_ambiguous_and_oversized_assets_are_not_served(self):
        for value in ('../bobcat', '/etc/passwd', 'BOBCAT INDIA', ''):
            self.assertIsNone(brands.logo_asset(value, self.root / 'qa.sqlite'))
        image = self.logo_dir / 'bobcat.png'
        image.write_bytes(b'<svg onload="bad()"></svg>')
        self.assertIsNone(brands.logo_asset('BOBCAT', self.root / 'qa.sqlite'))
        image.write_bytes(PNG + b'x' * brands.MAX_LOGO_BYTES)
        self.assertIsNone(brands.logo_asset('BOBCAT', self.root / 'qa.sqlite'))
        image.write_bytes(PNG)
        (self.logo_dir / 'bobcat.jpg').write_bytes(b'\xff\xd8\xfftest')
        self.assertIsNone(brands.logo_asset('BOBCAT', self.root / 'qa.sqlite'))

    def test_unreadable_logo_directory_cannot_break_a_reception_detail(self):
        with patch.object(Path, 'is_file', side_effect=PermissionError('QA unreadable folder')):
            self.assertEqual(brands.label_brand('BOBCAT INDIA', self.root / 'qa.sqlite'),
                             {'label_brand':'BOBCAT','brand_logo_url':'','company_logo_url':''})

    def test_detail_keeps_source_brand_and_does_not_change_database(self):
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        reception.init_reception_schema(db)
        init_traceability_schema(db)
        db.execute('CREATE TABLE order_importation_refs(bl_awb TEXT,sap_ov TEXT,transport_type TEXT)')
        sid = db.execute("INSERT INTO reception_shipments(bl_awb,app_status,created_at,updated_at) VALUES ('QA-BRAND','CERRADO','2026-10-13','2026-10-13')").lastrowid
        db.execute("INSERT INTO reception_lines(shipment_id,np_code,brand) VALUES (?,'QA-NP','BOBCAT INDIA')", (sid,))
        before = list(db.iterdump())
        detail = reception.reception_detail(db, sid, 'ADMINISTRADOR', 'qa')
        self.assertEqual(detail['lines'][0]['brand'], 'BOBCAT INDIA')
        self.assertEqual(detail['lines'][0]['label_brand'], 'BOBCAT')
        self.assertEqual(list(db.iterdump()), before)
        db.close()

    def test_logo_endpoint_permissions_type_etag_and_stale_version(self):
        from backend import app, wsgi
        (self.logo_dir / 'bobcat.png').write_bytes(PNG)
        digest = brands.logo_asset('BOBCAT', self.root / 'qa.sqlite')[2]
        with patch.dict(os.environ, {'TRITON_AUTH_MODE':'demo'}), patch.object(app, 'DB_PATH', self.root / 'qa.sqlite'):
            def request(query, extra=None):
                status, headers = [], {}
                environ = {'REQUEST_METHOD':'GET','PATH_INFO':'/api/reception-brand-logo','QUERY_STRING':query,
                           'wsgi.input':BytesIO(), 'CONTENT_LENGTH':'0', 'SERVER_NAME':'localhost','SERVER_PORT':'80',
                           'wsgi.url_scheme':'http', **(extra or {})}
                def start(value, fields, *args):
                    status.append(int(value.split()[0])); headers.update(fields)
                body = b''.join(wsgi.application(environ, start))
                return status[0], headers, body
            status, headers, body = request('brand=BOBCAT&v=' + digest)
            self.assertEqual(status, 200); self.assertEqual(body, PNG)
            self.assertEqual(headers['Content-Type'], 'image/png')
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(request('brand=BOBCAT&v=' + digest, {'HTTP_IF_NONE_MATCH':'"' + digest + '"'})[0], 304)
            self.assertEqual(request('brand=BOBCAT&v=old')[0], 410)
            self.assertEqual(request('brand=../bobcat')[0], 404)
            self.assertEqual(request('brand=BOBCAT', {'HTTP_X_ROLE':'PICKER','HTTP_X_USER':'qa'})[0], 403)


@unittest.skipUnless(shutil.which('node'), 'Node required')
class ReceptionLabelUiTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
const assert=require('assert/strict');global.window={};
global.esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
global.emEntryCard=s=>s;global.countLocationValue=l=>l.final_location||'';
require('./frontend/static/reception-labels.js');const labels=window.WmsReceptionLabels;
"""
        result = subprocess.run(['node','-e',setup + scenario], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reference_display_removes_only_repeated_source_ids_not_legitimate_sku_lines(self):
        self.run_js("""
const lines=[{id:1,np_code:'NP',ov_number:'OV1'},{id:1,np_code:'NP',ov_number:'OV1'},
 {id:2,np_code:'NP',ov_number:'OV2'},{id:3,np_code:'NP',ov_number:'OV1'}];
const ref={linked_lines:lines};assert.deepEqual(labels.referenceLines(ref).map(l=>l.id),[1,2,3]);
assert.equal(ref.linked_lines.length,4);
const view=emEntryCard({accounting_refs:[ref]});assert.equal(view.accounting_refs[0].linked_lines.length,3);
assert.equal(labels.referenceLines({linked_lines:[{np_code:'NP'},{np_code:'NP'}]}).length,2);
""")

    def test_data_matrix_exact_np_local_engine_and_fail_closed(self):
        self.run_js("""
assert.throws(()=>labels.dataMatrix('ICM/2022-273.a'),/Data Matrix/);
const engine=require('./frontend/static/bwip-js-min.js');let options;
window.bwipjs={toSVG:value=>{options=value;return engine.toSVG(value);}};
const svg=labels.dataMatrix('ICM/2022-273.a');
assert.equal(options.bcid,'datamatrix');assert.equal(options.text,'ICM/2022-273.a');
assert.equal(options.format,'square');assert(svg.includes('class="barcode datamatrix"'));
assert.throws(()=>labels.dataMatrix('X'.repeat(1000)),/tamaño legible/);
""")

    def test_stickers_keep_ov_brand_destination_and_current_attention_boundaries(self):
        self.run_js("""
const line={np_code:'NP001',ov_number:'OV001',customer_name:'Cliente',final_location:'BIN1',brand:'BOBCAT EUROPA',attention_verified_qty:1};
const list=[line,{...line,brand:'BOBCAT INDIA'},{...line,ov_number:'OV002'},
 {...line,brand:'CROWN INDIA'},{...line,final_location:''},{...line,attention_verified_qty:0,received_qty:20}];
const result=labels.items({lines:list});assert.equal(result.length,4);assert.equal(result[0].brand,'BOBCAT');
assert.equal(labels.brandName('BOBCAT CROWN'),'BOBCAT CROWN');
assert.equal(list[0].brand,'BOBCAT EUROPA');
assert.equal(labels.items({lines:[{...line,brand_logo_url:'javascript:bad()'}]})[0].logo,'');
""")
