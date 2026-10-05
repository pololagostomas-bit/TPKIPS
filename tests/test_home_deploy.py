import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "infrastructure/deployment/deploy-home.py"
spec = importlib.util.spec_from_file_location("deploy_home", path)
deployer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)


class HomeDeployTest(unittest.TestCase):
    def setUp(self):
        self.pr = {"state": "closed", "merged_at": "2026-10-05", "merge_commit_sha": "a" * 40,
                   "base": {"ref": "main", "repo": {"full_name": "owner/wms"}},
                   "merged_by": {"login": "owner"}}

    def test_only_owner_merged_pr_for_exact_head_and_base(self):
        self.assertTrue(deployer.approved_merge(self.pr, "owner/wms", "main", "a" * 40))
        mutations = [
            {"state": "open"}, {"merged_at": None}, {"merge_commit_sha": "b" * 40},
            {"merged_by": {"login": "someone-else"}},
            {"base": {"ref": "feature", "repo": {"full_name": "owner/wms"}}},
            {"base": {"ref": "main", "repo": {"full_name": "other/wms"}}},
        ]
        for mutation in mutations:
            changed = copy.deepcopy(self.pr)
            changed.update(mutation)
            self.assertFalse(deployer.approved_merge(changed, "owner/wms", "main", "a" * 40))

    def test_direct_push_never_runs_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "state.json").write_text(json.dumps({"sha": "b" * 40}))
            args = SimpleNamespace(state_dir=state, repository="owner/wms", base="main")
            with patch.object(deployer, "github", side_effect=[{"sha": "a" * 40}, []]), patch.object(deployer, "run") as run:
                self.assertTrue(deployer.deploy(args).startswith("ignored"))
                run.assert_not_called()

    def test_no_redeployment_or_retry_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            args = SimpleNamespace(state_dir=state, repository="owner/wms", base="main")
            for content, expected in (({"sha": "a" * 40}, "unchanged"),
                                      ({"sha": "b" * 40, "blocked_sha": "c" * 40}, "blocked")):
                (state / "state.json").write_text(json.dumps(content))
                with patch.object(deployer, "github", return_value={"sha": "a" * 40}), patch.object(deployer, "run") as run:
                    self.assertTrue(deployer.deploy(args).startswith(expected))
                    run.assert_not_called()

    def execute_approved(self, directory, fail_health=False):
        state = Path(directory)
        (state / "state.json").write_text(json.dumps({"sha": "b" * 40}))
        args = SimpleNamespace(state_dir=state, repository="owner/wms", base="main",
                               env_file=state / ".env", compose_file=state / "compose.yml")
        calls = []

        def command(*parts, **kwargs):
            calls.append(parts)
            if fail_health and "--wait-timeout" in parts:
                raise subprocess.CalledProcessError(1, parts)

        with patch.object(deployer, "github", side_effect=[{"sha": "a" * 40}, [{"number": 1}], self.pr]), patch.object(deployer, "run", side_effect=command):
            if fail_health:
                with self.assertRaises(RuntimeError):
                    deployer.deploy(args)
            else:
                self.assertEqual(deployer.deploy(args), "deployed: " + "a" * 40)
        return calls, json.loads((state / "state.json").read_text())

    def test_build_and_backup_before_recreate(self):
        with tempfile.TemporaryDirectory() as directory:
            calls, state = self.execute_approved(directory)
            build = next(i for i, args in enumerate(calls) if "build" in args)
            backup = next(i for i, args in enumerate(calls) if "exec" in args)
            recreate = next(i for i, args in enumerate(calls) if "up" in args)
            self.assertLess(build, backup)
            self.assertLess(backup, recreate)
            self.assertEqual(state, {"sha": "a" * 40, "image_tag": "a" * 12})

    def test_failed_health_stops_services_and_preserves_previous_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            calls, state = self.execute_approved(directory, fail_health=True)
            self.assertEqual(calls[-1][-3:], ("stop", "app", "backup"))
            self.assertEqual(state["sha"], "b" * 40)
            self.assertEqual(state["blocked_sha"], "a" * 40)
            self.assertFalse(any("down" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
