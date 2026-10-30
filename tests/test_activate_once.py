"""Offline, non-root transaction tests for the one-time local MCP activator."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import activate_once as act
from updater import artifact_inbox_overlay as overlay

SOURCE = ("import stage_manager\n"
          "TOOLS = [\n" + overlay.TOOLS_OLD + "]\n"
          'ANNOTATIONS = ["fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start"]\n').encode()
COMMIT = "c" * 40


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "mcp"
        self.state = Path(self.tmp.name) / "state"
        self.root.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        self.original = self.root / "fieldwork_mcp.py"
        self.original.write_bytes(SOURCE)
        self.original.chmod(0o600)
        self.hash_patch = patch.object(act, "SOURCE_SHA", hashlib.sha256(SOURCE).hexdigest())
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)
        module_dir = Path(overlay.__file__).parent
        self.payloads = {name: (module_dir / name).read_bytes() for name in act.MODULES}
        self.retrieve_patch = patch.object(act, "retrieve", side_effect=lambda commit, name: self.payloads[name])
        self.retrieve_patch.start()
        self.addCleanup(self.retrieve_patch.stop)

    def test_exact_anchors_compile_without_install(self):
        result = act.compile_candidate(SOURCE, self.payloads["artifact_inbox_overlay.py"])
        self.assertNotEqual(result, SOURCE)
        self.assertIn(b"fieldwork_artifact_finalize", result)
        self.assertEqual(self.original.read_bytes(), SOURCE)

    def test_anchor_drift_refuses(self):
        corrupted = SOURCE.replace(b"stage_manager.full_test", b"stage_manager.no_longer_exists")
        with patch.object(act, "SOURCE_SHA", act.sha(corrupted)):
            with self.assertRaisesRegex(act.Stop, "INSTALLED_SOURCE_ANCHOR_DRIFT"):
                act.compile_candidate(corrupted, self.payloads["artifact_inbox_overlay.py"])

    def test_released_overlay_mismatch_refuses(self):
        changed = self.payloads["artifact_inbox_overlay.py"].replace(
            b"fieldwork_artifact_finalize", b"fieldwork_artifact_last")
        with self.assertRaises(act.Stop):
            act.compile_candidate(SOURCE, changed)

    def test_preflight_fails_on_existing_module(self):
        (self.root / act.FILES[0]).write_bytes(b"existing")
        with patch.object(act, "service", return_value=True):
            with self.assertRaisesRegex(act.Stop, "MODULES_ALREADY_INSTALLED"):
                act.prepare(COMMIT, self.root)

    def test_preflight_does_not_write(self):
        with patch.object(act, "service", return_value=True):
            candidate, modules = act.prepare(COMMIT, self.root)
        self.assertGreater(len(candidate), len(SOURCE))
        self.assertEqual(set(modules), set(act.MODULES))
        self.assertEqual(self.original.read_bytes(), SOURCE)
        self.assertFalse((self.root / act.FILES[0]).exists())

    def test_activate_then_explicit_rollback(self):
        with patch.object(act, "service", return_value=True) as srv, \
             patch.object(act, "ready", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM"):
            act.activate(COMMIT, self.root, self.state)
            receipt = json.loads((self.state / "receipt.json").read_text())
            self.assertEqual(receipt["state"], "TUNNEL_READY_MCP_DISCOVERY_PENDING")
            self.assertEqual(act.sha(self.original.read_bytes()), receipt["candidate_sha256"])
            self.assertIn(("restart",), [call.args for call in srv.call_args_list])
            act.rollback(self.root, self.state)
        self.assertEqual(self.original.read_bytes(), SOURCE)
        self.assertFalse((self.root / act.FILES[0]).exists())
        self.assertEqual(json.loads((self.state / "receipt.json").read_text())["state"],
                         "ROLLED_BACK")

    def test_restart_failure_auto_rollback(self):
        def run(action):
            return action != "restart" or run.restart_calls > 0
        run.restart_calls = 0

        def mocked(action):
            if action == "restart":
                run.restart_calls += 1
                return run.restart_calls >= 2
            return True

        with patch.object(act, "service", side_effect=mocked), \
             patch("builtins.input", return_value="AKTIVALOM"):
            with self.assertRaisesRegex(act.Stop, "TUNNEL_RESTART_FAILED"):
                act.activate(COMMIT, self.root, self.state)
        self.assertEqual(run.restart_calls, 2)
        self.assertEqual(self.original.read_bytes(), SOURCE)
        self.assertFalse((self.root / act.FILES[0]).exists())

    def test_wrong_local_confirmation_does_nothing(self):
        with patch.object(act, "service", return_value=True), \
             patch("builtins.input", return_value="no"):
            with self.assertRaisesRegex(act.Stop, "LOCAL_APPROVAL_NOT_GIVEN"):
                act.activate(COMMIT, self.root, self.state)
        self.assertFalse((self.state / "receipt.json").exists())
        self.assertEqual(self.original.read_bytes(), SOURCE)

    def test_unexpected_change_blocks_rollback(self):
        with patch.object(act, "service", return_value=True), \
             patch.object(act, "ready", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM"):
            act.activate(COMMIT, self.root, self.state)
        self.original.write_bytes(b"unexpected rewrite")
        with self.assertRaisesRegex(act.Stop, "UNEXPECTED_MCP_CHANGE_NO_OVERWRITE"):
            act.rollback(self.root, self.state)

    def test_no_unapproved_service_action(self):
        with self.assertRaisesRegex(act.Stop, "SERVICE_ACTION_DENIED"):
            act.service("stop")
        with self.assertRaisesRegex(act.Stop, "SERVICE_ACTION_DENIED"):
            act.service("disable")

    def test_commit_pin_required(self):
        self.retrieve_patch.stop()  # Exercise the real guard, never download.
        with self.assertRaisesRegex(act.Stop, "DOWNLOAD_SOURCE_NOT_PINNED"):
            act.retrieve("main", act.MODULES[0])
        with self.assertRaisesRegex(act.Stop, "DOWNLOAD_SOURCE_NOT_PINNED"):
            act.retrieve(COMMIT, "../main.py")


if __name__ == "__main__":
    unittest.main()
