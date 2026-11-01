"""Pinned, local-approval, rollback tests for MCP v2 extension.

No networking, host systemd, sudo, Docker, or production filesystem accesses.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import activate_artifact_extension_v2 as v2

SOURCE = (
    "import artifact_inbox_adapter\n"
    "TOOLS = [\n"
    + v2.TOOLS_OLD
    + "]\n"
    + "ANNOTATIONS = [" + v2.ANNOTATION_OLD + "]\n"
).encode()
INBOX = b"# inert original inbox bytes for synthetic fixture\nX = 1\n"
ADAPTER = b"# inert original adapter bytes\nX = 1\n"
MODULES = {
    name: ("# pinned syntax-valid %s\nX = 1\n" % name).encode()
    for name in (*v2.ADDED, v2.UPDATED)
}
COMMIT = "e" * 40


class V2Tests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("real installer disallows root")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / v2.MCP_REL
        self.state = self.home / v2.STATE_REL
        self.root.mkdir(parents=True, mode=0o700)
        self.state.mkdir(parents=True, mode=0o700)
        (self.root / "fieldwork_mcp.py").write_bytes(SOURCE)
        (self.root / v2.UPDATED).write_bytes(INBOX)
        (self.root / v2.KEEP).write_bytes(ADAPTER)
        for f in self.root.iterdir():
            f.chmod(0o600)
        self.pins = patch.object(v2, "SOURCE_PREVIOUS", v2.sha(SOURCE))
        self.pins.start()
        self.addCleanup(self.pins.stop)
        def fake_download(commit, name):
            if commit == v2.PREVIOUS_COMMIT:
                return {v2.UPDATED: INBOX, v2.KEEP: ADAPTER}[name]
            self.assertEqual(commit, COMMIT)
            return MODULES[name]
        self.source_patch = patch.object(v2, "download", side_effect=fake_download)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)

    def test_installer_matches_reviewed_static_overlay_contract(self):
        from updater import canary_archive_overlay as overlay
        self.assertEqual(v2.IMPORT_OLD, overlay.IMPORT_OLD)
        self.assertEqual(v2.IMPORT_NEW, overlay.IMPORT_NEW)
        self.assertEqual(v2.TOOLS_OLD, overlay.TOOLS_OLD)
        self.assertEqual(v2.TOOLS_NEW, overlay.TOOLS_NEW)
        self.assertEqual(v2.ANNOTATION_OLD, overlay.ANNOTATION_OLD)
        self.assertEqual(v2.ANNOTATION_NEW, overlay.ANNOTATION_NEW)
        self.assertEqual(v2.transformed(SOURCE), overlay.overlay(SOURCE))

    def test_exact_source_transform(self):
        generated = v2.transformed(SOURCE)
        self.assertEqual(generated.count(b'("fieldwork_artifact_qualify"'), 1)
        self.assertEqual(generated.count(b'("fieldwork_artifact_retire"'), 1)
        self.assertIn(b"import canary_archive_adapter", generated)
        self.assertIn(b"import artifact_retention_adapter", generated)
        self.assertEqual((self.root / "fieldwork_mcp.py").read_bytes(), SOURCE)

    def test_mcp_source_drift_denied(self):
        changed = SOURCE.replace(b"artifact_inbox_adapter.finalize",
                                 b"artifact_inbox_adapter.other")
        with patch.object(v2, "SOURCE_PREVIOUS", v2.sha(changed)):
            with self.assertRaisesRegex(v2.Stop, "MCP_INTEGRATION_ANCHOR_DRIFT"):
                v2.transformed(changed)

    def test_reapplication_denied(self):
        generated = v2.transformed(SOURCE)
        with patch.object(v2, "SOURCE_PREVIOUS", v2.sha(generated)):
            with self.assertRaisesRegex(v2.Stop, "ALREADY_UPDATED_OR_PARTIAL"):
                v2.transformed(generated)

    def test_candidate_detects_modified_current_inbox(self):
        (self.root / v2.UPDATED).write_bytes(b"tampered")
        with patch.object(v2, "unit", return_value=True):
            with self.assertRaisesRegex(v2.Stop, "ACTIVE_INBOX_BYTES_DRIFT"):
                v2.candidate(COMMIT, self.root)

    def test_candidate_denies_already_installed_module(self):
        (self.root / v2.ADDED[0]).write_bytes(b"existing")
        with patch.object(v2, "unit", return_value=True):
            with self.assertRaisesRegex(v2.Stop, "V2_MODULE_ALREADY_EXISTS"):
                v2.candidate(COMMIT, self.root)

    def test_preflight_never_changes_installed_files(self):
        with patch.object(v2, "unit", return_value=True):
            newer, modules, old = v2.candidate(COMMIT, self.root)
        self.assertNotEqual(newer, SOURCE)
        self.assertEqual(old, INBOX)
        self.assertEqual(set(modules), set((*v2.ADDED, v2.UPDATED)))
        self.assertEqual((self.root / "fieldwork_mcp.py").read_bytes(), SOURCE)

    def test_declined_local_approval_means_no_change(self):
        with patch.object(v2, "unit", return_value=True), \
             patch("builtins.input", return_value="NO"), \
             patch.object(v2, "sudo_ready", return_value=True) as sudo:
            with self.assertRaisesRegex(v2.Stop, "LOCAL_APPROVAL_REQUIRED"):
                v2.activate(COMMIT, self.root, self.state)
            sudo.assert_not_called()
        self.assertFalse((self.state / "receipt.json").exists())
        self.assertEqual((self.root / v2.UPDATED).read_bytes(), INBOX)

    def test_no_sudo_means_no_change(self):
        with patch.object(v2, "unit", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM_V2"), \
             patch.object(v2, "sudo_ready", return_value=False):
            with self.assertRaisesRegex(v2.Stop, "SUDO_NOT_APPROVED_BEFORE_FILES"):
                v2.activate(COMMIT, self.root, self.state)
        self.assertFalse((self.state / "receipt.json").exists())

    def test_success_then_explicit_rollback(self):
        with patch.object(v2, "unit", return_value=True) as service, \
             patch.object(v2, "local_ready", return_value=True), \
             patch.object(v2, "sudo_ready", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM_V2"):
            v2.activate(COMMIT, self.root, self.state)
            self.assertEqual((self.root / v2.UPDATED).read_bytes(), MODULES[v2.UPDATED])
            self.assertIn(b"fieldwork_artifact_retire", (self.root / "fieldwork_mcp.py").read_bytes())
            self.assertEqual(json.loads((self.state / "receipt.json").read_text())["status"],
                             "TUNNEL_READY_DISCOVERY_PENDING")
            self.assertTrue(all((self.root / name).exists() for name in v2.ADDED))
            v2.restore(self.root, self.state)
        self.assertEqual((self.root / "fieldwork_mcp.py").read_bytes(), SOURCE)
        self.assertEqual((self.root / v2.UPDATED).read_bytes(), INBOX)
        self.assertTrue(all(not (self.root / name).exists() for name in v2.ADDED))
        self.assertEqual(service.call_args_list[-1].args, ("restart",))

    def test_unhealthy_tunnel_rolls_back(self):
        def service(action):
            if action == "is-active":
                return True
            if action == "restart":
                return True
            return False
        with patch.object(v2, "unit", side_effect=service), \
             patch.object(v2, "local_ready", return_value=False), \
             patch.object(v2, "sudo_ready", return_value=True), \
             patch.object(v2.time, "sleep"), \
             patch("builtins.input", return_value="AKTIVALOM_V2"):
            with self.assertRaisesRegex(v2.Stop, "TUNNEL_HEALTH_FAILED"):
                v2.activate(COMMIT, self.root, self.state)
        self.assertEqual((self.root / "fieldwork_mcp.py").read_bytes(), SOURCE)
        self.assertEqual((self.root / v2.UPDATED).read_bytes(), INBOX)
        self.assertEqual(json.loads((self.state / "receipt.json").read_text())["status"],
                         "ROLLED_BACK")

    def test_failed_restart_rolls_back(self):
        restarts = 0
        def service(action):
            nonlocal restarts
            if action != "restart":
                return True
            restarts += 1
            return restarts > 1
        with patch.object(v2, "unit", side_effect=service), \
             patch.object(v2, "sudo_ready", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM_V2"):
            with self.assertRaisesRegex(v2.Stop, "TUNNEL_RESTART_FAILED"):
                v2.activate(COMMIT, self.root, self.state)
        self.assertEqual(restarts, 2)
        self.assertEqual((self.root / "fieldwork_mcp.py").read_bytes(), SOURCE)
        self.assertTrue(all(not (self.root / name).exists() for name in v2.ADDED))

    def test_changed_live_source_blocks_rollback(self):
        with patch.object(v2, "unit", return_value=True), \
             patch.object(v2, "local_ready", return_value=True), \
             patch.object(v2, "sudo_ready", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM_V2"):
            v2.activate(COMMIT, self.root, self.state)
        (self.root / "fieldwork_mcp.py").write_bytes(b"unreviewed change")
        with self.assertRaisesRegex(v2.Stop, "ACTIVE_MCP_CHANGED_NO_OVERWRITE"):
            v2.restore(self.root, self.state)

    def test_unauthorized_unit_action_denied(self):
        with self.assertRaisesRegex(v2.Stop, "UNAUTHORIZED_SYSTEMD_ACTION"):
            v2.unit("stop")
        with self.assertRaisesRegex(v2.Stop, "UNAUTHORIZED_SYSTEMD_ACTION"):
            v2.unit("disable")

    def test_rollback_has_not_mutated_production(self):
        with patch.object(v2, "unit", return_value=True), \
             patch.object(v2, "local_ready", return_value=True), \
             patch.object(v2, "sudo_ready", return_value=True), \
             patch("builtins.input", return_value="AKTIVALOM_V2"):
            v2.activate(COMMIT, self.root, self.state)
        record = json.loads((self.state / "receipt.json").read_text())
        self.assertFalse(record["production_modified"])
        self.assertEqual(record["previous_source_sha256"], v2.sha(SOURCE))


if __name__ == "__main__":
    unittest.main()
