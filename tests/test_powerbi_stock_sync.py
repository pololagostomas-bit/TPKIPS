"""Temporary stock DBs and synthetic completed refreshes only."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend.services import cloud_sync, powerbi_stock as stock, powerbi_stock_api as api
from tests.test_powerbi_stock_api import configuration,refresh_row


class PowerBIStockSyncTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        path=Path(self.folder.name);config=path/'bi.json';config.write_text(json.dumps(configuration()))
        self.env=patch.dict(os.environ,{'POWERBI_STOCK_ENABLED':'1','POWERBI_STOCK_CONFIG_PATH':str(config),'WMS_CLOUD_AUTO_SYNC':'0'})
        self.env.start();self.addCleanup(self.env.stop)
        @contextmanager
        def db():
            connection=sqlite3.connect(path/'qa.db');connection.row_factory=sqlite3.Row
            try:
                with connection:yield connection
            finally:connection.close()
        self.app=SimpleNamespace(db=db)
        with db() as conn:
            cloud_sync.init_schema(conn)
            conn.executescript('''CREATE TABLE inventory_stock(item_key TEXT,warehouse_key TEXT,item_code TEXT,warehouse TEXT,snapshot_qty REAL,snapshot_day TEXT,snapshot_at TEXT,source_file TEXT,default_location TEXT,is_current INTEGER,updated_at TEXT,description TEXT DEFAULT '',PRIMARY KEY(item_key,warehouse_key));
              CREATE TABLE data_imports(id INTEGER PRIMARY KEY,source_type TEXT,filename TEXT,file_hash TEXT,cutoff_at TEXT,loaded_at TEXT,username TEXT,summary TEXT,UNIQUE(source_type,cutoff_at,file_hash));
              CREATE TABLE stock_allocations(id INTEGER,quantity REAL);
              INSERT INTO stock_allocations VALUES(1,7);
              INSERT INTO inventory_stock VALUES('OTHER','2','OTHER','02',8,'2020-01-01','2020-01-01T00:00:00','old','KEEP',1,'old','');''')
        self.marker={'key':'qa-refresh','started_at':refresh_row()['startTime'],'completed_at':refresh_row()['endTime']}
        self.client=Mock();self.client.refresh.return_value=self.marker
        self.rows=[dict(warehouse='01',item_code='00123',description='QA part',location='BIN-A',quantity=2),
                   dict(warehouse='01',item_code='00123',description='QA part',location='BIN-B',quantity=8)]
        self.client.read_rows.return_value=self.rows
        self.factory=patch.object(stock,'Client',return_value=self.client);self.factory.start();self.addCleanup(self.factory.stop)

    def test_cut_default_alternatives_and_import_history_are_atomic_and_idempotent(self):
        result=stock.sync(self.app);self.assertEqual(result['state'],'updated')
        with self.app.db() as conn:
            row=conn.execute("SELECT * FROM inventory_stock WHERE item_key='00123'").fetchone()
            self.assertEqual((row['snapshot_qty'],row['default_location'],row['description']),(10,'BIN-B','QA part'))
            self.assertEqual(conn.execute("SELECT is_current FROM inventory_stock WHERE warehouse_key='2'").fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT quantity FROM stock_allocations').fetchone()[0],7)
            self.assertEqual(conn.execute('SELECT count(*) FROM powerbi_stock_locations').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT count(*) FROM data_imports').fetchone()[0],1)
        self.assertEqual(stock.sync(self.app)['state'],'unchanged');self.assertEqual(self.client.read_rows.call_count,1)
        self.assertTrue(stock.status(self.app)['stock_connected'])
        with self.app.db() as conn:
            row=conn.execute("SELECT rows_count FROM cloud_sync_history WHERE state='unchanged' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row[0],1)

    def test_bad_cut_or_api_failure_preserves_snapshot_and_safe_history(self):
        stock.sync(self.app);self.client.refresh.return_value={**self.marker,'key':'new'}
        self.client.read_rows.side_effect=api.StockError('partial')
        self.assertEqual(stock.sync(self.app)['state'],'error')
        with self.app.db() as conn:self.assertEqual(conn.execute("SELECT snapshot_qty FROM inventory_stock WHERE item_key='00123'").fetchone()[0],10)
        self.assertEqual(stock.status(self.app)['state'],'error')
        with patch.object(api.requests,'request',side_effect=AssertionError('Status must be local')):stock.status(self.app)

    def test_late_failure_rolls_back_entire_cut_and_does_not_claim_success(self):
        with self.app.db() as conn:
            conn.execute("CREATE TRIGGER fail_cut BEFORE INSERT ON data_imports BEGIN SELECT RAISE(ABORT,'PRIVATE'); END")
        self.assertEqual(stock.sync(self.app)['state'],'error')
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM inventory_stock WHERE warehouse_key='1'").fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM powerbi_stock_locations').fetchone()[0],0)
        self.assertNotIn('PRIVATE',json.dumps(stock.status(self.app)))

    def test_newer_manual_cut_wins_over_older_bi_refresh(self):
        cutoff=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        with self.app.db() as conn:conn.execute("INSERT INTO data_imports VALUES(1,'stock','manual','qa',?,?,'qa','{}')",(cutoff,cutoff))
        self.assertEqual(stock.sync(self.app)['state'],'blocked')
        self.assertFalse(stock.status(self.app)['stock_connected'])

    def test_manual_cut_replacing_active_bi_is_never_still_reported_as_connected(self):
        stock.sync(self.app)
        cutoff=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        with self.app.db() as conn:
            conn.execute("INSERT INTO data_imports(source_type,filename,file_hash,cutoff_at,loaded_at,username,summary) VALUES('stock','manual','qa',?,?,'qa','{}')",(cutoff,cutoff))
        self.assertFalse(stock.status(self.app)['stock_connected'])
        self.assertEqual(stock.status(self.app)['state'],'superseded')

    def test_manual_cut_arriving_during_network_read_is_not_overwritten(self):
        def downloaded(marker):
            cutoff=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            with self.app.db() as conn:
                conn.execute("INSERT INTO data_imports VALUES(1,'stock','manual','qa',?,?,'qa','{}')",(cutoff,cutoff))
            return self.rows
        self.client.read_rows.side_effect=downloaded
        self.assertEqual(stock.sync(self.app)['error_code'],'newer_cut')
        with self.app.db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM data_imports').fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM inventory_stock WHERE warehouse_key='1'").fetchone()[0],0)

    def test_throttling_waits_until_retry_after_without_extra_api_calls(self):
        self.client.refresh.side_effect=api.StockError('throttled',900)
        self.assertEqual(stock.sync(self.app)['error_code'],'throttled')
        self.assertEqual(stock.sync(self.app)['state'],'throttled')
        self.assertEqual(self.client.refresh.call_count,1)
        self.assertFalse(stock.status(self.app)['stock_connected'])

    def test_powerbi_opt_in_excludes_only_automatic_excel_stock(self):
        sources=[{'source_type':kind} for kind in ('stock','importation','accounting')]
        with patch.object(cloud_sync.cloud_excel,'configured_sources',return_value=sources):
            self.assertEqual([source['source_type'] for source in cloud_sync._excel_sources()],['importation','accounting'])
            with patch.dict(os.environ,{'POWERBI_STOCK_ENABLED':'0'}):
                self.assertEqual(cloud_sync._excel_sources(),sources)
        with patch.object(cloud_sync.cloud_excel,'configured_sources',return_value=[sources[0]]),patch.object(cloud_sync.cloud_auth,'status',side_effect=AssertionError('No Excel auth request')):
            cloud_sync._worker_cycle(self.app)
        self.assertEqual(cloud_sync._runtime(self.app)['worker_state'],'waiting')

    def test_distinct_bi_codes_share_no_stock_or_bins_despite_legacy_key_collision(self):
        from backend.services import powerbi_stock_store as store
        self.client.read_rows.return_value=[self.rows[0],dict(self.rows[1],item_code='00-123')]
        self.assertEqual(stock.sync(self.app)['state'],'updated')
        with self.app.db() as conn:
            first=store.snapshot(conn,'00123','1');second=store.snapshot(conn,'00-123','1')
            self.assertEqual((first['snapshot_qty'],first['default_location']),(2,'BIN-A'))
            self.assertEqual((second['snapshot_qty'],second['default_location']),(8,'BIN-B'))
            self.assertEqual(store.snapshot(conn,'0-0123','1')['snapshot_qty'],0)
            self.assertEqual(conn.execute("SELECT snapshot_qty FROM inventory_stock WHERE item_key='00123'").fetchone()[0],0)

    def test_scheduler_polls_bi_every300s_without_changing_excel_interval(self):
        with patch.dict(os.environ,{'WMS_CLOUD_AUTO_SYNC':'1','WMS_CLOUD_INTERVAL_SECONDS':'900'}), \
             patch.object(cloud_sync,'_worker_cycle') as excel,patch.object(stock,'sync') as bi:
            schedule={}
            stock._worker_tick(self.app,schedule,now=0)
            stock._worker_tick(self.app,schedule,now=299)
            stock._worker_tick(self.app,schedule,now=300)
            stock._worker_tick(self.app,schedule,now=600)
            self.assertEqual(bi.call_count,3);excel.assert_not_called();self.assertEqual(cloud_sync.interval(),900)
        with patch.object(stock,'sync') as bi:
            stock._worker_tick(self.app,{},now=0);bi.assert_called_once()
        with patch.object(stock,'start_worker') as worker,patch.object(cloud_sync,'_worker_started',False),patch.object(cloud_sync,'_recover_runtime'):
            cloud_sync.start_worker(self.app);worker.assert_called_once_with(self.app)
