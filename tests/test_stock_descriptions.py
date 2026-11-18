"""Stock-only SAP cuts must supply descriptions to inventory and labels."""
import base64
from io import BytesIO
from pathlib import Path
import unittest
import uuid

from openpyxl import Workbook
import app
from backend.services.inventory_governance import inventory_label
from backend.services.inventory_stock_labels import parse_list


class StockDescriptionsTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB_PATH
        self.path = Path(__file__).parent / ('.stock-description-' + uuid.uuid4().hex + '.db')
        app.DB_PATH = self.path
        app.init_db()

    def tearDown(self):
        app.DB_PATH = self.original_db
        for suffix in ('', '-wal', '-shm'):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def workbook(self, description='Filtro SAP', heading='Descripción del artículo', quantity=7):
        book = Workbook(); sheet = book.active
        sheet.append(['Número de artículo', 'En stock', 'Ubicación'] + ([heading] if heading else []))
        sheet.append(['00123-A', quantity, '01-01-A-01-01'] + ([description] if heading else []))
        content = BytesIO(); book.save(content); book.close()
        return content.getvalue()

    def load(self, content, day=1, force=False):
        return app.import_daily_excel(content, 'stock.xlsx', 'stock', f'2026-10-{day:02d}T08:00:00',
                                      'qa.admin', 'ADMINISTRADOR', force=force)

    def label(self):
        with app.db() as connection:
            return inventory_label(connection, '00123-A', 'qa.admin', 'ADMINISTRADOR', db_path=self.path)

    def test_stock_headers_capture_description_without_dispatch(self):
        for heading in ('Descripción', 'Descripción del artículo', 'Descripción artículo/serv.'):
            with self.subTest(heading=heading):
                self.load(self.workbook(heading=heading), force=True)
                self.assertEqual(self.label()['description'], 'Filtro SAP')

    def test_new_stock_description_reaches_label_and_preserves_print_sequence(self):
        content = self.workbook()
        result = self.load(content)
        self.assertTrue(result['stock_updated'])
        label = self.label()
        self.assertEqual(label['description'], 'Filtro SAP')
        self.assertEqual(label['stock_qty'], 7)
        self.assertEqual(label['default_location'], '01-01-A-01-01')
        book = Workbook(); book.active.append(['NP', 'Cantidad'])
        for quantity in (200, 999): book.active.append(['00123-A', quantity])
        output = BytesIO(); book.save(output); book.close()
        parsed = parse_list({'filename': 'labels.xlsx', 'file_base64': base64.b64encode(output.getvalue()).decode()})
        self.assertEqual(parsed['codes'], ['00123-A', '00123-A'])
        with app.db() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM reception_receipts').fetchone()[0], 0)

    def test_newer_cut_updates_description_and_stock(self):
        self.load(self.workbook('Descripción anterior'))
        self.load(self.workbook('Descripción vigente', quantity=3), day=2)
        self.assertEqual(self.label()['description'], 'Descripción vigente')
        self.assertEqual(self.label()['stock_qty'], 3)

    def test_cut_without_description_or_with_blank_preserves_known_description(self):
        self.load(self.workbook())
        self.load(self.workbook(heading=None), day=2)
        self.assertEqual(self.label()['description'], 'Filtro SAP')
        self.load(self.workbook('   '), day=3)
        self.assertEqual(self.label()['description'], 'Filtro SAP')

    def test_existing_force_reload_can_restore_descriptions_without_multiplying_stock(self):
        content = self.workbook(); self.load(content)
        with app.db() as connection:
            connection.execute("UPDATE inventory_stock SET description='' WHERE item_code='00123-A'")
        result = self.load(content, force=True)
        self.assertTrue(result['forced'])
        self.assertEqual(self.label()['description'], 'Filtro SAP')
        self.assertEqual(self.label()['stock_qty'], 7)
