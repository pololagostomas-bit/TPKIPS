"""One corrected documentary IP is not a second purchase reference."""
import json
from unittest.mock import patch
from openpyxl import Workbook
from backend.services import reception as r
from tests.test_reception_costing import CostingFixture


class AccountingIpRevisionTests(CostingFixture):
    def load(self, rows, blanks=0):
        book=Workbook();sheet=book.active;sheet.title=r.ACCOUNTING_SHEET_NAME
        sheet.append(['IP','AWB','FACTURA RESERVA','ENTRADA DE MERCANCIA','FECHA DE RECEPCION','FECHA DE EM','FECHA DE COSTEO'])
        for _ in range(blanks):sheet.append([])
        for ip,fr,em in rows:sheet.append([ip,'QA-COST',fr,em,'2026-10-01','2026-10-02','2026-10-03'])
        return r.import_reception_accounting_workbook(self.db,book,'qa-facturas.xlsx','qa','ADMINISTRADOR')

    def refs(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM reception_accounting_refs ORDER BY id')]

    def prepare_old(self):
        self.db.execute("UPDATE reception_lines SET ip_reference='IP260001-2'")
        self.load([('IP260001-2','QA-FR','QA-EM')])
        ref=self.refs()[0]
        self.db.execute("UPDATE reception_accounting_ems SET attention_id=?,username='qa.receiver'",(self.aid,))
        self.db.execute("UPDATE reception_lines SET ip_reference='IP260001-3'")
        return ref

    def test_unique_ip_revision_preserves_reference_manual_em_and_physical_work(self):
        old=self.prepare_old()
        em=dict(self.db.execute('SELECT * FROM reception_accounting_ems').fetchone())
        physical=[tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines')]
        result=self.load([('IP260001-3','QA-FR','QA-EM')],blanks=10)
        self.assertEqual(len(self.refs()),1)
        self.assertEqual(self.refs()[0]['id'],old['id'])
        self.assertEqual(self.refs()[0]['ip_reference'],'IP260001-3')
        current=dict(self.db.execute('SELECT * FROM reception_accounting_ems').fetchone())
        self.assertEqual(current,{**em,'ip_reference_key':'IP2600013'})
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM reception_attention_lines')],physical)
        self.assertEqual(result['ip_references_revised'],1)
        history=self.db.execute("SELECT * FROM reception_history WHERE event_type='REVISION IP FACTURAS'").fetchall()
        self.assertEqual(len(history),1)
        self.assertEqual(json.loads(history[0]['old_value'])['reference']['ip_reference'],'IP260001-2')
        self.load([('IP260001-3','QA-FR','QA-EM')],blanks=10)
        self.assertEqual(len(self.refs()),1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='REVISION IP FACTURAS'").fetchone()[0],1)

    def test_legacy_generated_duplicate_is_archived_without_losing_bound_em_or_costing(self):
        old=self.prepare_old()
        key=r._accounting_source_key(r.LEGACY_ACCOUNTING_SHEET_NAME,'QACOST','IP2600013',1)
        columns=[key for key in old if key!='id']
        new={**old,'source_key':key,'ip_reference':'IP260001-3'}
        cur=self.db.execute('INSERT INTO reception_accounting_refs ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',[new[k] for k in columns])
        duplicate=cur.lastrowid
        self.db.execute("INSERT INTO reception_accounting_ems(accounting_ref_id,ip_reference_key,em_number,username,created_at) VALUES(?,'IP2600013','QA-EM','importacion','2026-10-03')",(duplicate,))
        self.db.execute('UPDATE reception_attention_costing SET reference_ids=?',(json.dumps([duplicate]),))
        self.load([('IP260001-3','QA-FR','QA-EM')])
        self.assertEqual([row['id'] for row in self.refs()],[old['id']])
        self.assertEqual(json.loads(self.db.execute('SELECT reference_ids FROM reception_attention_costing').fetchone()[0]),[old['id']])
        archived=json.loads(self.db.execute("SELECT old_value FROM reception_history WHERE event_type='REVISION IP FACTURAS'").fetchone()[0])
        self.assertEqual(archived['duplicate']['id'],duplicate)
        self.assertEqual(self.db.execute('SELECT attention_id FROM reception_accounting_ems').fetchone()[0],self.aid)

    def test_both_ips_still_in_source_are_separate_regardless_of_order(self):
        self.prepare_old()
        self.load([('IP260001-3','QA-FR','QA-EM'),('IP260001-2','QA-FR','QA-EM')])
        self.assertEqual(len(self.refs()),2)
        self.load([('IP260001-2','QA-FR','QA-EM'),('IP260001-3','QA-FR','QA-EM')])
        self.assertEqual(len(self.refs()),2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM reception_history WHERE event_type='REVISION IP FACTURAS'").fetchone()[0],0)

    def test_different_or_missing_documents_are_not_identity(self):
        for fr,em in [('QA-OTHER','QA-EM'),('QA-FR','QA-OTHER'),('','QA-EM'),('QA-FR','')]:
            with self.subTest(fr=fr,em=em):
                self.db.execute('SAVEPOINT scenario')
                self.prepare_old()
                self.load([('IP260001-3',fr,em)])
                self.assertEqual(len(self.refs()),2)
                self.db.execute('ROLLBACK TO scenario');self.db.execute('RELEASE scenario')

    def test_two_stale_candidates_and_multiple_source_ips_are_not_merged(self):
        self.prepare_old()
        self.load([('IP260001-3','QA-FR','QA-EM'),('IP260001-4','QA-FR','QA-EM')])
        self.assertEqual(len(self.refs()),3)
        self.db.execute("UPDATE reception_lines SET ip_reference='IP260001-5'")
        self.load([('IP260001-5','QA-FR','QA-EM')])
        self.assertEqual(len(self.refs()),4)

    def test_duplicate_with_its_own_manual_work_is_not_deleted(self):
        self.prepare_old()
        self.load([('IP260001-2','QA-FR','QA-EM'),('IP260001-3','QA-FR','QA-EM')])
        self.db.execute("UPDATE reception_accounting_ems SET username='qa.other' WHERE ip_reference_key='IP2600013'")
        self.load([('IP260001-3','QA-FR','QA-EM')])
        self.assertEqual(len(self.refs()),2)

    def test_old_ip_still_in_importations_and_unknown_new_ip_are_not_revisions(self):
        for ip in ['IP260001-2','IP260009']:
            with self.subTest(ip=ip):
                self.db.execute('SAVEPOINT scenario')
                self.prepare_old()
                self.db.execute('UPDATE reception_lines SET ip_reference=?',(ip,))
                self.load([('IP260001-3','QA-FR','QA-EM')])
                self.assertEqual(len(self.refs()),2)
                self.db.execute('ROLLBACK TO scenario');self.db.execute('RELEASE scenario')

    def test_coverage_or_unrelated_manual_em_requires_review(self):
        for protection in ['coverage','other_em']:
            with self.subTest(protection=protection):
                self.db.execute('SAVEPOINT scenario')
                self.prepare_old()
                if protection=='coverage':
                    emid=self.db.execute('SELECT id FROM reception_accounting_ems').fetchone()[0]
                    self.db.execute("INSERT INTO reception_em_arrival_coverage VALUES(?,?,?,'QAFR','IP2600012','QA-EM',1,'qa','2026-10-03','QA coverage')",(emid,self.aid,self.aid))
                else:
                    self.db.execute("UPDATE reception_accounting_ems SET em_number='QA-OTHER'")
                self.load([('IP260001-3','QA-FR','QA-EM')])
                self.assertEqual(len(self.refs()),2)
                self.db.execute('ROLLBACK TO scenario');self.db.execute('RELEASE scenario')

    def test_previous_importer_revision_requests_exactly_one_replay(self):
        from backend.services import accounting_source_em as source
        self.prepare_old()
        self.db.execute('UPDATE reception_accounting_source_state SET revision=1')
        self.assertTrue(source.refresh_required(self.db))
        self.load([('IP260001-3','QA-FR','QA-EM')])
        self.assertFalse(source.refresh_required(self.db))

    def test_import_failure_rolls_back_revision_and_duplicate_retirement(self):
        self.prepare_old()
        self.db.commit()
        before=list(self.db.iterdump())
        with patch('backend.services.reception._write_history',side_effect=RuntimeError('QA failure')):
            with self.assertRaises(RuntimeError):
                with self.db:self.load([('IP260001-3','QA-FR','QA-EM')])
        self.assertEqual(list(self.db.iterdump()),before)
