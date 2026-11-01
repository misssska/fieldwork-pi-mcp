"""M14 offline policy / local approval: denial-first, no Pi or network."""
from __future__ import annotations
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from updater import linux_upgrade_gate as g

NOW = 1793465000
OLD = "a" * 64
NEW = "b" * 64
N2 = "c" * 64
SOURCE_COMMIT = "d" * 40
SECRET = b"independent-local-only-secret-for-tests" + b"_more_entropy"


def local_policy():
    return g.HostPolicy(
        host_id="fieldwork-pi",
        allowed_modules=frozenset({"fieldwork_mcp.py", "linux_telemetry.py",
                                  "mcp_linux_telemetry.py", "safe_module.py"}),
        locked_modules=frozenset({"safe_module.py"}),
    )


def fixture():
    return {
        "protocol": 1,
        "host_id": "fieldwork-pi",
        "commit_sha": SOURCE_COMMIT,
        "issued_at": NOW - 30,
        "expires_at": NOW + 120,
        "files": [
            {"name": "fieldwork_mcp.py", "action": "replace",
             "old_sha256": OLD, "new_sha256": NEW},
            {"name": "linux_telemetry.py", "action": "create",
             "old_sha256": None, "new_sha256": N2},
        ],
    }


ACTIVE = {"fieldwork_mcp.py": OLD, "linux_telemetry.py": None,
          "mcp_linux_telemetry.py": None, "safe_module.py": "e" * 64}


class PolicyTests(unittest.TestCase):
    def validate(self, data=None, *, now=NOW, active=ACTIVE):
        return g.validate_plan(
            data if data is not None else fixture(), local_policy(),
            active, now)

    def test_accepts_exact_ordered_bound_plan(self):
        plan = self.validate()
        self.assertEqual(plan.host_id, "fieldwork-pi")
        self.assertEqual(len(plan.plan_sha256), 64)
        self.assertEqual(len(plan.files), 2)
        self.assertEqual(plan.scope, "private_mcp_owned_files_only")
        display = g.approval_display(plan)
        self.assertEqual(display["status"], "LOCAL_REVIEW_REQUIRED")
        self.assertFalse(display["activation_authorized"])
        self.assertNotIn("secret", str(display).lower())
        self.assertNotIn("/opt/fieldwork", str(display))
        self.assertEqual(display["target_modules"],
                         ["fieldwork_mcp.py", "linux_telemetry.py"])

    def test_tampering_any_material_field_changes_digest_or_denies(self):
        original = self.validate()
        changed = fixture()
        changed["commit_sha"] = "e" * 40
        self.assertNotEqual(original.plan_sha256, self.validate(changed).plan_sha256)
        changed = fixture()
        changed["expires_at"] -= 1
        self.assertNotEqual(original.plan_sha256, self.validate(changed).plan_sha256)
        changed = fixture()
        changed["files"][0]["new_sha256"] = "f" * 64
        self.assertNotEqual(original.plan_sha256, self.validate(changed).plan_sha256)

    def test_cross_host_and_cross_platform_denied(self):
        changed = fixture()
        changed["host_id"] = "orange-pi"
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_HOST_MISMATCH"):
            self.validate(changed)

    def test_no_command_path_or_extra_fields_allowed(self):
        bads = [
            {"shell": "rm -rf /"},
            {"process": "systemctl restart something"},
            {"policy": {"allow_all": True}},
            {"another": "ignored"},
        ]
        for unwanted in bads:
            data = fixture()
            data.update(unwanted)
            with self.subTest(data=unwanted), self.assertRaisesRegex(
                    g.UpgradeDenied, "PLAN_FIELDS_DENIED"):
                self.validate(data)

    def test_no_path_traversal_or_service_or_policy_mutation(self):
        for name in (
            "../../fieldwork_mcp.py", "/opt/fieldwork/server/app/main.py",
            ".env", "docker-compose.yml", "updater.py",
            "safe_module.py", "fieldwork_mcp.PY", "a\\b.py",
        ):
            data = fixture()
            data["files"][0]["name"] = name
            with self.subTest(name=name), self.assertRaisesRegex(
                    g.UpgradeDenied, "PLAN_FILE_NOT_ALLOWED"):
                self.validate(data)

    def test_file_set_must_be_unique_and_sorted(self):
        data = fixture()
        data["files"].reverse()
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_FILES_NOT_CANONICALLY_ORDERED"):
            self.validate(data)
        data = fixture()
        data["files"].append(copy.deepcopy(data["files"][0]))
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_FILE_NOT_ALLOWED"):
            self.validate(data)

    def test_rejects_missing_extra_or_bad_file_fields(self):
        for bad in (
            {"name": "fieldwork_mcp.py"},
            {"name": "fieldwork_mcp.py", "action": "replace",
             "new_sha256": NEW, "old_sha256": OLD, "extra": "X"},
        ):
            data = fixture()
            data["files"][0] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(
                    g.UpgradeDenied, "PLAN_FILE_SCHEMA_DENIED"):
                self.validate(data)

    def test_create_and_replace_require_exact_installed_byte_hash(self):
        bad = fixture()
        bad["files"][0]["old_sha256"] = "f" * 64
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_ACTIVE_SOURCE_MISMATCH"):
            self.validate(bad)
        bad = fixture()
        bad["files"][0]["new_sha256"] = OLD
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_ACTIVE_SOURCE_MISMATCH"):
            self.validate(bad)
        bad = fixture()
        bad["files"][1]["old_sha256"] = OLD
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_CREATE_NOT_EMPTY"):
            self.validate(bad)
        bad = fixture()
        with self.assertRaisesRegex(g.UpgradeDenied, "PLAN_CREATE_NOT_EMPTY"):
            self.validate(bad, active={**ACTIVE, "linux_telemetry.py": OLD})

    def test_stale_skewed_and_unbounded_lease_denied(self):
        for issued, expires, now in (
            (NOW - 5000, NOW + 10, NOW),
            (NOW + 1, NOW + 100, NOW),
            (NOW - 30, NOW, NOW),
            (NOW - 30, NOW + 4000, NOW),
            (True, NOW + 120, NOW),
            (NOW - 30, False, NOW),
        ):
            data = fixture()
            data["issued_at"] = issued
            data["expires_at"] = expires
            with self.subTest(case=(issued, expires, now)), self.assertRaisesRegex(
                    g.UpgradeDenied, "PLAN_EXPIRED_OR_CLOCK_INVALID"):
                self.validate(data, now=now)

    def test_json_nan_oversize_and_cycle_denied(self):
        for item in (float("nan"), float("inf"), b"abc"):
            with self.assertRaisesRegex(g.UpgradeDenied, "UPGRADE_JSON_INVALID"):
                g.canon({"bad": item})
        with self.assertRaisesRegex(g.UpgradeDenied, "UPGRADE_REQUEST_TOO_LARGE"):
            g.canon({"big": "x" * 17000})

    def test_policy_rejects_unsafe_local_config(self):
        for kwargs in (
            {"host_id": "../pi", "allowed_modules": frozenset({"a.py"})},
            {"host_id": "fieldwork-pi", "allowed_modules": frozenset({"../foo"})},
            {"host_id": "fieldwork-pi", "allowed_modules": {"a.py"}},
            {"host_id": "fieldwork-pi",
             "allowed_modules": frozenset({"a.py"}), "locked_modules": frozenset({"x.py"})},
        ):
            with self.subTest(value=kwargs), self.assertRaises(g.UpgradeDenied):
                g.HostPolicy(**kwargs)


class LocalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.plan = g.validate_plan(fixture(), local_policy(), ACTIVE, NOW)

    def approve(self):
        with patch.object(g.secrets, "token_hex", return_value="e" * 32):
            return g.issue_local_approval(
                self.plan, local_secret=SECRET, operator_present=True,
                now=NOW)

    def verify(self, approval, *, plan=None, spent=frozenset(), now=NOW):
        return g.verify_local_approval(
            plan if plan is not None else self.plan, approval,
            local_secret=SECRET, now=now, spent_nonces=spent)

    def test_real_hmac_bound_to_plan_and_host(self):
        auth = self.approve()
        self.assertEqual(auth["plan_sha256"], self.plan.plan_sha256)
        self.assertEqual(auth["host_id"], "fieldwork-pi")
        self.assertEqual(self.verify(auth), "e" * 32)
        self.assertNotIn(SECRET.decode(), str(auth))

    def test_remote_proposal_never_grants_authorization(self):
        result = g.approval_display(self.plan)
        self.assertFalse(result["activation_authorized"])
        self.assertNotIn("mac", result)
        self.assertNotIn("nonce", result)

    def test_no_operator_present_fails_closed(self):
        with self.assertRaisesRegex(g.UpgradeDenied, "LOCAL_APPROVAL_NOT_GIVEN"):
            g.issue_local_approval(self.plan, local_secret=SECRET,
                                   operator_present=False, now=NOW)

    def test_secret_too_short_denied(self):
        with self.assertRaisesRegex(g.UpgradeDenied, "LOCAL_APPROVAL_KEY_INVALID"):
            g.issue_local_approval(self.plan, local_secret=b"short",
                                   operator_present=True, now=NOW)

    def test_tampered_signature_field_or_commit_denied(self):
        auth = self.approve()
        modified = copy.deepcopy(auth)
        modified["nonce"] = "f" * 32
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_MAC_DENIED"):
            self.verify(modified)
        modified = copy.deepcopy(auth)
        modified["mac"] = "a" * 64
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_MAC_DENIED"):
            self.verify(modified)
        plan = g.validate_plan({**fixture(), "commit_sha": "b" * 40},
                               local_policy(), ACTIVE, NOW)
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_PLAN_MISMATCH"):
            self.verify(auth, plan=plan)

    def test_cross_host_and_extra_fields_denied(self):
        auth = self.approve()
        auth["host_id"] = "orange-pi"
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_PLAN_MISMATCH"):
            self.verify(auth)
        auth = self.approve()
        auth["scope"] = "/"
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_SCHEMA_DENIED"):
            self.verify(auth)

    def test_expired_and_replayed_nonce_denied(self):
        auth = self.approve()
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_REPLAY_DENIED"):
            self.verify(auth, spent=frozenset({"e" * 32}))
        with self.assertRaisesRegex(g.UpgradeDenied, "APPROVAL_EXPIRED_OR_CLOCK_INVALID"):
            self.verify(auth, now=auth["expires_at"])

    def test_expired_plan_denied_at_approval(self):
        with self.assertRaisesRegex(g.UpgradeDenied, "LOCAL_APPROVAL_EXPIRED"):
            g.issue_local_approval(self.plan, local_secret=SECRET,
                                   operator_present=True, now=self.plan.expires_at)

    def test_no_unsafe_automation_actions_or_remote_approve_route(self):
        import inspect
        text = inspect.getsource(g)
        for forbidden in ("import subprocess", "subprocess.run(", "os.system(",
                          "sudo -n", "docker stop", "systemctl restart",
                          ".unlink(", ".write_bytes(", "shell=True"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
