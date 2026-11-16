import base64
from io import BytesIO
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from backend.services import inventory_stock_labels as bulk


class StockLabelListTests(unittest.TestCase):
    def test_paste_preserves_repeated_rows_and_input_order(self):
        result = bulk.parse_list({'text': '00123\n1R-1804\n1R1804\n00123\n1r-1804'})
        self.assertEqual(result['codes'], ['00123', '1R-1804', '1R1804', '00123', '1r-1804'])
        self.assertEqual(result['duplicates'], 2)

    def test_excel_ignores_quantity_and_preserves_text_codes(self):
        book = Workbook()
        book.active.append(['NP', 'Cantidad'])
        for row in [('00123', 200), ('NP-B', 2), ('00123', 500)]:
            book.active.append(row)
        content = BytesIO(); book.save(content); book.close()
        result = bulk.parse_list({'filename': 'stock.xlsx',
                                  'file_base64': base64.b64encode(content.getvalue()).decode()})
        self.assertEqual(result['codes'], ['00123', 'NP-B', '00123'])
        self.assertEqual(result['duplicates'], 1)

    def test_csv_header_and_unknown_extra_columns(self):
        data = 'Descripción;SKU;Cantidad\nFiltro;NP-B;900\nAnillo;NP-A;2\nFiltro;NP-B;7\n'
        result = bulk.parse_list({'filename': 'stock.csv',
                                  'file_base64': base64.b64encode(data.encode()).decode()})
        self.assertEqual(result['codes'], ['NP-B', 'NP-A', 'NP-B'])

    def test_rejects_formulas_empty_ambiguous_and_oversized_inputs(self):
        for payload in ({'text': '=SUM(A1:A2)'}, {'text': ''}, {'text': 'A' * 101},
                        {'text': 'NP', 'file_base64': 'YQ=='},
                        {'filename': 'x.exe', 'file_base64': 'YQ=='},
                        {'text': 'NP\tSKU\nA\tB'}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                bulk.parse_list(payload)

    def test_large_list_has_one_entry_per_code(self):
        result = bulk.parse_list({'text': '\n'.join('QA%05d' % n for n in range(5000))})
        self.assertEqual(len(result['codes']), 5000)

    def test_repeated_ascii_codes_are_counted_but_all_rows_are_preserved(self):
        result = bulk.parse_list({'text': 'Straße\nSTRASSE\nnp-a\nNP-A'})
        self.assertEqual(result['codes'], ['Straße', 'STRASSE', 'np-a', 'NP-A'])
        self.assertEqual(result['duplicates'], 1)

    def test_print_row_limit_includes_repeated_codes(self):
        with patch.object(bulk, 'MAX_CODES', 2), self.assertRaisesRegex(ValueError, 'filas'):
            bulk.parse_list({'text': 'NP-A\nNP-B\nNP-A'})

    def test_batch_reuses_exact_inventory_label_and_reports_missing(self):
        def label(connection, code, username, role, *, db_path):
            if code == 'MISSING': raise ValueError('No existe')
            return {'item_code': code, 'description': 'Pieza', 'stock_qty': 2}
        with patch.object(bulk, 'inventory_label', side_effect=label) as lookup:
            result = bulk.labels_batch(None, {'codes': ['NP-A', 'np-a', 'MISSING']}, 'qa', 'PICKER', db_path='qa.db')
        self.assertEqual([item['item_code'] for item in result['items']], ['NP-A'])
        self.assertEqual(result['missing'], ['MISSING'])
        self.assertEqual(lookup.call_count, 2)

    def test_batch_is_bounded_and_role_is_checked_before_lookup(self):
        for payload, role, error in [({'codes': ['A']}, 'INVALID', PermissionError),
                                     ({'codes': ['A'] * 101}, 'PICKER', ValueError),
                                     ({'codes': 'A'}, 'PICKER', ValueError)]:
            with self.subTest(role=role, payload=payload), self.assertRaises(error):
                bulk.labels_batch(None, payload, 'qa', role, db_path='qa.db')
