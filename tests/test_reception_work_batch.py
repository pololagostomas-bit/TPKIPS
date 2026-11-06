"""Work-list source checks scale by source batches, without stale identity data."""
from collections import Counter
import unittest

from backend.services import reception, reception_source_bl as source
from tests.test_reception_work import ReceptionWorkTests, shipment, complete_refs


class WorkBatchTests(unittest.TestCase):
    setUp = ReceptionWorkTests.setUp
    tearDown = ReceptionWorkTests.tearDown
    report = ReceptionWorkTests.report

    def case(self):
        records=[]
        for number in range(40):
            bl=f'QA-BATCH-{number}'
            sid=shipment(self.db,bl=bl,ips='IP-101')
            self.db.execute('''INSERT INTO reception_lines
                (shipment_id,source_key,source_sheet,np_code,ip_reference,oc_number,ov_number,expected_qty)
                VALUES (?,?,'QA-SHEET','QA-SHARED','IP-101','12345',?,1)''',
                (sid,f'QA-LINE-{number}',f'QA-OV-{number}'))
            complete_refs(self.db,sid,1)
            records.append({'source_sheet':'QA-SHEET','source_row':number+2,'np_code':'QA-SHARED',
                'guide':'QA-OTHER' if number in {3,7} else bl,'ip':'IP-101','oc':'12345','ov':f'QA-OV-{number}'})
        source.store(self.db,records,['QA-SHEET'],'qa.xlsx','2026-11-01')
        return [dict(row) for row in self.db.execute('SELECT * FROM reception_shipments ORDER BY id')]

    def test_work_report_does_not_reread_the_source_for_every_bl(self):
        self.case()
        statements=[]
        self.db.set_trace_callback(statements.append)
        before=self.db.total_changes
        report=self.report(view='arrival',username='worker.test',role='ASISTENTE_RECEPCION')
        self.db.set_trace_callback(None)
        self.assertEqual(report['total_bl'],40)
        self.assertEqual(self.db.total_changes,before)
        reads=Counter(table for table in ('reception_source_bl_rows','reception_source_bl_state','reception_import_legacy')
            for sql in statements if 'FROM '+table in sql)
        self.assertLessEqual(reads['reception_source_bl_rows'],2,reads)
        self.assertLessEqual(reads['reception_import_legacy'],2,reads)

    def test_bulk_ips_match_individual_guards_and_refresh_after_source_change(self):
        shipments=self.case()
        ids=[row[0] for row in self.db.execute('SELECT id FROM reception_lines ORDER BY id')]
        self.db.execute("INSERT INTO reception_import_legacy VALUES(?,?, '2026-11-01')",(ids[0],ids[1]))
        no_lines=shipment(self.db,bl='QA-NO-LINES',ips='IP-900')
        shipments=[dict(row) for row in self.db.execute('SELECT * FROM reception_shipments ORDER BY id')]
        for complete in (True,False):
            with self.subTest(complete=complete):
                if not complete:
                    self.db.execute('DELETE FROM reception_source_bl_state')
                expected={row['id']:reception._shipment_expected_ips(self.db,row['id'],row) for row in shipments}
                before=self.db.total_changes
                self.assertEqual(source.expected_ips_for_shipments(self.db,shipments),expected)
                self.assertEqual(self.db.total_changes,before)
                self.assertEqual(expected[no_lines],{'IP900'})
        source.store(self.db,[{'source_sheet':'QA-SHEET','source_row':2,'np_code':'QA-SHARED',
            'guide':'QA-BATCH-3','ip':'IP-101','oc':'12345','ov':'QA-OV-3'}],['QA-SHEET'],'new.xlsx','2026-11-02')
        expected={row['id']:reception._shipment_expected_ips(self.db,row['id'],row) for row in shipments}
        self.assertEqual(source.expected_ips_for_shipments(self.db,shipments),expected)
        self.assertEqual(expected[shipments[3]['id']],{'IP101'})
        self.assertEqual(source.expected_ips_for_shipments(self.db,[]),{})
