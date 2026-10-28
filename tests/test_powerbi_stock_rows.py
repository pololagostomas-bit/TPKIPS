"""Synthetic per-bin physical stock, independent of a tenant/model schema."""
import unittest

from backend.services import powerbi_stock_rows as stock


def row(sku='NP-001', location='01-A', quantity=3, warehouse='01'):
    return dict(item_code=sku, location=location, quantity=quantity, warehouse=warehouse)


class PowerBIStockRowsTests(unittest.TestCase):
    def test_greatest_positive_bin_wins_and_other_positive_bins_remain(self):
        result = stock.normalize_rows([row(location='01-Z', quantity=0),
            row(location='01-A', quantity=2), row(location='01-B', quantity=8)])
        self.assertEqual(result, [{'item_code': 'NP-001', 'item_key': 'NP001',
            'quantity': 10.0, 'default_location': '01-B',
            'locations': [{'location': '01-B', 'quantity': 8.0},
                          {'location': '01-A', 'quantity': 2.0}]}])

    def test_zero_and_negative_have_no_default_location(self):
        result = stock.normalize_rows([row(quantity=0), row(location='01-B', quantity=-2)])
        self.assertEqual(result[0]['quantity'], 0)
        self.assertEqual(result[0]['default_location'], '')
        self.assertEqual(result[0]['locations'], [])

    def test_warehouse_is_exact_not_prefix_and_blank_is_never_01(self):
        result = stock.normalize_rows([row(warehouse='1'), row(sku='OTHER', warehouse='10'),
            row(sku='OTHER2', warehouse='11'), row(sku='UNKNOWN', warehouse='')])
        self.assertEqual([item['item_code'] for item in result], ['NP-001'])

    def test_ties_and_source_order_have_stable_default(self):
        a, b = row(location='01-A'), row(location='01-B')
        self.assertEqual(stock.normalize_rows([a, b]), stock.normalize_rows([b, a]))
        self.assertEqual(stock.normalize_rows([b, a])[0]['default_location'], '01-A')

    def test_repeated_bin_never_doubles_quantity(self):
        self.assertEqual(stock.normalize_rows([row(), row()])[0]['quantity'], 3)

    def test_source_codes_are_authoritative_even_when_existing_key_collides(self):
        rows=[row(sku='NP-001',quantity=0),row(sku='NP001',quantity=7)]
        values=stock.normalize_rows(rows)
        self.assertEqual([(v['item_code'],v['quantity']) for v in values],[('NP-001',0),('NP001',7)])
        self.assertEqual(stock.normalize_rows(list(reversed(rows))),values)

    def test_two_nonzero_source_codes_are_never_summed_or_deduplicated(self):
        for quantity in (3,5,-2):
            with self.subTest(quantity=quantity):
                result=stock.normalize_rows([row(sku='NP-001'),row(sku='NP001',location='01-B',quantity=quantity)])
                self.assertEqual(len(result),2)
                self.assertEqual([item['quantity'] for item in result],[3,max(0,quantity)])

    def test_conflicting_repeated_bin_rejects_instead_of_guessing(self):
        with self.assertRaises(ValueError):
            stock.normalize_rows([row(), row(quantity=9)])

    def test_invalid_stock_cannot_silently_become_zero(self):
        for quantity in [None, '', 'unknown', float('nan'), float('inf'), True]:
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                stock.normalize_rows([row(quantity=quantity)])

    def test_no_location_can_have_stock_but_never_invents_a_bin(self):
        result = stock.normalize_rows([row(location='', quantity=5)])
        self.assertEqual(result[0]['quantity'], 5)
        self.assertEqual(result[0]['locations'], [])
        self.assertEqual(result[0]['default_location'], '')

    def test_empty_or_malformed_snapshot_is_not_an_authoritative_zero_cut(self):
        for rows in [[], [row(warehouse='02')], [row(sku='')], [{'quantity': 1}]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                stock.normalize_rows(rows)
