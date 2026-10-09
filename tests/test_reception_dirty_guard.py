"""Regression for server-loaded selects being mistaken for unsaved edits."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class ReceptionDirtyGuardTests(unittest.TestCase):
    def check_guard(self, control, expected):
        template = (ROOT / "frontend/templates/reception.html").read_text(encoding="utf-8")
        start = template.index("    function receptionHasUnsavedFields(){")
        end = template.index("    window.confirmLeaveActiveReceptionWork=", start)
        code = """
const assert = require('node:assert/strict');
const control = CONTROL;
global.document = {querySelectorAll: () => [control]};
FUNCTION
assert.equal(receptionHasUnsavedFields(), EXPECTED);
""".replace("CONTROL", control).replace("FUNCTION", template[start:end]).replace("EXPECTED", str(expected).lower())
        result = subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_untouched_first_option_is_clean_without_selected_attribute(self):
        self.check_guard("{tagName:'SELECT',selectedIndex:0,options:[{selected:true,defaultSelected:false},{selected:false,defaultSelected:false}]}", False)

    def test_explicit_saved_option_is_clean(self):
        self.check_guard("{tagName:'SELECT',selectedIndex:1,options:[{selected:false,defaultSelected:false},{selected:true,defaultSelected:true}]}", False)

    def test_user_selection_differs_from_implicit_default(self):
        self.check_guard("{tagName:'SELECT',selectedIndex:1,options:[{selected:false,defaultSelected:false},{selected:true,defaultSelected:false}]}", True)

    def test_user_selection_differs_from_explicit_saved_value(self):
        self.check_guard("{tagName:'SELECT',selectedIndex:0,options:[{selected:true,defaultSelected:false},{selected:false,defaultSelected:true}]}", True)

    def test_disabled_changes_are_not_editable_work(self):
        self.check_guard("{tagName:'SELECT',disabled:true,selectedIndex:1,options:[{selected:false,defaultSelected:true},{selected:true,defaultSelected:false}]}", False)

    def test_untouched_multiple_selection_is_clean(self):
        self.check_guard("{tagName:'SELECT',multiple:true,options:[{selected:true,defaultSelected:true},{selected:false,defaultSelected:false}]}", False)

    def test_changed_multiple_selection_is_dirty(self):
        self.check_guard("{tagName:'SELECT',multiple:true,options:[{selected:true,defaultSelected:true},{selected:true,defaultSelected:false}]}", True)

    def test_changed_text_field_still_protects_work(self):
        self.check_guard("{tagName:'INPUT',type:'text',value:'new location',defaultValue:'saved location'}", True)

    def test_mobile_stage_navigation_is_not_business_work(self):
        self.check_guard("{tagName:'SELECT',dataset:{wmsNavigation:'true'},selectedIndex:1,options:[{selected:false,defaultSelected:true},{selected:true,defaultSelected:false}]}", False)
