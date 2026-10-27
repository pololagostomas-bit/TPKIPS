"""Purchase report presentation on synthetic Excel and disposable history only."""
import csv
import io
import unittest
from datetime import datetime

from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904, to_excel

from backend.services import purchase_alerts as alerts
from tests import test_purchase_alerts as fixtures


def workbook(rows, header='FECHA DE SOLICITUD DE IMP / OV', epoch=None):
    book = Workbook()
    if epoch is not None:
        book.epoch = epoch
    book.active.title = 'BUYER'
    book.active.append(['ORDEN DE COMPRA', 'PEDIDO TRITON', 'OV', header])
    for row in rows:
        book.active.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


class PurchaseReportDateTests(unittest.TestCase):
    setUp = fixtures.PurchaseTests.setUp
    tearDown = fixtures.PurchaseTests.tearDown
    set_rows = fixtures.PurchaseTests.set_rows

    def make_snapshot(self, rows, **kwargs):
        snapshot = alerts.read_cases(workbook(rows, **kwargs), [])
        snapshot['checked_at'] = alerts._stamp(self.now)
        return snapshot

    def test_source_request_date_aliases_and_supported_excel_representations(self):
        day = datetime(2026, 9, 17)
        for header in ('FECHA DE SOLICITUD DE IMP / OV', 'Fecha solicitud de IMP OV',
                       'Fecha de solicitud IMP/OV', 'FECHA SOLICITUD IMP\nOV'):
            for value in (day, '17/09/2026', '2026-09-17', to_excel(day)):
                with self.subTest(header=header, value=value):
                    case = self.make_snapshot([['PRE1', 'IP1', 'OV1', value]], header=header)['cases'][0]
                    self.assertEqual(case['sources'][0].get('request_date'), '2026-09-17')

    def test_serial_uses_workbook_epoch(self):
        day = datetime(2026, 9, 17)
        case = self.make_snapshot([['PRE1', 'IP1', 'OV1', to_excel(day, CALENDAR_MAC_1904)]],
                             epoch=CALENDAR_MAC_1904)['cases'][0]
        self.assertEqual(case['sources'][0].get('request_date'), '2026-09-17')

    def test_missing_invalid_dates_do_not_hide_alerts_or_fall_back_to_eta(self):
        for value in (None, '', 'no disponible', '31/02/2026', '=TODAY()', '#VALUE!', True, 0):
            with self.subTest(value=value):
                snap = self.make_snapshot([['PRE1', 'IP1', 'OV1', value]])
                self.assertEqual(len(snap['cases']), 1)
                self.assertIsNone(snap['cases'][0]['sources'][0].get('request_date'))
                self.assertIn('Sin fecha', alerts.render(alerts.settings(), snap, set())['html'])
        snap = self.make_snapshot([['PRE1', 'IP1', 'OV1', datetime(2026, 9, 17)]], header='FECHA TRITON ESTIMADA')
        self.assertIn('Sin fecha', alerts.render(alerts.settings(), snap, set())['html'])

    def test_grouped_sources_preserve_all_dates_in_mail_and_private_history(self):
        self.snapshot = self.make_snapshot([
            ['PRE1', 'IP1', 'OV1', '17/10/2026'],
            ['PRE1', 'IP1', 'OV1', '18/10/2026'],
            ['PRE1', 'IP1', 'OV1', None]])
        result = alerts.run(force=True, now=self.now)
        item = alerts.case_history(now=self.now)['items'][0]
        self.assertEqual(item.get('request_date_display'), '17/10/2026; 18/10/2026; Sin fecha')
        self.assertIn('17/10/2026; 18/10/2026', result['preview']['html'])
        self.assertIn('Sin fecha', result['preview']['html'])
        self.assertEqual(len(item['sources']), 3)
        self.post_mock.assert_not_called()

    def test_date_edits_do_not_reset_identity_or_clock_or_create_mail_case(self):
        self.snapshot = self.make_snapshot([['PRE1', 'IP1', 'OV1', '17/09/2026']])
        old_key = self.snapshot['cases'][0]['key']
        alerts.run(force=True, now=self.now)
        first = alerts.case_history(now=self.now)['items'][0]
        self.snapshot = self.make_snapshot([['PRE1', 'IP1', 'OV1', '18/09/2026']])
        alerts.run(force=True, now=self.now + 7200)
        last = alerts.case_history(now=self.now + 7200)['items'][0]
        self.assertEqual(self.snapshot['cases'][0]['key'], old_key)
        self.assertEqual((last['id'], last['first_seen_at']), (first['id'], first['first_seen_at']))
        self.assertEqual(last['elapsed_hours'], 2)
        self.assertEqual(last.get('request_date_display'), '18/09/2026')

    def test_history_merge_of_oc_variants_preserves_request_dates(self):
        self.snapshot = self.make_snapshot([['PRE1', 'IP1', 'OV1', '17/09/2026'],
                                      ['PRE2', 'IP1', 'OV1', '18/09/2026']])
        alerts.run(force=True, now=self.now)
        history = alerts.case_history(now=self.now)
        self.assertEqual(history['total'], 1)
        self.assertEqual(history['items'][0].get('request_date_display'), '17/09/2026; 18/09/2026')

    def test_each_report_kind_has_separate_severity_sections_and_dates(self):
        snap = self.make_snapshot([['PRE1', 'IP-ORDINARY', 'OV1', '17/10/2026'],
                              ['12345', 'IP-GRAVE', 'COT1', '18/10/2026']])
        new_keys = {case['key'] for case in snap['cases'] if case['severity'] == 'REGULARIZAR'}
        for kind in ('daily', 'initial', 'incremental'):
            with self.subTest(kind=kind):
                payload = alerts.render(alerts.settings(), snap, new_keys, kind)
                body = payload['html']
                self.assertIn('Graves: cotizacion con OC o pedido a fabrica', body)
                self.assertIn('Por regularizar: preliminar / OC con pedido a fabrica', body)
                self.assertLess(body.index('IP-GRAVE'), body.index('IP-ORDINARY'))
                self.assertEqual(body.count('Fecha de solicitud IMP/OV</th>'), 2)
                self.assertIn('18/10/2026', body)
                self.assertIn('17/10/2026', body)
                self.assertEqual(len(payload['case_keys']), 2)
                if kind == 'incremental':
                    self.assertIn('Casos adicionados', body)
                    self.assertIn('Demas pendientes', body)

    def test_legacy_snapshot_and_csv_render_missing_date_and_preserve_speech(self):
        alerts.run(force=True, now=self.now)
        result = alerts.run(force=True, now=self.now + 3600)
        self.assertIn('Sin fecha', result['preview']['html'])
        rows = list(csv.DictReader(io.StringIO(alerts.history_csv(now=self.now).decode('utf-8-sig'))))
        self.assertEqual(rows[0].get('Fecha de solicitud IMP/OV'), 'Sin fecha')
        self.assertEqual(alerts.settings()['body'], alerts.DEFAULTS['body'])
        self.post_mock.assert_not_called()

    def test_all_history_and_csv_are_gravity_first_even_for_resolved_grave(self):
        self.snapshot = self.make_snapshot([['12345', 'IP-GRAVE', 'COT1', '18/09/2026']])
        alerts.run(force=True, now=self.now)
        self.snapshot = self.make_snapshot([['PRE1', 'IP-ORDINARY', 'OV1', '17/09/2026']])
        alerts.run(force=True, now=self.now + 3600)
        rows = list(csv.DictReader(io.StringIO(alerts.history_csv(state='all', now=self.now).decode('utf-8-sig'))))
        self.assertEqual([row['Nivel'] for row in rows], ['GRAVE', 'REGULARIZAR'])
        self.assertEqual([row.get('Fecha de solicitud IMP/OV') for row in rows], ['18/09/2026', '17/09/2026'])


if __name__ == '__main__':
    unittest.main()
