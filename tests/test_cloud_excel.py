import unittest
from unittest.mock import Mock, patch

from backend.services import cloud_excel


class CloudExcelTests(unittest.TestCase):
    @patch.dict('os.environ', {'WMS_CLOUD_DISPATCH_MODE':'manual',
        'GRAPH_SHARE_URL_DISPATCH':'https://contoso.sharepoint.com/ov.xlsx',
        'GRAPH_SHARE_URL_IMPORTATION':'https://contoso.sharepoint.com/importation.xlsx',
        'GRAPH_SHARE_URL_ACCOUNTING':'', 'GRAPH_SHARE_URL_STOCK':''})
    def test_manual_ov_is_excluded_even_if_a_cloud_url_exists(self):
        self.assertEqual([source['source_type'] for source in cloud_excel.configured_sources()], ['importation'])

    def test_share_url_encoding_uses_graph_share_id(self):
        encoded = cloud_excel._encode_share_url("https://contoso.sharepoint.com/:x:/r/share")
        self.assertTrue(encoded.startswith("u!"))
        self.assertNotIn("=", encoded)

    def test_powerbi_report_is_rejected_before_token_or_graph_request(self):
        for host in ['app.powerbi.com', 'api.powerbi.com', 'app.powerbi.cn', 'app.powerbigov.us']:
            with self.subTest(host=host), patch.object(cloud_excel, '_access_token') as token, \
                    patch.object(cloud_excel.requests, 'get') as get:
                with self.assertRaises(cloud_excel.CloudExcelError) as result:
                    cloud_excel.download_cloud_excels(sources=[{'source_type': 'stock',
                        'share_url': 'https://' + host + '/reportEmbed?reportId=PRIVATE-QA'}])
                self.assertEqual(result.exception.code, 'source_not_excel')
                self.assertNotIn('PRIVATE-QA', str(result.exception))
                token.assert_not_called()
                get.assert_not_called()

    def test_host_matching_does_not_reject_sharepoint_paths(self):
        self.assertFalse(cloud_excel.is_powerbi_url('https://example.sharepoint.com/powerbi.com.xlsx'))
        self.assertFalse(cloud_excel.is_powerbi_url('https://powerbi.com.example.test/file.xlsx'))

    @patch.dict("os.environ", {
        "GRAPH_SHARE_URL_DISPATCH": "https://example.test/dispatch",
        "GRAPH_SHARE_URL_STOCK": "",
        "GRAPH_SHARE_URL_IMPORTATION": "https://example.test/importation",
        "GRAPH_SHARE_URL_ACCOUNTING": "",
    }, clear=False)
    def test_configured_sources_keeps_operational_order(self):
        sources = cloud_excel.configured_sources()
        self.assertEqual([item["source_type"] for item in sources], ["dispatch", "importation"])

    @patch("backend.services.cloud_excel._access_token", return_value="token")
    @patch("backend.services.cloud_excel.requests.get")
    @patch.dict("os.environ", {
        "GRAPH_SHARE_URL_DISPATCH": "https://example.test/dispatch",
        "GRAPH_SHARE_URL_STOCK": "",
        "GRAPH_SHARE_URL_IMPORTATION": "",
        "GRAPH_SHARE_URL_ACCOUNTING": "",
    }, clear=False)
    def test_download_returns_excel_bytes(self, get, _token):
        item_response = Mock(status_code=200)
        item_response.json.return_value = {
            "id": "item-1",
            "name": "OV.xlsx",
            "parentReference": {"driveId": "drive-1"},
        }
        content_response = Mock(status_code=200, content=b"excel-bytes")
        get.side_effect = [item_response, content_response]

        result = cloud_excel.download_cloud_excels()

        self.assertEqual(result[0]["content"], b"excel-bytes")
        self.assertEqual(result[0]["source_type"], "dispatch")
        self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
