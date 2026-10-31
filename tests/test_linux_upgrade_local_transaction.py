"""M14 isolated local transaction tests: source-only, no Docker or Pi."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import linux_upgrade_gate as gate
from updater import linux_upgrade_local_transaction as tx

NOW = 1793465000
SECRET = b"local-only-hmac-key-tests-32chars-minimum-long" + b"more"
OLD = b"def sample():\n    return 1\n"
NEW = b"def sample():\n    return 2\n"
CREATE = b"def telemetry():\n    return 3\n"
HOST = "fieldwork-pi"


def sha(value):
    return hashlib.sha256(value).hexdigest()


class LocalTransactionTests(unittest.TestCase):
    def prepare(self, home):
        install = home / "installed-mcp"
        state = home / "local-operator-state"
        install.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        (state / "spent").mkdir(mode=0o700)
        (install / "fieldwork_mcp.py").write_bytes(OLD)
        (install / "fieldwork_mcp.py").chmod(0o600)
        policy = gate.HostPolicy(
            HOST,
            frozenset({"fieldwork_mcp.py", "linux_telemetry.py"}),
        )
        request = {
            "protocol": 1, "host_id": HOST,
            "commit_sha": "e"*40, "issued_at": NOW-10,
            "expires_at": NOW+120, "files": [
                {"name": "fieldwork_mcp.py", "action": "replace",
                 "old_sha256": sha(OLD), "new_sha256": sha(NEW)},
                {"name": "linux_telemetry.py", "action": "create",
                 "old_sha256": None, "new_sha256": sha(CREATE)},
            ],
        }
        plan = gate.validate_plan(
            request, policy,
            {"fieldwork_mcp.py": sha(OLD), "linux_telemetry.py": None},
            NOW)
        approval = gate.issue_local_approval(
            plan, local_secret=SECRET, operator_present=True, now=NOW)
        return install, state, policy, request, approval

    def apply(self, install, state, policy, request, approval,
              *, payload=None, health=lambda: True, now=NOW):
        return tx.apply_approved(
            request, policy, install_root=install, state_root=state,
            source_bytes=payload if payload is not None else
            {"fieldwork_mcp.py": NEW, "linux_telemetry.py": CREATE},
            approval=approval, local_secret=SECRET, now=now,
            health_check=health,
        )

    def test_one_approval_writes_only_two_modules_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            r = self.apply(install, state, policy, request, approval)
            self.assertEqual(r["status"], "LOCAL_APPROVED_FILES_APPLIED")
            self.assertFalse(r["remote_shell_executed"])
            self.assertFalse(r["production_modified"])
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), NEW)
            self.assertEqual((install/"linux_telemetry.py").read_bytes(), CREATE)
            digest = r["plan_sha256"]
            journal = json.loads((state/digest/"receipt.json").read_text())
            self.assertEqual(journal["status"], "APPLIED")
            self.assertEqual((state/digest/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertEqual(len(list((state/"spent").iterdir())), 1)
            self.assertEqual((state/digest/"receipt.json").stat().st_mode & 0o777, 0o600)

    def test_identical_approval_replay_denied_without_touching_source(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            self.apply(install, state, policy, request, approval)
            with self.assertRaises((tx.LocalApplyDenied, gate.UpgradeDenied)):
                self.apply(install, state, policy, request, approval)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), NEW)

    def test_invalid_hmac_fails_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            approval["mac"] = "0"*64
            with self.assertRaisesRegex(gate.UpgradeDenied, "APPROVAL_MAC_DENIED"):
                self.apply(install, state, policy, request, approval)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertFalse((install/"linux_telemetry.py").exists())
            self.assertEqual(len(list((state/"spent").iterdir())), 0)

    def test_modified_binary_content_sha_denied(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_PAYLOAD_SHA256_DENIED"):
                self.apply(install, state, policy, request, approval, payload={
                    "fieldwork_mcp.py": NEW + b"# changed",
                    "linux_telemetry.py": CREATE,
                })
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertEqual(len(list((state/"spent").iterdir())), 0)

    def test_invalid_python_denied_even_if_sha_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            bad = b"not valid python %%%\n"
            request["files"][0]["new_sha256"] = sha(bad)
            plan = gate.validate_plan(
                request, policy, {"fieldwork_mcp.py": sha(OLD),
                                  "linux_telemetry.py": None}, NOW)
            approval = gate.issue_local_approval(
                plan, local_secret=SECRET, operator_present=True, now=NOW)
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_PAYLOAD_PYTHON_DENIED"):
                self.apply(install, state, policy, request, approval, payload={
                    "fieldwork_mcp.py": bad,
                    "linux_telemetry.py": CREATE,
                })
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_service_health_fail_automatically_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            calls = []
            def health():
                calls.append(len(calls))
                return len(calls) == 2
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_HEALTH_CHECK_FAILED"):
                self.apply(install, state, policy, request, approval, health=health)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertFalse((install/"linux_telemetry.py").exists())
            self.assertEqual(len(calls),2)
            folders = [x for x in state.iterdir() if x.is_dir() and x.name != "spent"]
            self.assertEqual(len(folders), 1)
            journal = json.loads((folders[0]/"receipt.json").read_text())
            self.assertEqual(journal["status"], "ROLLED_BACK")

    def test_no_approval_and_foreign_host_never_writes(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            request["host_id"] = "orange-pi"
            with self.assertRaisesRegex(gate.UpgradeDenied, "PLAN_HOST_MISMATCH"):
                self.apply(install, state, policy, request, approval)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_root_directory_permissions_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            state.chmod(0o755)
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_ROOT_PERMISSIONS_DENIED"):
                self.apply(install, state, policy, request, approval)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_disallows_symlink_installed_module(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            target = install/"outside"
            target.write_bytes(OLD)
            (install/"fieldwork_mcp.py").unlink()
            (install/"fieldwork_mcp.py").symlink_to(target)
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_MODULE_SYMLINK_DENIED"):
                self.apply(install, state, policy, request, approval)
            self.assertEqual(target.read_bytes(), OLD)

    def test_expired_local_approval_denied(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            with self.assertRaises(gate.UpgradeDenied):
                self.apply(install, state, policy, request, approval, now=NOW+130)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_unknown_payload_filename_denied(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_PAYLOAD_FILE_SET_DENIED"):
                self.apply(install, state, policy, request, approval, payload={
                    "fieldwork_mcp.py": NEW,
                    "linux_telemetry.py": CREATE,
                    "../../etc/shadow": b"x",
                })
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_readonly_recovery_denies_applied_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            r = self.apply(install, state, policy, request, approval)
            with self.assertRaisesRegex(tx.LocalApplyDenied, "LOCAL_RECOVERY_NOT_PENDING"):
                tx.recover_unfinished(
                    r["plan_sha256"], policy, install_root=install,
                    state_root=state, health_check=lambda: True)

    def test_crash_recovery_restores_one_modified_one_new_module(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            hashes = {"fieldwork_mcp.py": sha(OLD), "linux_telemetry.py": None}
            plan = gate.validate_plan(request, policy, hashes, NOW)
            folder = state/plan.plan_sha256
            folder.mkdir(mode=0o700)
            tx.write_atomic(folder, "fieldwork_mcp.py", OLD, create=True)
            tx.write_atomic(folder, "plan.json", gate.canon(request), create=True)
            journal = {
                "status": "APPLYING", "host_id": policy.host_id,
                "plan_sha256": plan.plan_sha256,
                "files": [dict(x) for x in plan.files],
                "nonce": approval["nonce"], "production_modified": False,
            }
            tx._receipt(folder, journal, create=True)
            tx.write_atomic(install, "fieldwork_mcp.py", NEW)
            tx.write_atomic(install, "linux_telemetry.py", CREATE, create=True)
            result = tx.recover_unfinished(
                plan.plan_sha256, policy,
                install_root=install, state_root=state,
                health_check=lambda: True)
            self.assertEqual(result["status"], "LOCAL_ROLLBACK_RESTORED")
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)
            self.assertFalse((install/"linux_telemetry.py").exists())
            self.assertEqual(json.loads(
                (folder/"receipt.json").read_text())["status"], "ROLLED_BACK")

    def test_recovery_refuses_overwrite_unrelated_changes(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            plan = gate.validate_plan(
                request, policy, {"fieldwork_mcp.py": sha(OLD),
                                  "linux_telemetry.py": None}, NOW)
            folder = state/plan.plan_sha256
            folder.mkdir(mode=0o700)
            tx.write_atomic(folder, "fieldwork_mcp.py", OLD, create=True)
            tx.write_atomic(folder, "plan.json", gate.canon(request), create=True)
            tx._receipt(folder, {
                "status": "APPLYING", "host_id": HOST,
                "plan_sha256": plan.plan_sha256,
                "files": [dict(x) for x in plan.files],
                "nonce": approval["nonce"], "production_modified": False,
            }, create=True)
            tx.write_atomic(install, "fieldwork_mcp.py",
                            b"print('somebody else modified this')\n")
            with self.assertRaisesRegex(
                    tx.LocalApplyDenied, "LOCAL_RESTORE_FOREIGN_CHANGE_DENIED"):
                tx.recover_unfinished(plan.plan_sha256, policy,
                    install_root=install, state_root=state,
                    health_check=lambda: True)
            self.assertNotEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_recovery_rejects_tampered_journal_manifest_binding(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            plan = gate.validate_plan(
                request, policy, {"fieldwork_mcp.py": sha(OLD),
                                  "linux_telemetry.py": None}, NOW)
            folder = state / plan.plan_sha256
            folder.mkdir(mode=0o700)
            tx.write_atomic(folder, "fieldwork_mcp.py", OLD, create=True)
            altered = dict(request)
            altered["commit_sha"] = "f" * 40
            tx.write_atomic(folder, "plan.json", gate.canon(altered), create=True)
            tx._receipt(folder, {
                "status": "APPLYING", "host_id": HOST,
                "plan_sha256": plan.plan_sha256,
                "files": [dict(x) for x in plan.files],
                "nonce": approval["nonce"], "production_modified": False,
            }, create=True)
            tx.write_atomic(install, "fieldwork_mcp.py", NEW)
            with self.assertRaisesRegex(
                    tx.LocalApplyDenied, "LOCAL_JOURNAL_PLAN_BINDING_DENIED"):
                tx.recover_unfinished(plan.plan_sha256, policy,
                    install_root=install, state_root=state,
                    health_check=lambda: True)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), NEW)

    def test_root_execution_denied_without_touching_any_files(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            with patch.object(tx.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(
                        tx.LocalApplyDenied, "LOCAL_ROOT_EXECUTION_DENIED"):
                    self.apply(install, state, policy, request, approval)
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_status_is_not_falsely_marked_applied_on_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            install, state, policy, request, approval = self.prepare(Path(td))
            with self.assertRaises(tx.LocalApplyDenied):
                self.apply(install, state, policy, request, approval,
                           health=lambda: False)
            # If health also fails in rollback, state remains APPLYING
            folders = [x for x in state.iterdir() if x.is_dir() and x.name != "spent"]
            journal = json.loads((folders[0]/"receipt.json").read_text())
            self.assertEqual(journal["status"], "APPLYING")
            self.assertEqual((install/"fieldwork_mcp.py").read_bytes(), OLD)

    def test_does_not_run_source_or_shell(self):
        import inspect
        source = inspect.getsource(tx)
        for forbidden in ("exec(", "eval(", "import subprocess",
                          "os.system(", "docker ", "shell=True", "sudo -n"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
