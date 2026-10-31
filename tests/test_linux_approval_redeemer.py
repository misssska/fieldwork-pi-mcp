"""M15-E strictly local ticket redemption. Offline + real AF_UNIX rejection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from updater import linux_approval_redeemer as redeem
from updater import linux_upgrade_gate as gate

NOW = 1793468000
SECRET = b"m15e-test-independent-operator-key-" + b"x" * 32
A = "a" * 64
B = "b" * 64
COMMIT = "c" * 40


class OneShotApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.approved = self.base / "approved"
        self.spent = self.base / "spent"
        self.sockdir = self.base / "socket"
        for p, mode in ((self.approved, 0o700), (self.spent, 0o700),
                        (self.sockdir, 0o710)):
            p.mkdir(mode=mode)
        self.executor = os.geteuid() + 10000
        self.policy = gate.HostPolicy("fieldwork-pi",
                                    frozenset({"fieldwork_mcp.py"}))
        self.request = {
            "protocol": 1, "host_id": "fieldwork-pi", "commit_sha": COMMIT,
            "issued_at": NOW - 5, "expires_at": NOW + 300,
            "files": [{
                "name": "fieldwork_mcp.py", "action": "replace",
                "old_sha256": A, "new_sha256": B,
            }],
        }
        self.plan = gate.validate_plan(
            self.request, self.policy, {"fieldwork_mcp.py": A}, NOW)
        self.approval = gate.issue_local_approval(
            self.plan, local_secret=SECRET, operator_present=True, now=NOW)
        self.ticket = self.approved / (self.plan.plan_sha256 + ".json")
        self.ticket.write_bytes(gate.canon(self.approval))
        self.ticket.chmod(0o600)
        self.server = redeem.LocalRedeemer(
            plan=self.plan, local_secret=SECRET,
            approval_root=self.approved, spent_root=self.spent,
            socket_root=self.sockdir,
            expected_executor_uid=self.executor,
            expected_executor_gid=os.getegid())

    def packet(self, **overrides):
        data = {"protocol": 1, "plan_sha256": self.plan.plan_sha256}
        data.update(overrides)
        return gate.canon(data) + b"\n"

    def call(self, **kwargs):
        return self.server.redeem(
            request=kwargs.pop("request", self.packet()),
            peer_uid=kwargs.pop("peer_uid", self.executor),
            now=kwargs.pop("now", NOW),
            **kwargs)

    def test_success_binds_exact_host_commit_and_plan_but_never_installs(self):
        res = self.call()
        self.assertEqual(res["status"], "LOCAL_APPROVAL_REDEEMED_NOT_EXECUTED")
        self.assertEqual(res["plan_sha256"], self.plan.plan_sha256)
        self.assertEqual(res["commit_sha"], COMMIT)
        self.assertFalse(res["execution_authorized"])
        self.assertFalse(res["publisher_verified"])
        self.assertFalse(res["deployment_performed"])
        self.assertFalse(res["production_modified"])
        spent = list(self.spent.iterdir())
        self.assertEqual([x.name for x in spent], [self.approval["nonce"]])
        self.assertEqual(spent[0].stat().st_mode & 0o777, 0o600)
        body = json.loads(spent[0].read_bytes())
        self.assertEqual(body["plan_sha256"], self.plan.plan_sha256)
        self.assertEqual(body["consumed_at"], NOW)

    def test_replay_denied_even_if_ticket_unchanged(self):
        self.call()
        with self.assertRaisesRegex(redeem.RedemptionDenied,
                                    "REDEEM_NONCE_REPLAY_DENIED"):
            self.call()
        self.assertEqual(len(list(self.spent.iterdir())), 1)

    def test_foreign_peer_denied_before_reading_ticket(self):
        for uid in (0, os.geteuid(), self.executor + 1, -1, True):
            with self.subTest(uid=uid), self.assertRaises(
                    redeem.RedemptionDenied):
                self.call(peer_uid=uid)
        self.assertEqual(list(self.spent.iterdir()), [])

    def test_packet_must_be_exact_canonical_single_line(self):
        for bad in (
            self.packet(plan_sha256="f" * 64),
            self.packet(protocol=2),
            self.packet(extra="shell"),
            b'{"plan_sha256":"' + self.plan.plan_sha256.encode() +
            b'","protocol":1}',  # newline absent
            self.packet() + b"\n",
            b" " + self.packet(),
            b"x" * 260 + b"\n",
            b'{"protocol":1,"protocol":1,"plan_sha256":"' +
            self.plan.plan_sha256.encode() + b'"}\n',
        ):
            with self.subTest(body=bad[:25]), self.assertRaises(
                    redeem.RedemptionDenied):
                self.call(request=bad)
        self.assertEqual(list(self.spent.iterdir()), [])

    def test_forged_hmac_invalid_and_does_not_spend(self):
        changed = dict(self.approval)
        changed["mac"] = "f" * 64
        self.ticket.write_bytes(gate.canon(changed))
        with self.assertRaises(gate.UpgradeDenied):
            self.call()
        self.assertEqual(list(self.spent.iterdir()), [])

    def test_foreign_ticket_mode_and_symlink_denied(self):
        self.ticket.chmod(0o644)
        with self.assertRaisesRegex(redeem.RedemptionDenied,
                                    "REDEEM_TICKET_OWNER_MODE_DENIED"):
            self.call()
        self.ticket.chmod(0o600)
        other = self.base / "other.json"
        other.write_bytes(self.ticket.read_bytes())
        self.ticket.unlink()
        self.ticket.symlink_to(other)
        with self.assertRaises(redeem.RedemptionDenied):
            self.call()

    def test_expiry_and_mismatched_plan_deny_without_spending(self):
        with self.assertRaises(gate.UpgradeDenied):
            self.call(now=NOW + 301)
        with self.assertRaises(redeem.RedemptionDenied):
            self.call(request=self.packet(plan_sha256="e" * 64))
        self.assertEqual(list(self.spent.iterdir()), [])

    def test_private_directory_owner_mode_required(self):
        self.spent.chmod(0o755)
        with self.assertRaises(redeem.RedemptionDenied):
            self.call()
        self.spent.chmod(0o700)
        self.approved.chmod(0o755)
        with self.assertRaises(redeem.RedemptionDenied):
            self.call()
        self.approved.chmod(0o700)
        self.sockdir.chmod(0o700)
        with self.assertRaises(redeem.RedemptionDenied):
            redeem.LocalRedeemer(
                plan=self.plan, local_secret=SECRET,
                approval_root=self.approved, spent_root=self.spent,
                socket_root=self.sockdir, expected_executor_uid=self.executor,
                expected_executor_gid=os.getegid())

    def test_no_duplicate_second_listener_and_no_unlink_of_socket(self):
        # Real Unix peer is the test process itself; it MUST fail because
        # only a different, independently configured executor UID is valid.
        worker = threading.Thread(target=self.server.serve_one, daemon=True)
        worker.start()
        path = self.sockdir / "handoff.sock"
        for _ in range(100):
            if path.exists():
                break
            time.sleep(0.01)
        else:
            self.fail("Unix listener not ready")
        with self.assertRaisesRegex(redeem.RedemptionDenied,
                                    "REDEEM_SOCKET_ALREADY_EXISTS"):
            self.server.serve_one()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(str(path))
            conn.sendall(self.packet())
            data = conn.recv(1024)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(json.loads(data)["status"],
                         "LOCAL_APPROVAL_REDEMPTION_DENIED")
        self.assertTrue(path.exists())
        self.assertEqual(list(self.spent.iterdir()), [])

    def test_group_mismatch_and_equal_uid_cannot_create_server(self):
        with self.assertRaisesRegex(redeem.RedemptionDenied,
                                    "REDEEM_EXECUTOR_IDENTITY_DENIED"):
            redeem.LocalRedeemer(
                plan=self.plan, local_secret=SECRET,
                approval_root=self.approved, spent_root=self.spent,
                socket_root=self.sockdir,
                expected_executor_uid=os.geteuid(),
                expected_executor_gid=os.getegid())
        with self.assertRaisesRegex(redeem.RedemptionDenied,
                                    "REDEEM_EXECUTOR_IDENTITY_DENIED"):
            redeem.LocalRedeemer(
                plan=self.plan, local_secret=SECRET,
                approval_root=self.approved, spent_root=self.spent,
                socket_root=self.sockdir,
                expected_executor_uid=self.executor,
                expected_executor_gid=os.getegid() + 1)

    def test_no_shell_docker_service_or_program_install_exports(self):
        from inspect import getsource
        s = getsource(redeem)
        for pattern in ("import subprocess", "subprocess.run(", "os.system(",
                        "docker run", "shell=True", "exec(", "eval(",
                        "os.unlink(", "os.remove("):
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, s)


if __name__ == "__main__":
    unittest.main()
