"""M12 local activation safety contracts: never touch the actual host."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from updater import mcp_self_service_activate as a


class ActivateFailClosedTests(unittest.TestCase):
    def test_exact_read_write_scope_excludes_production(self):
        self.assertNotIn("/opt/fieldwork", str(a.ROOT))
        self.assertEqual(a.UNIT, "fieldwork-pi-tunnel.service")
        self.assertNotIn("rm", a.MODULE_PINS)
        self.assertEqual(len(a.MODULE_PINS), 3)
        self.assertEqual(a.CONSENT, "ENGEDÉLYEZEM_M12")

    def test_bad_commit_is_denied_before_host_lookup(self):
        for value in ("", "../main", "a" * 39, "z" * 40, 123):
            with self.subTest(value=value):
                with self.assertRaises(a.ActivationStop):
                    a.execute_once(value, confirm=True)

    def test_no_explicit_activation_denied(self):
        with self.assertRaisesRegex(
                a.ActivationStop, "EXPLICIT_ACTIVATION_REQUIRED"):
            a.execute_once("a" * 40, confirm=False)

    def test_no_root_activation(self):
        with patch.object(a.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(a.ActivationStop, "ROOT_DENIED"):
                a.execute_once("a" * 40, confirm=True)

    def test_only_read_active_and_restart_existing_tunnel(self):
        with patch.object(a.subprocess, "run", return_value=SimpleNamespace(
                returncode=0)) as proc:
            self.assertTrue(a.systemd("is-active"))
            self.assertTrue(a.systemd("restart"))
        one, two = [c.args[0] for c in proc.call_args_list]
        self.assertEqual(one, ["systemctl", "is-active", a.UNIT])
        self.assertEqual(two, ["sudo", "-n", "systemctl", "restart", a.UNIT])
        for forbidden in ("stop", "enable", "disable", "start", "kill"):
            with self.assertRaises(a.ActivationStop):
                a.systemd(forbidden)

    def test_reject_untrusted_download_names_before_network(self):
        with self.assertRaisesRegex(a.ActivationStop,
                                    "DOWNLOAD_SOURCE_NOT_ALLOWED"):
            a.get_pinned("a" * 40, "../../fieldwork_mcp.py")
        with self.assertRaisesRegex(a.ActivationStop,
                                    "DOWNLOAD_SOURCE_NOT_ALLOWED"):
            a.get_pinned("main", "mcp_self_diagnostics.py")

    def test_atomic_write_and_exclusive_do_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "test.txt"
            a.atomic(path, b"hello", new=True)
            self.assertEqual(path.read_bytes(), b"hello")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(a.ActivationStop):
                a.atomic(path, b"overwrite", new=True)
            self.assertEqual(path.read_bytes(), b"hello")
            a.atomic(path, b"new data")
            self.assertEqual(path.read_bytes(), b"new data")
            link = root / "unsafe"
            link.symlink_to(path)
            with self.assertRaises(a.ActivationStop):
                a.atomic(link, b"UNSAFE")
            self.assertEqual(path.read_bytes(), b"new data")

    def test_read_owned_blocks_symlink_and_loose_mode(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "secret.py"
            path.write_bytes(b"pass\n")
            path.chmod(0o644)
            with self.assertRaises(a.ActivationStop):
                a.read_owned(path)
            path.chmod(0o600)
            self.assertEqual(a.read_owned(path), b"pass\n")
            link = Path(td) / "link"
            link.symlink_to(path)
            with self.assertRaises(a.ActivationStop):
                a.read_owned(link)

    def test_rollback_refuses_unexpected_current_source_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "mcp"
            state = Path(td) / "state"
            root.mkdir()
            state.mkdir()
            oldmain = b"old-main\n"
            oldrun = b"old-sandbox\n"
            (state / "previous-fieldwork_mcp.py").write_bytes(oldmain)
            (state / "previous-sandbox_command.py").write_bytes(oldrun)
            (root / "fieldwork_mcp.py").write_bytes(b"UNKNOWN DRIFT")
            (root / "sandbox_command.py").write_bytes(oldrun)
            for p in list(root.iterdir()) + list(state.iterdir()):
                p.chmod(0o600)
            receipt = {"new_mcp_sha256": hashlib.sha256(b"newmain").hexdigest(),
                       "new_sandbox_sha256": hashlib.sha256(b"newrun").hexdigest()}
            with patch.object(a, "MAIN_PIN",
                              hashlib.sha256(oldmain).hexdigest()):
                with patch.object(a, "RUNNER_PIN",
                                  hashlib.sha256(oldrun).hexdigest()):
                    with self.assertRaisesRegex(
                            a.ActivationStop, "ROLLBACK_SOURCE_CHANGED"):
                        a.restore(root, state, receipt)
            self.assertEqual((root / "fieldwork_mcp.py").read_bytes(),
                             b"UNKNOWN DRIFT")

    def test_rollback_restores_pinned_sources_and_removes_only_own_module(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "mcp"
            state = Path(td) / "state"
            root.mkdir()
            state.mkdir()
            oldmain, oldrun = b"original\n", b"runner\n"
            newmain, newrun = b"candidate\n", b"runner-candidate\n"
            (state / "previous-fieldwork_mcp.py").write_bytes(oldmain)
            (state / "previous-sandbox_command.py").write_bytes(oldrun)
            (root / "fieldwork_mcp.py").write_bytes(newmain)
            (root / "sandbox_command.py").write_bytes(newrun)
            (root / "mcp_self_diagnostics.py").write_bytes(b"diag\n")
            for p in list(root.iterdir()) + list(state.iterdir()):
                p.chmod(0o600)
            receipt = {"new_mcp_sha256": a.sha(newmain),
                       "new_sandbox_sha256": a.sha(newrun)}
            with patch.object(a, "MAIN_PIN", a.sha(oldmain)), patch.object(
                    a, "RUNNER_PIN", a.sha(oldrun)), patch.dict(
                    a.MODULE_PINS, {"mcp_self_diagnostics.py": a.sha(b"diag\n")}), patch.object(
                    a, "systemd", return_value=True) as restart:
                a.restore(root, state, receipt)
            self.assertEqual((root / "fieldwork_mcp.py").read_bytes(), oldmain)
            self.assertEqual((root / "sandbox_command.py").read_bytes(), oldrun)
            self.assertFalse((root / "mcp_self_diagnostics.py").exists())
            self.assertEqual(receipt["status"], "ROLLED_BACK")
            restart.assert_called_once_with("restart")
            self.assertEqual(
                (state / "receipt.json").stat().st_mode & 0o777, 0o600)

    def test_diagnostic_module_does_not_offer_update_handler(self):
        import inspect
        from updater import mcp_self_diagnostics
        text = inspect.getsource(mcp_self_diagnostics)
        self.assertNotIn("def update(", text)
        self.assertNotIn("def activate(", text)
        self.assertNotIn("subprocess.Popen", text)

    def test_readonly_compilation_of_downloaded_modules(self):
        for mod in a.MODULE_PINS:
            self.assertRegex(a.MODULE_PINS[mod], r"^[a-f0-9]{64}$")


class EntireActivationTransactionTests(unittest.TestCase):
    """Simulated one-shot operator flow, fully confined to temp directories."""

    def setup_temp(self, home):
        import os
        source = home / a.ROOT
        source.mkdir(parents=True, mode=0o700)
        state_parent = home / a.STATE_ROOT
        state_parent.mkdir(parents=True, mode=0o700)
        # Temporary root and all parent dirs stay owned by current user.
        for path in (source / "fieldwork_mcp.py", source / "sandbox_command.py"):
            path.write_bytes(b"old-mcp" if path.name == "fieldwork_mcp.py"
                             else b"old-sandbox")
            path.chmod(0o600)
        return source, state_parent / a.STATE_NAME

    def fake_transaction(self, home, *, approve=True, restart_results=None):
        from contextlib import ExitStack
        source, state = self.setup_temp(home)
        oldmain, oldrun = b"old-mcp", b"old-sandbox"
        newmain, newrun = b"new-mcp", b"new-sandbox"
        extension = b"def source_inventory(args):\n    return {}\n"
        sources = {name: b"pass\n" for name in a.MODULE_PINS}
        sources["mcp_self_diagnostics.py"] = extension
        fake_patcher = SimpleNamespace(build_mcp_and_cleanup=lambda _m, _s: {
            "status": "M12_OFFLINE_CANDIDATE_ONLY",
            "activation_authorized": False,
            "mcp_bytes": newmain,
            "sandbox_bytes": newrun,
        })
        receipt = None
        with ExitStack() as stack:
            stack.enter_context(patch.object(a.Path, "home",
                               return_value=home))
            stack.enter_context(patch.object(a, "MAIN_PIN",
                               a.sha(oldmain)))
            stack.enter_context(patch.object(a, "RUNNER_PIN",
                               a.sha(oldrun)))
            stack.enter_context(patch.dict(a.MODULE_PINS, {
                "mcp_self_diagnostics.py": a.sha(extension)}))
            stack.enter_context(patch.object(a, "get_pinned",
                               side_effect=lambda _commit, name: sources[name]))
            stack.enter_context(patch.object(a, "modules_from_pins",
                               return_value=fake_patcher))
            system = stack.enter_context(
                patch.object(a, "systemd",
                    side_effect=(lambda operation:
                        restart_results.pop(0) if operation == "restart"
                        and restart_results is not None else True)))
            stack.enter_context(patch.object(a, "ready", return_value=True))
            stack.enter_context(patch.object(a.subprocess, "run",
                               return_value=SimpleNamespace(returncode=0)))
            stack.enter_context(patch("builtins.input", return_value=(
                a.CONSENT if approve else "NEM")))
            try:
                receipt = a.execute_once("f" * 40, confirm=True)
            except a.ActivationStop:
                if approve:
                    raise
            if approve:
                self.assertEqual((source / "fieldwork_mcp.py").read_bytes(),
                                 newmain if receipt["status"] ==
                                 "M12_READY_TOOL_DISCOVERY_PENDING" else oldmain)
                self.assertEqual((source / "sandbox_command.py").read_bytes(),
                                 newrun if receipt["status"] ==
                                 "M12_READY_TOOL_DISCOVERY_PENDING" else oldrun)
            else:
                self.assertEqual((source / "fieldwork_mcp.py").read_bytes(), oldmain)
                self.assertFalse(state.exists())
                system.assert_called_once_with("is-active")
        return receipt, source, state

    def test_one_approval_installs_all_three_files_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, root, state = self.fake_transaction(Path(td))
            self.assertEqual(receipt["status"], "M12_READY_TOOL_DISCOVERY_PENDING")
            self.assertTrue((root / "mcp_self_diagnostics.py").exists())
            self.assertEqual((state / "previous-fieldwork_mcp.py").read_bytes(),
                             b"old-mcp")
            self.assertEqual((state / "previous-sandbox_command.py").read_bytes(),
                             b"old-sandbox")
            self.assertEqual((state / "receipt.json").stat().st_mode & 0o777,
                             0o600)
            self.assertFalse(receipt["production_modified"])
            self.assertFalse(receipt["new_tunnel_created"])

    def test_refused_local_approval_leaves_no_files_or_state(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, root, state = self.fake_transaction(Path(td), approve=False)
            self.assertIsNone(receipt)
            self.assertFalse((root / "mcp_self_diagnostics.py").exists())
            self.assertFalse(state.exists())

    def test_failed_service_restart_restores_both_originals(self):
        with tempfile.TemporaryDirectory() as td:
            # The restart fails before readiness. Rollback uses the same
            # fixed service and creates no new tunnel.
            try:
                self.fake_transaction(Path(td), restart_results=[False, True])
            except a.ActivationStop as exc:
                self.assertIn("TUNNEL_RESTART_FAILED", str(exc))
            else:
                self.fail("restart failure was not propagated")
            root = Path(td) / a.ROOT
            state = Path(td) / a.STATE_ROOT / a.STATE_NAME
            self.assertEqual((root / "fieldwork_mcp.py").read_bytes(),
                             b"old-mcp")
            self.assertEqual((root / "sandbox_command.py").read_bytes(),
                             b"old-sandbox")
            self.assertFalse((root / "mcp_self_diagnostics.py").exists())
            self.assertEqual(__import__("json").loads(
                (state / "receipt.json").read_text())["status"],
                "ROLLED_BACK")


if __name__ == "__main__":
    unittest.main()
