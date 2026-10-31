"""M13 installer security: refusal, exact scope, rollback, complete temp-home flow."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from updater import mcp_linux_telemetry_activate as m


def fixture_files(home):
    root = home / m.INSTALL
    state_parent = home / m.STATE
    root.mkdir(parents=True, mode=0o700)
    state_parent.mkdir(parents=True, mode=0o700)
    for p in (home / ".local", home / ".local/share",
              home / ".local/share/fieldwork-pi-mcp",
              home / ".local/state", state_parent, root):
        p.chmod(0o700)
    main = root / "fieldwork_mcp.py"
    main.write_bytes(b"old M12 deployed main")
    main.chmod(0o600)
    return root, state_parent / m.ATTEMPT


class M13InstallerSafetyTests(unittest.TestCase):
    def test_root_denied(self):
        with patch.object(m.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(m.M13Stop, "M13_ROOT_DENIED"):
                m.activate_once("f" * 40, approved=True)

    def test_activation_flag_required(self):
        with self.assertRaisesRegex(
                m.M13Stop, "M13_ACTIVATION_FLAG_REQUIRED"):
            m.activate_once("f" * 40, approved=False)

    def test_immutable_commit_required(self):
        for invalid in ("main", "", "f" * 39, "z" * 40, None):
            with self.subTest(invalid=invalid), self.assertRaises(m.M13Stop):
                m.activate_once(invalid, approved=True)

    def test_download_allowed_only_three_modules_from_fixed_commit(self):
        with self.assertRaisesRegex(m.M13Stop, "M13_DOWNLOAD_TARGET_DENIED"):
            m.download("f" * 40, "../../etc/passwd")
        with self.assertRaisesRegex(m.M13Stop, "M13_DOWNLOAD_TARGET_DENIED"):
            m.download("main", "linux_telemetry.py")
        self.assertEqual(set(m.MODULE_PINS), {
            "linux_telemetry.py", "mcp_linux_telemetry.py",
            "mcp_linux_telemetry_overlay.py",
        })

    def test_only_read_active_and_restart_fixed_existing_unit(self):
        with patch.object(m.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(m.service("is-active"))
            self.assertTrue(m.service("restart"))
        commands = [c.args[0] for c in run.call_args_list]
        self.assertEqual(commands, [
            ["systemctl", "is-active", m.UNIT],
            ["sudo", "-n", "systemctl", "restart", m.UNIT],
        ])
        for forbidden in ("start", "enable", "stop", "disable"):
            with self.assertRaises(m.M13Stop):
                m.service(forbidden)

    def test_no_unsafe_write_to_link_or_existing_new_target(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "new"
            m.atomic(dest, b"first", create=True)
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(m.M13Stop, "M13_TARGET_COLLISION"):
                m.atomic(dest, b"second", create=True)
            link = Path(td) / "link"
            link.symlink_to(dest)
            with self.assertRaises(m.M13Stop):
                m.atomic(link, b"secret")
            self.assertEqual(dest.read_bytes(), b"first")

    def test_backup_read_requires_owner_only(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "file"
            dest.write_bytes(b"old")
            dest.chmod(0o644)
            with self.assertRaisesRegex(m.M13Stop,
                                        "M13_SOURCE_MODE_OR_SIZE"):
                m.owned(dest)
            dest.chmod(0o600)
            self.assertEqual(m.owned(dest), b"old")
            (Path(td) / "link").symlink_to(dest)
            with self.assertRaises(m.M13Stop):
                m.owned(Path(td) / "link")

    def scenario(self, home, *, approval=True, sudo_ok=True,
                 first_restart_ok=True, active_sha_correct=True):
        root, state = fixture_files(home)
        source = b"old M12 deployed main"
        candidate = b"# Telemetry candidate\npass\n"
        modules = {name: b"pass\n" for name in m.MODULE_PINS}
        fake_overlay = SimpleNamespace(
            build=lambda value: {
                "status": "M13_OFFLINE_CANDIDATE_ONLY",
                "activation_authorized": False,
                "new_sha256": m.sha(candidate),
                "candidate_bytes": candidate,
            }
        )
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(m.Path, "home", return_value=home))
            stack.enter_context(patch.object(
                m, "M12_MAIN_SHA256",
                m.sha(source) if active_sha_correct else "a" * 64
            ))
            stack.enter_context(patch.dict(m.MODULE_PINS,
                 {name: m.sha(value) for name, value in modules.items()}))
            fetch = stack.enter_context(
                patch.object(m, "download", side_effect=lambda commit,name: modules[name]))
            load = stack.enter_context(
                patch.object(m, "load_exact_overlay", return_value=fake_overlay))
            restarts = []
            def service(action):
                if action == "restart":
                    restarts.append(action)
                    return first_restart_ok if len(restarts) == 1 else True
                return True
            stack.enter_context(patch.object(m, "service", side_effect=service))
            stack.enter_context(patch.object(m, "ready", return_value=True))
            stack.enter_context(patch.object(m.subprocess, "run",
                return_value=SimpleNamespace(returncode=0 if sudo_ok else 1)))
            stack.enter_context(patch("builtins.input",
                return_value=m.CONSENT if approval else "NEM"))
            if not active_sha_correct:
                with self.assertRaisesRegex(m.M13Stop,
                                          "M13_INSTALLED_MAIN_SHA256_NOT_REVIEWED"):
                    m.activate_once("f" * 40, approved=True)
                self.assertEqual(fetch.call_count, 0)
                self.assertFalse(state.exists())
                return root,state,None,restarts
            if not approval or not sudo_ok:
                with self.assertRaises(m.M13Stop):
                    m.activate_once("f" * 40, approved=True)
                self.assertEqual((root / "fieldwork_mcp.py").read_bytes(),source)
                self.assertFalse(state.exists())
                return root,state,None,restarts
            if not first_restart_ok:
                with self.assertRaisesRegex(m.M13Stop,
                                            "M13_TUNNEL_RESTART_FAILED"):
                    m.activate_once("f" * 40, approved=True)
                self.assertEqual((root / "fieldwork_mcp.py").read_bytes(),source)
                self.assertFalse((root / "linux_telemetry.py").exists())
                self.assertFalse((root / "mcp_linux_telemetry.py").exists())
                self.assertEqual(json.loads(
                    (state / "receipt.json").read_text())["status"],
                    "M13_ROLLED_BACK")
                self.assertEqual(len(restarts), 2)
                return root,state,None,restarts
            result = m.activate_once("f" * 40, approved=True)
            self.assertEqual((root / "fieldwork_mcp.py").read_bytes(), candidate)
            self.assertEqual((root / "linux_telemetry.py").read_bytes(),
                             modules["linux_telemetry.py"])
            self.assertEqual((root / "mcp_linux_telemetry.py").read_bytes(),
                             modules["mcp_linux_telemetry.py"])
            self.assertEqual(len(restarts), 1)
            return root,state,result,restarts

    def test_local_consent_denied_no_changes(self):
        with tempfile.TemporaryDirectory() as td:
            self.scenario(Path(td), approval=False)

    def test_sudo_denied_no_changes(self):
        with tempfile.TemporaryDirectory() as td:
            self.scenario(Path(td), sudo_ok=False)

    def test_sha_drift_denied_before_download(self):
        with tempfile.TemporaryDirectory() as td:
            self.scenario(Path(td), active_sha_correct=False)

    def test_failure_after_write_auto_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            self.scenario(Path(td), first_restart_ok=False)

    def test_single_transaction_produces_backup_and_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root, state, result, restarted = self.scenario(Path(td))
            self.assertEqual(result["status"],
                             "M13_LOCAL_READY_DISCOVERY_PENDING")
            self.assertFalse(result["production_modified"])
            self.assertFalse(result["docker_modified"])
            self.assertFalse(result["new_tunnel_created"])
            self.assertEqual((state / "previous-fieldwork_mcp.py").read_bytes(),
                             b"old M12 deployed main")
            self.assertEqual((state / "receipt.json").stat().st_mode & 0o777,
                             0o600)
            with self.assertRaisesRegex(m.M13Stop,
                                        "M13_PREVIOUS_ATTEMPT_EXISTS"):
                with patch.object(m.Path, "home", return_value=Path(td)):
                    with patch.object(m, "M12_MAIN_SHA256",
                                      m.sha(b"old M12 deployed main")):
                        m.activate_once("f" * 40, approved=True)

    def test_rollback_blocks_unknown_live_source(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root, state = fixture_files(home)
            state.mkdir()
            old = b"old M12 deployed main"
            backup = state / "previous-fieldwork_mcp.py"
            backup.write_bytes(old)
            backup.chmod(0o600)
            active = root / "fieldwork_mcp.py"
            active.write_bytes(b"foreign change")
            data = {"new_mcp_sha256": m.sha(b"candidate")}
            with patch.object(m, "M12_MAIN_SHA256", m.sha(old)):
                with self.assertRaisesRegex(
                        m.M13Stop, "M13_ROLLBACK_SOURCE_CHANGED"):
                    m.rollback(root,state,data)
            self.assertEqual(active.read_bytes(), b"foreign change")

    def test_safe_user_visible_fail_code(self):
        with patch("sys.argv", ["m13", "--commit", "f" * 40,
                                "--activate"]), patch.object(
                m, "activate_once", side_effect=m.M13Stop(
                    "M13_INSTALLED_MAIN_SHA256_NOT_REVIEWED")), patch(
                    "builtins.print") as printed:
            self.assertEqual(m.main(),2)
        printed.assert_called_once_with(
            "M13_STOP=M13_INSTALLED_MAIN_SHA256_NOT_REVIEWED", flush=True)


if __name__ == "__main__":
    unittest.main()
