"""Run the transfer interaction contract without browser/network dependencies."""
import shutil
import subprocess
import unittest
from pathlib import Path


class AssistantTransferUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for the JS interaction contract')
    def test_transfer_interaction(self):
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('assistant_transfer_ui.cjs'))],
                                capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
