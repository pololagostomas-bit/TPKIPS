"""Build-time guards preserve variant code and reject partial/unknown bases."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'cloud_overlay_prepare', ROOT / 'infrastructure/cloud-overlay/prepare.py')
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.reception = (ROOT / 'backend/services/reception.py').read_text(encoding='utf-8')
        self.toolbar = (ROOT / 'frontend/static/daily-work.js').read_text(encoding='utf-8')

    def original_reception(self):
        source = self.reception
        for changes in overlay.RECEPTION_CHANGES.values():
            for old, new in changes:
                self.assertEqual(source.count(new), 1)
                source = source.replace(new, old)
        return source

    def original_toolbar(self):
        source = self.toolbar
        for old, new in overlay.TOOLBAR_CHANGES:
            self.assertEqual(source.count(new), 1)
            source = source.replace(new, old)
        return source

    def test_approved_reception_changes_only_documentary_guards(self):
        source = self.original_reception()
        self.assertEqual(overlay.patch_reception(source), self.reception)

    def test_already_installed_reception_is_unchanged(self):
        self.assertEqual(overlay.patch_reception(self.reception), self.reception)

    def test_overlay_removes_embedded_recipients_not_private_settings(self):
        source = self.original_reception().replace('"TRITON_CONTABILIDAD_EMAILS",\n                "",',
            '"TRITON_CONTABILIDAD_EMAILS",\n                "legacy@example.test",')
        self.assertIn('legacy@example.test', source)
        self.assertEqual(overlay.patch_reception(source), self.reception)
        self.assertIn('"TRITON_CONTABILIDAD_EMAILS"', self.reception)

    def test_toolbar_patch_and_repeat_keep_same_layout(self):
        self.assertEqual(overlay.patch_toolbar(self.original_toolbar()), self.toolbar)
        self.assertEqual(overlay.patch_toolbar(self.toolbar), self.toolbar)

    def test_legacy_top_button_is_replaced_by_daily_cuts_button(self):
        original = self.original_toolbar()
        old = original.replace('  toolbar?.append(stockButton, dataButton);',
            '  toolbar?.append(stockButton, dataButton);\n' + overlay.LEGACY_BUTTON.rstrip('\n'))
        old = old.replace('dataButton.hidden = !admin; stockButton.hidden = !admin;',
            'dataButton.hidden = !admin; stockButton.hidden = !admin; microsoftButton.hidden = !admin;')
        self.assertEqual(overlay.patch_toolbar(old), self.toolbar)

    def test_partial_patch_is_rejected(self):
        original = self.original_reception()
        old, new = overlay.RECEPTION_CHANGES['import_reception_workbook'][0]
        with self.assertRaisesRegex(ValueError, 'Partial cloud patch'):
            overlay.patch_reception(original.replace(old, new))

    def test_mobile_action_styles_apply_once(self):
        source = (ROOT / 'frontend/static/daily-work.css').read_text(encoding='utf-8')
        old, new = overlay.STYLE_CHANGE
        self.assertEqual(source.count(new), 1)
        self.assertEqual(overlay.replace_once(source.replace(new, old), [overlay.STYLE_CHANGE], 'css'), source)
        self.assertEqual(overlay.replace_once(source, [overlay.STYLE_CHANGE], 'css'), source)

    def test_purchase_link_preserves_workspace_and_is_idempotent(self):
        source = (ROOT / 'frontend/static/workspace-shell.js').read_text(encoding='utf-8')
        self.assertEqual(overlay.patch_workspace(source), source)
        original = source.replace("\n      action(tools,'Alertas de compras / OC','Pendientes y reportes de Importaciones',()=>location.assign('/purchase-alerts'));", '')
        self.assertEqual(overlay.patch_workspace(original), source)

    def test_unexpected_base_is_rejected(self):
        with self.assertRaises(ValueError):
            overlay.patch_reception(self.original_reception().replace(
                '_source_confirms_arrival(records)', '_changed_import_rule(records)'))
        with self.assertRaises(ValueError):
            overlay.patch_toolbar('const unrelatedVariant = true;')

    def test_no_file_written_if_other_validation_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reception = root / 'backend/services/reception.py'
            toolbar = root / 'frontend/static/daily-work.js'
            reception.parent.mkdir(parents=True)
            toolbar.parent.mkdir(parents=True)
            source = self.original_reception()
            reception.write_text(source, encoding='utf-8')
            toolbar.write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                overlay.main(root)
            self.assertEqual(reception.read_text(encoding='utf-8'), source)


if __name__ == '__main__':
    unittest.main()
