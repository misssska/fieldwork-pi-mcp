"""M14 private local update-inbox tests, no network or host changes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import linux_upgrade_gate as g
from updater import linux_upgrade_inbox as i

NOW = 1793465000
ACTIVE = {"linux_telemetry.py": None, "fieldwork_mcp.py": "a" * 64}


def policy(host="fieldwork-pi"):
    return g.HostPolicy(
        host_id=host,
        allowed_modules=frozenset(ACTIVE),
    )


def request(host="fieldwork-pi"):
    return {
        "protocol": 1,
        "host_id": host,
        "commit_sha": "f" * 40,
        "issued_at": NOW - 15,
        "expires_at": NOW + 90,
        "files": [
            {"name": "fieldwork_mcp.py", "action": "replace",
             "old_sha256": "a" * 64, "new_sha256": "b" * 64},
            {"name": "linux_telemetry.py", "action": "create",
             "old_sha256": None, "new_sha256": "c" * 64},
        ],
    }


class ImmutableInboxTests(unittest.TestCase):
    def setup(self, root):
        root.chmod(0o700)
        return i.ProposalInbox(root=root, policy=policy())

    def test_submit_only_stages_metadata_never_runs_or_approves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inbox = self.setup(root)
            result = inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            self.assertEqual(result["status"], "UPGRADE_REQUEST_STAGED")
            self.assertFalse(result["activation_authorized"])
            self.assertFalse(result["source_bytes_written"])
            path = root / (result["plan_sha256"] + ".json")
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(list(root.iterdir())), 1)
            stored = json.loads(path.read_text())
            self.assertEqual(stored["host_id"], "fieldwork-pi")
            self.assertNotIn("mac", stored)
            self.assertNotIn("secret", path.read_text())
            self.assertNotIn("/opt", path.read_text())

    def test_idempotent_same_plan_is_exactly_one_file(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = self.setup(Path(td))
            first = inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            again = inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            self.assertEqual(again["status"], "UPGRADE_REQUEST_ALREADY_STAGED")
            self.assertEqual(first["plan_sha256"], again["plan_sha256"])
            self.assertEqual(len(list(Path(td).iterdir())), 1)

    def test_status_readback_still_requires_active_source_and_expiry(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = self.setup(Path(td))
            h = inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            result = inbox.status(h["plan_sha256"],
                                  active_hashes=ACTIVE, now=NOW)
            self.assertEqual(result["status"],
                             "UPGRADE_REQUEST_AWAITING_LOCAL_APPROVAL")
            self.assertFalse(result["activation_authorized"])
            with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_EXPIRED_OR_CLOCK_INVALID"):
                inbox.status(h["plan_sha256"],
                             active_hashes=ACTIVE, now=NOW+100)
            with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_ACTIVE_SOURCE_MISMATCH"):
                inbox.status(h["plan_sha256"],
                             active_hashes={**ACTIVE,
                                            "fieldwork_mcp.py": "9" * 64},
                             now=NOW)

    def test_private_owned_directory_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inbox = self.setup(root)
            root.chmod(0o755)
            with self.assertRaisesRegex(i.InboxDenied,
                                        "UPGRADE_INBOX_PERMISSIONS_DENIED"):
                inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            self.assertEqual(list(root.iterdir()), [])

    def test_cross_host_denied(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = self.setup(Path(td))
            with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_HOST_MISMATCH"):
                inbox.submit(request("orange-pi"), active_hashes=ACTIVE, now=NOW)
            self.assertEqual(len(list(Path(td).iterdir())), 0)

    def test_symlink_manifest_and_unsafe_filename_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inbox = self.setup(root)
            manifest = request()
            plan = g.validate_plan(manifest, policy(), ACTIVE, NOW)
            outside = root / "outside"
            outside.write_bytes(b"sensitive")
            path = root / (plan.plan_sha256 + ".json")
            path.symlink_to(outside)
            with self.assertRaisesRegex(i.InboxDenied,
                                        "UPGRADE_TARGET_SYMLINK_DENIED"):
                inbox.submit(manifest, active_hashes=ACTIVE, now=NOW)
            self.assertEqual(outside.read_bytes(), b"sensitive")
            with self.assertRaisesRegex(i.InboxDenied, "UPGRADE_FILENAME_DENIED"):
                i._read_exact(root, "../etc/passwd")

    def test_manifest_is_immutable_and_bad_tamper_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inbox = self.setup(root)
            r = inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            path = root / (r["plan_sha256"] + ".json")
            altered = request()
            altered["commit_sha"] = "e" * 40
            path.write_bytes(g.canon(altered))
            with self.assertRaisesRegex(i.InboxDenied,
                                        "UPGRADE_REPLAY_CONTENT_MISMATCH"):
                inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            with self.assertRaisesRegex(i.InboxDenied,
                                        "UPGRADE_STORED_DIGEST_MISMATCH"):
                inbox.status(r["plan_sha256"], active_hashes=ACTIVE, now=NOW)

    def test_malformed_json_does_not_leak_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inbox = self.setup(root)
            r = inbox.submit(request(), active_hashes=ACTIVE, now=NOW)
            path = root / (r["plan_sha256"] + ".json")
            path.write_bytes(b"{Invalid")
            with self.assertRaisesRegex(i.InboxDenied,
                                        "UPGRADE_STORED_MANIFEST_INVALID"):
                inbox.status(r["plan_sha256"], active_hashes=ACTIVE, now=NOW)

    def test_no_shell_privilege_or_docker_lifecycle_code(self):
        import inspect
        src = inspect.getsource(i)
        for forbidden in ("import subprocess", "os.system(", "subprocess.run(",
                          "docker stop", "docker rm", "systemctl restart",
                          "shell=True", "sudo -n", "shutil.rmtree("):
            self.assertNotIn(forbidden, src)

    def test_caller_cannot_select_output_directory_from_request(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = self.setup(Path(td))
            malicious = request()
            malicious["root"] = "/etc"
            with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_FIELDS_DENIED"):
                inbox.submit(malicious, active_hashes=ACTIVE, now=NOW)
            self.assertEqual(len(list(Path(td).iterdir())), 0)


if __name__ == "__main__":
    unittest.main()
