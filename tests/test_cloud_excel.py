import unittest
from unittest.mock import Mock, patch

from backend.services import cloud_excel


class CloudExcelTests(unittest.TestCase):
    def test_share_url_encoding_uses_graph_share_id(self):
        encoded = cloud_excel._encode_share_url("https://contoso.sharepoint.com/:x:/r/share")
        self.assertTrue(encoded.startswith("u!"))
        self.assertNotIn("=", encoded)

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
