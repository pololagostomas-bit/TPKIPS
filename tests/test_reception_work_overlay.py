import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('work_overlay',
    ROOT / 'infrastructure/reception-work-overlay/prepare.py')
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)


class WorkOverlayTests(unittest.TestCase):
    def test_current_source_is_idempotent(self):
        for path, transform in [('backend/app.py', overlay.patch_app),
            ('backend/services/reception.py', overlay.patch_lifecycle),
            ('backend/services/truck_entry.py', overlay.patch_resolver),
            ('frontend/templates/reception.html', overlay.patch_template)]:
            source=(ROOT/path).read_text(encoding='utf-8')
            self.assertEqual(transform(source),source)

    def test_legacy_accounting_preserves_body_and_default(self):
        source='''def _accounting_status_for_shipment(connection, shipment_id, shipment=None, rows=None):
    received_ips = set()
    if received_ips:
        return "EXISTING VARIANT RULE"
    return "DEFAULT"
'''
        patched=overlay.patch_accounting(source)
        self.assertIn('include_unreceived_ips=False',patched)
        self.assertIn('return "EXISTING VARIANT RULE"',patched)
        self.assertEqual(overlay.patch_accounting(patched),patched)

    def test_unknown_or_partial_bases_abort(self):
        with self.assertRaises(ValueError):
            overlay.patch_accounting('def renamed():\n    pass\n')
        with self.assertRaises(ValueError):
            overlay.patch_template('<script src="/assets/reception-work.js"></script>')
        with self.assertRaises(ValueError):
            overlay.patch_template('<html></html>')

    def test_template_keeps_manual_markers_and_load_order(self):
        source='<main data-manual-mode="true"></main><script src="/assets/workspace-shell.js?v=existing"></script>'
        patched=overlay.patch_template(source)
        self.assertIn('data-manual-mode="true"',patched)
        self.assertLess(patched.index('reception-work.js'),patched.index('workspace-shell.js'))
        self.assertEqual(overlay.patch_template(patched),patched)

    def test_manual_truck_registration_and_optional_argument_are_preserved(self):
        source='''def resolve_entered_bl(connection, code, username, role, create_if_missing=True):
    matches = []
    if matches:
        return matches[0], False
    if not create_if_missing:
        raise ValueError("Legacy known-only")
    timestamp = reception.reception_now()
    return connection.execute("INSERT INTO reception_shipments").fetchone(), True

def register_truck_bl(connection, truck_guide, bl_code, packages, username, role):
    return resolve_entered_bl(connection, bl_code, username, role, create_if_missing=False)
'''
        patched=overlay.patch_resolver(source)
        self.assertIn('def register_truck_bl(',patched)
        self.assertIn('create_if_missing=False)',patched)
        self.assertNotIn('INSERT INTO reception_shipments',patched)
        self.assertEqual(overlay.patch_resolver(patched),patched)


if __name__=='__main__':
    unittest.main()
