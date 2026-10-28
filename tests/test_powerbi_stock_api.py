"""Synthetic BI API boundaries. No tenant, credentials or live requests."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.services import powerbi_stock_api as api


def configuration():
    return {'dataset_id':'11111111-2222-4333-8444-555555555555','table':'QA_STOCK',
        'storage_mode':'Import','quantity_kind':'physical_by_bin',
        'columns':dict(zip(('warehouse','item_code','description','location','quantity'),
                           ('Warehouse','SKU','Description','Bin','Quantity')))}


def refresh_row():
    end=datetime.now(timezone.utc)-timedelta(hours=2)
    return {'requestId':'qa-refresh','status':'Completed','startTime':(end-timedelta(minutes=4)).isoformat(),'endTime':end.isoformat()}


def response(data,status=200):
    value=Mock(status_code=status,headers={'Content-Type':'application/json'})
    value.iter_content.return_value=[json.dumps(data).encode()]
    return value


def result(rows):return {'results':[{'tables':[{'rows':rows}]}]}


class PowerBIStockAPITests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'bi.json';self.path.write_text(json.dumps(configuration()))
        self.env=patch.dict(os.environ,{'POWERBI_STOCK_ENABLED':'1','POWERBI_STOCK_CONFIG_PATH':str(self.path)})
        self.env.start();self.addCleanup(self.env.stop)
        self.token=patch.object(api,'_access_token',return_value='synthetic-bearer');self.token.start();self.addCleanup(self.token.stop)

    def test_private_mapping_is_validated_and_fingerprinted(self):
        config=api.load_configuration();self.assertEqual(config['columns']['item_code'],'SKU')
        self.assertEqual(len(config['fingerprint']),64)
        for change in ({'dataset_id':'https://bad.invalid'}, {'storage_mode':'DirectQuery'},
                       {'quantity_kind':'warehouse_total'}, {'table':"x'); DELETE"}, {'columns':{}}):
            self.path.write_text(json.dumps({**configuration(),**change}))
            with self.subTest(change=change),self.assertRaises(api.StockError):api.load_configuration()

    def test_completed_refresh_count_full_rows_and_recheck(self):
        refresh=refresh_row();rows=[{'[warehouse]':'01','[item_code]':'00123','[description]':'QA',
                                  '[location]':'BIN-A','[quantity]':4}]
        with patch.object(api.requests,'request',side_effect=[response({'value':[refresh]}),
                response(result([{'[row_count]':1}])),response(result(rows)),response({'value':[refresh]})]) as request:
            client=api.Client(api.load_configuration());marker=client.refresh();data=client.read_rows(marker)
        self.assertEqual(data[0]['item_code'],'00123');self.assertEqual(data[0]['quantity'],4)
        self.assertEqual(request.call_count,4)
        query=request.call_args_list[1].kwargs['json']['queries'][0]['query']
        self.assertIn('DISTINCT',query);self.assertIn('"01"',query)
        self.assertTrue(all(call.kwargs['allow_redirects'] is False for call in request.call_args_list))

    def test_partial_or_nested_api200_errors_never_return_a_cut(self):
        refresh=refresh_row()
        for bad in ({'error':{'message':'PRIVATE-ERROR'}}, {'results':[{'error':{'code':'bad'}}]},
                    {'results':[{'tables':[{'error':{'code':'limit'}}]}]},result([])):
            with self.subTest(bad=bad),patch.object(api.requests,'request',side_effect=[response({'value':[refresh]}),
                    response(result([{'[row_count]':2}])),response(bad)]):
                client=api.Client(api.load_configuration());marker=client.refresh()
                with self.assertRaises(api.StockError) as caught:client.read_rows(marker)
                self.assertNotIn('PRIVATE-ERROR',str(caught.exception))

    def test_model_change_during_download_keeps_previous_cut(self):
        refresh=refresh_row();other={**refresh,'requestId':'qa-new'}
        rows=[{'[warehouse]':'01','[item_code]':'QA','[description]':'QA','[location]':'BIN','[quantity]':1}]
        with patch.object(api.requests,'request',side_effect=[response({'value':[refresh]}),
                response(result([{'[row_count]':1}])),response(result(rows)),response({'value':[other]})]):
            client=api.Client(api.load_configuration());marker=client.refresh()
            with self.assertRaises(api.StockError):client.read_rows(marker)

    def test_empty_oversized_unfinished_and_wrong_warehouse_are_rejected(self):
        for status in ('Unknown','Failed','Disabled'):
            with patch.object(api.requests,'request',return_value=response({'value':[{**refresh_row(),'status':status}]})):
                with self.assertRaises(api.StockError):api.Client(api.load_configuration()).refresh()
        for count in (0,api.MAX_ROWS+1):
            with patch.object(api.requests,'request',return_value=response(result([{'[row_count]':count}]))):
                with self.assertRaises(api.StockError):api.Client(api.load_configuration()).read_rows({'key':'x'})

    def test_bi_token_uses_selected_delegated_account_even_with_graph_secret(self):
        self.token.stop()
        client=Mock();client.get_accounts.return_value=[{'home_account_id':'chosen'}]
        client.acquire_token_silent.return_value={'access_token':'QA-BI'}
        with patch.dict(os.environ,{'GRAPH_CLIENT_SECRET':'synthetic-graph-secret'}), \
             patch.object(api.cloud_auth,'locked',side_effect=lambda:nullcontext()), \
             patch.object(api.cloud_auth,'client',return_value=(client,Mock())), \
             patch.object(api.cloud_auth,'read_state',return_value={'home_account_id':'chosen'}), \
             patch.object(api.cloud_auth,'save_cache'),patch.object(api.cloud_auth,'access_token',side_effect=AssertionError('No Graph fallback')):
            self.assertEqual(api._access_token(),'QA-BI')
            client.acquire_token_silent.assert_called_once_with([api.BI_SCOPE],account={'home_account_id':'chosen'})

    def test_wrong_warehouse_oversized_body_and_retry_after_are_safe(self):
        row={'[warehouse]':'02','[item_code]':'QA','[description]':'QA','[location]':'BIN','[quantity]':1}
        with patch.object(api.requests,'request',side_effect=[response(result([{'[row_count]':1}])),response(result([row]))]):
            with self.assertRaises(api.StockError):api.Client(api.load_configuration()).read_rows({'key':'qa'})
        with patch.object(api,'MAX_BYTES',2),patch.object(api.requests,'request',return_value=response({'value':[]})):
            with self.assertRaises(api.StockError):api.Client(api.load_configuration()).refresh()
        limited=response({},429);limited.headers['Retry-After']='900'
        with patch.object(api.requests,'request',return_value=limited):
            with self.assertRaises(api.StockError) as caught:api.Client(api.load_configuration()).refresh()
        self.assertEqual((caught.exception.code,caught.exception.retry_after),('throttled',900))
