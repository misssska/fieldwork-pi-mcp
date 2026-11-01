"""M14 UI approval => local-only signed handoff => atomic update proof.

All modules are isolated to tmp paths. No Pi, systemd, Docker or remote
installer is invoked. This validates wiring, not deployment readiness.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import linux_upgrade_gate as gate
from updater import linux_upgrade_review_ui as review
from updater import linux_upgrade_local_handoff as handoff
from updater import linux_upgrade_local_transaction as tx

NOW = 1793468000
SECRET = b"locally-owned-operator-secret-with-32bytes-minimum-123"
OPERATOR_TOKEN = b"independent-ui-auth-credential-32bytes-plus-123"
OLD = b"def mcp():\n    return 1\n"
NEW = b"def mcp():\n    return 2\n"
EXTRA = b"def linux_metrics():\n    return 3\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def setup_fixture(home):
    installed = home / "installed"
    worker = home / "worker"
    ui_store = home / "operator"
    for root in (installed, worker, ui_store):
        root.mkdir(mode=0o700)
    (worker / "spent").mkdir(mode=0o700)
    (installed / "fieldwork_mcp.py").write_bytes(OLD)
    (installed / "fieldwork_mcp.py").chmod(0o600)
    policy = gate.HostPolicy(
        "fieldwork-pi",
        frozenset({"fieldwork_mcp.py", "linux_telemetry.py"}),
    )
    request = {
        "protocol": 1,
        "host_id": "fieldwork-pi",
        "commit_sha": "f" * 40,
        "issued_at": NOW - 10,
        "expires_at": NOW + 120,
        "files": [
            {"name": "fieldwork_mcp.py", "old_sha256": sha(OLD),
             "new_sha256": sha(NEW), "action": "replace"},
            {"name": "linux_telemetry.py", "old_sha256": None,
             "new_sha256": sha(EXTRA), "action": "create"},
        ],
    }
    plan = gate.validate_plan(
        request, policy,
        {"fieldwork_mcp.py": sha(OLD), "linux_telemetry.py": None}, NOW)
    session = review.ReviewSession(
        plan, local_secret=SECRET, operator_token=OPERATOR_TOKEN, handoff=ui_store)
    return installed, worker, ui_store, policy, request, session


def run(h, w, approval_dir, policy, request, *,
        secret=SECRET, now=NOW, content=None, health=lambda: True):
    return handoff.apply_one_reviewed_plan(
        request, policy, install_root=h, state_root=w,
        handoff_root=approval_dir,
        source_bytes=content if content is not None else {
            "fieldwork_mcp.py": NEW, "linux_telemetry.py": EXTRA},
        local_secret=secret, now=now, health_check=health,
    )


class BrowserToLocalInstallerIntegration(unittest.TestCase):
    def test_approved_handoff_updates_only_fixed_modules(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            result = run(install, state, inbox, policy, request)
            self.assertEqual(result["status"], "LOCAL_APPROVED_HANDOFF_APPLIED")
            self.assertFalse(result["real_service_restart_performed"])
            self.assertFalse(result["production_modified"])
            self.assertFalse(result["approval_ticket_disclosed_remotely"])
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), NEW)
            self.assertEqual((install/"linux_telemetry.py").read_bytes(), EXTRA)
            self.assertEqual(len(list(inbox.iterdir())), 1)
            receipt = json.loads(
                (state/ui.plan.plan_sha256/"receipt.json").read_text())
            self.assertEqual(receipt["status"], "APPLIED")

    def test_rejected_ui_is_not_executable(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.deny(ui.csrf)
            with self.assertRaisesRegex(
                    handoff.HandoffDenied, "HANDOFF_NOT_REGULAR_OR_SYMLINK"):
                run(install, state, inbox, policy, request)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_ui_approval_replay_is_denied_by_durable_local_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            run(install, state, inbox, policy, request)
            with self.assertRaises((gate.UpgradeDenied, tx.LocalApplyDenied)):
                run(install, state, inbox, policy, request)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), NEW)

    def test_foreign_host_cannot_use_same_ticket(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            request["host_id"] = "orange-pi"
            with self.assertRaisesRegex(gate.UpgradeDenied,
                                        "PLAN_HOST_MISMATCH"):
                run(install, state, inbox, policy, request)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_corrupted_mac_before_any_write_denied(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            path = inbox / (ui.plan.plan_sha256 + ".json")
            ticket = json.loads(path.read_text())
            ticket["mac"] = "0" * 64
            path.write_bytes(gate.canon(ticket))
            with self.assertRaisesRegex(gate.UpgradeDenied, "APPROVAL_MAC_DENIED"):
                run(install, state, inbox, policy, request)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertFalse((install/"linux_telemetry.py").exists())

    def test_tampered_source_sha_denied_despite_valid_approval(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            with self.assertRaisesRegex(tx.LocalApplyDenied,
                                        "LOCAL_PAYLOAD_SHA256_DENIED"):
                run(install, state, inbox, policy, request, content={
                    "fieldwork_mcp.py": NEW + b"#exfil\n",
                    "linux_telemetry.py": EXTRA,
                })
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_expired_ticket_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            with self.assertRaises(gate.UpgradeDenied):
                run(install, state, inbox, policy, request, now=NOW+130)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_symlink_approval_ticket_is_never_followed(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            outside = inbox / "outside"
            outside.write_text("PRIVATE")
            (inbox / (ui.plan.plan_sha256 + ".json")).symlink_to(outside)
            with self.assertRaisesRegex(handoff.HandoffDenied,
                                        "HANDOFF_NOT_REGULAR_OR_SYMLINK"):
                run(install, state, inbox, policy, request)
            self.assertEqual(outside.read_text(), "PRIVATE")

    def test_invalid_handoff_permissions_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            (inbox / (ui.plan.plan_sha256+".json")).chmod(0o644)
            with self.assertRaisesRegex(handoff.HandoffDenied,
                                        "HANDOFF_FILE_MODE_SIZE_DENIED"):
                run(install, state, inbox, policy, request)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_negative_health_rolls_back_from_approved_ui_ticket(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, inbox, policy, request, ui = setup_fixture(Path(td))
            ui.approve(ui.csrf, ui.plan.plan_sha256, NOW)
            checks = []
            def health():
                checks.append(True)
                return len(checks) == 2
            with self.assertRaisesRegex(tx.LocalApplyDenied,
                                        "LOCAL_HEALTH_CHECK_FAILED"):
                run(install, state, inbox, policy, request, health=health)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertFalse((install/"linux_telemetry.py").exists())
            self.assertEqual(len(checks), 2)

    def test_handoff_has_no_network_exec_or_remote_file_selector(self):
        import inspect
        code = inspect.getsource(handoff)
        for bad in ("subprocess.run(", "os.system(", "docker ", "shell=True",
                    "socket.connect(", "requests.get(", "exec(", "eval("):
            self.assertNotIn(bad, code)


if __name__ == "__main__":
    unittest.main()
