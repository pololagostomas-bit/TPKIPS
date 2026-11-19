from io import BytesIO
from pathlib import Path
import tempfile
import shutil
import unittest

from openpyxl import Workbook
from backend import app
from backend.services import reception_rotation as rotation
from backend.services.reception import create_reception, reception_detail


def workbook(rows,headers=('NP','Descripción','Clasificación')):
    book=Workbook();sheet=book.active;sheet.append(headers)
    for row in rows:sheet.append(row)
    buffer=BytesIO();book.save(buffer);book.close();return buffer.getvalue()


class ReceptionRotationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=app.DB_PATH
        app.DB_PATH=Path(self.folder.name)/'rotation.sqlite3';app.init_db()

    def tearDown(self):
        app.DB_PATH=self.previous;self.folder.cleanup()

    def load(self,rows,hour=9):
        return app.import_daily_excel(workbook(rows),'classification.xlsx','rotation',f'2026-11-18T{hour:02d}:00:00','admin','ADMINISTRADOR')

    def test_exact_codes_are_distinct_and_unchanged_by_description(self):
        self.load([(' 00123 ','Descripción antigua','A'),('123','Otra','B'),('AB-01','Uno','C'),('AB01','Dos','D')])
        with app.db() as db:
            shipment=create_reception(db,{'bl_awb':'QA-ROTATION','supplier':'QA','current_assistant':'qa.receiver'},'admin','ADMINISTRADOR')
            for code in ('00123','123','AB-01','AB01','ab-01','UNLISTED'):
                db.execute('INSERT INTO reception_lines(shipment_id,np_code,description,expected_qty) VALUES(?,?,?,2)',(shipment['id'],code,'Descripción operativa'))
            payload=reception_detail(db,shipment['id'])
            self.assertEqual([line['rotation_classification'] for line in payload['lines']],['A','B','C','D','C',''])
            self.assertTrue(all(line['description']=='Descripción operativa' for line in payload['lines']))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM inventory_stock').fetchone()[0],0)

    def test_update_preserves_unlisted_codes_and_survives_stock_reload(self):
        self.load([('QA-01','Uno','A'),('QA-02','Dos','B')])
        self.load([('QA-01','Descripción nueva','C')],hour=10)
        content=workbook([('QA-01',9,'1')],headers=('Número de artículo','En stock','Almacén'))
        app.import_daily_excel(content,'stock.xlsx','stock','2026-11-18T11:00:00','admin','ADMINISTRADOR')
        with app.db() as db:
            lines=[{'np_code':'QA-01'},{'np_code':'QA-02'}];rotation.annotate(db,lines)
            self.assertEqual([line['rotation_classification'] for line in lines],['C','B'])

    def test_conflict_empty_and_bad_headers_are_atomic(self):
        self.load([('QA-01','Uno','A')])
        for rows,headers in [([('QA-01','Uno','B'),('QA-01','Uno','C')],('NP','Descripción','Clasificación')),
                             ([],('NP','Descripción','Clasificación')),
                             ([('QA-01','Uno','B')],('Otra','Descripción','Clasificación')),
                             ([('QA-01','Uno','')],('NP','Descripción','Clasificación'))]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                app.import_daily_excel(workbook(rows,headers),'bad.xlsx','rotation','2026-11-18T10:00:00','admin','ADMINISTRADOR')
        with app.db() as db:
            lines=[{'np_code':'QA-01'}];rotation.annotate(db,lines);self.assertEqual(lines[0]['rotation_classification'],'A')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM data_imports WHERE source_type='rotation'").fetchone()[0],1)

    def test_repeated_rows_hash_old_cut_and_role(self):
        content=workbook([('QA-01','Uno','A'),('QA-01','Uno','A')])
        result=app.import_daily_excel(content,'rotation.xlsx','rotation','2026-11-18T09:00:00','admin','ADMINISTRADOR')
        self.assertEqual(result['classifications'],1);self.assertEqual(result['repeated_rows'],1)
        with app.db() as db:
            status=next(source for source in app.data_status(db)['sources'] if source['source_type']=='rotation')
            self.assertEqual(status['status'],'VIGENTE')
        self.assertTrue(app.import_daily_excel(content,'rotation.xlsx','rotation','2026-11-18T09:00:00','admin','ADMINISTRADOR')['duplicate'])
        with self.assertRaises(ValueError):self.load([('QA-01','Uno','B')],hour=8)
        with self.assertRaises(PermissionError):app.import_daily_excel(content,'rotation.xlsx','rotation','2026-11-18T10:00:00','worker','AUXILIAR_RECEPCION')

    def test_numeric_codes_displayed_with_zero_padding_and_header_order(self):
        book=Workbook();sheet=book.active;sheet.append(['Clasificación de rotación','Descripción del artículo','Código de artículo'])
        sheet.append(['A','Numérico',123]);sheet['C2'].number_format='00000'
        sheet.append(['B','Texto','123'])
        stream=BytesIO();book.save(stream);book.close()
        self.assertEqual(set(rotation.parse_workbook(stream.getvalue())[0]),{'00123','123'})

    def test_catalog_survives_schema_reinitialization_and_large_lookup_is_bounded(self):
        self.load([(f'QA-{i:04d}','Referencia','A') for i in range(1001)])
        app.init_db()
        with app.db() as db:
            lines=[{'np_code':f'QA-{i:04d}'} for i in range(1001)]+[{'np_code':'MISSING'}]
            rotation.annotate(db,lines)
            self.assertTrue(all(line['rotation_classification']=='A' for line in lines[:-1]))
            self.assertEqual(lines[-1]['rotation_classification'],'')

    def test_formula_missing_cache_and_ambiguous_sheets_preserve_previous_catalog(self):
        self.load([('QA-01','Referencia','A')])
        with self.assertRaises(ValueError):self.load([('QA-01','Referencia','=1+1')],hour=10)
        book=Workbook()
        for sheet in (book.active,book.create_sheet()):
            sheet.append(['NP','Descripción','Clasificación']);sheet.append(['QA-01','Referencia','B'])
        stream=BytesIO();book.save(stream);book.close()
        with self.assertRaises(ValueError):app.import_daily_excel(stream.getvalue(),'ambiguous.xlsx','rotation','2026-11-18T10:00:00','admin','ADMINISTRADOR')
        with app.db() as db:
            lines=[{'np_code':'QA-01'}];rotation.annotate(db,lines);self.assertEqual(lines[0]['rotation_classification'],'A')


@unittest.skipUnless(shutil.which('node'),'Node required')
class RotationLabelTests(unittest.TestCase):
    def run_js(self,script):
        from tests import test_reception_stock_labels as fixture
        fixture.StockLabelTests().run_js(script)

    def test_classification_prints_without_changing_matrix_quantity_or_label_scope(self):
        self.run_js(r'''
const shipment={lines:[{...first,rotation_classification:'A <alta>'},{...first,id:2,rotation_classification:'A <alta>'}]};
const before=JSON.stringify(shipment),items=labels.items(shipment);
assert.equal(items.length,1);assert.equal(items[0].quantity,4);
assert.equal(items[0].rotation_classification,'A <alta>');
const html=labels.documentHtml({},items);
assert(html.includes('Clasificación de rotación'));assert(html.includes('A &lt;alta&gt;'));
assert(!html.includes('A <alta>'));assert(html.includes('Data Matrix QA-NP'));
assert.equal(JSON.stringify(shipment),before);
const stock=labels.inventoryDocumentHtml({item_code:'QA-NP',rotation_classification:'PRIVATE-CLASS'});
assert(!stock.includes('PRIVATE-CLASS'));assert(!stock.includes('Clasificación de rotación'));
''')

    def test_unmapped_reception_is_not_given_an_invented_class(self):
        self.run_js(r'''
const html=labels.documentHtml({},labels.items({lines:[first]}));
assert(html.includes('Sin clasificación'));assert(!html.includes('rotation-value">A<'));
''')


if __name__=='__main__':unittest.main()
