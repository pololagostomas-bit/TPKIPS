import importlib.util
from pathlib import Path
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / "infrastructure/deployment/init-home.py"
spec = importlib.util.spec_from_file_location("init_home", path)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class HomeSetupTest(unittest.TestCase):
    def test_creates_unique_password_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory) / name for name in ("first.env", "second.env"))
            setup.initialize(first, "owner@example.com")
            setup.initialize(second, "owner@example.com")
            original = first.read_text()
            self.assertNotEqual(original, second.read_text())
            password = original.split("TRITON_BOOTSTRAP_ADMIN_PASSWORD=")[1].splitlines()[0]
            self.assertGreaterEqual(len(password), 40)
            with self.assertRaises(FileExistsError):
                setup.initialize(first, "owner@example.com")
            self.assertEqual(original, first.read_text())

    def test_rejects_wildcards_and_env_injection(self):
        for email in ("*@example.com", "a@example.com\nMALICIOUS=1", "missing"):
            with self.assertRaises(ValueError):
                setup.initialize("unused.env", email)
        with self.assertRaises(ValueError):
            setup.initialize("unused.env", "owner@example.com", username="a\nBAD=1")
        with self.assertRaises(ValueError):
            setup.initialize("unused.env", "owner@example.com", port=80)


if __name__ == "__main__":
    unittest.main()
