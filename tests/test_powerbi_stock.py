"""Synthetic capability checks; no tenant, cache or Power BI calls."""
import json
import os
import unittest
from unittest.mock import patch

from backend.services import powerbi_stock


class PowerBIStockTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_configuration_never_claims_stock_or_refresh(self):
        with patch('requests.get', side_effect=AssertionError('No network')), \
                patch('backend.services.cloud_auth.access_token', side_effect=AssertionError('No token')):
            result = powerbi_stock.status()
        self.assertEqual(result['configuration'], dict.fromkeys(('report', 'workspace', 'dataset'), 'missing'))
        self.assertEqual(result['state'], 'disabled')
        self.assertFalse(result['stock_connected'])
        self.assertFalse(result['warehouse_filter_verified'])
        self.assertEqual(result['required_warehouse'], '01')
        self.assertEqual(result['refresh_schedule']['state'], 'unknown')
        self.assertIsNone(result['last_refresh_at'])

    def test_identifiers_are_declarations_not_access_and_are_not_exposed(self):
        ids = ['11111111-2222-4333-8444-555555555555',
               'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
               '12345678-1234-4234-8234-123456789abc']
        with patch.dict(os.environ, dict(zip(('POWERBI_STOCK_REPORT_ID',
                'POWERBI_STOCK_WORKSPACE_ID', 'POWERBI_STOCK_DATASET_ID'), ids))):
            result = powerbi_stock.status()
        self.assertEqual(set(result['configuration'].values()), {'declared'})
        self.assertEqual(result['api_access'], 'unverified')
        self.assertTrue(result['connector_implemented'])
        self.assertFalse(result['stock_connected'])
        for value in ids:
            self.assertNotIn(value, json.dumps(result))

    def test_embed_url_is_not_a_dataset_identifier(self):
        with patch.dict(os.environ, {'POWERBI_STOCK_DATASET_ID':
                'https://app.powerbi.com/reportEmbed?reportId=private'}):
            result = powerbi_stock.status()
        self.assertEqual(result['configuration']['dataset'], 'invalid')
        self.assertNotIn('private', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
