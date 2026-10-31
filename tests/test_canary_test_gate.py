"""HMAC proof, exact suite receipt and stale stage negative tests."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from updater import canary_test_runner as runner
from updater import canary_test_gate as gate
from updater import canary_stage_inspect as stage
from updater import canary_archive_qualifier as q
from updater import artifact_inbox as inbox

TID = "e" * 32
IMAGE = "fieldwork-canary-test-appliance@sha256:" + "3" * 64
SNAPSHOT = {
    "status": "STAGE_VERIFIED_NOT_TESTED", "transfer_id": TID,
    "base_commit": "4" * 40, "snapshot_tree_sha256": "5" * 64,
}
KEY = b"0123456789abcdef0123456789abcdef"


class TestGate(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("production runner must be non-root")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        stage_root = self.home / inbox.STATE.parent / stage.STAGE_NAME / TID
        stage_root.mkdir(parents=True, mode=0o700)
        deps = {}
        for key, relative in runner.DEPENDENCY_FILES.items():
            blob = (key + "\n").encode()
            path = stage_root / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(blob)
            path.chmod(0o600)
            deps[key] = hashlib.sha256(blob).hexdigest()
        p = self.home / runner.PIN_REL
        p.parent.mkdir(parents=True, mode=0o700)
        p.write_text(json.dumps({
            "schema": 1, "profile": runner.PROFILE, "image": IMAGE,
            "stage_testing_only": True, "locally_approved": True,
            **deps,
        }))
        p.chmod(0o600)
        key = self.home / runner.KEY_REL
        key.write_bytes(KEY)
        key.chmod(0o600)

    def run_mock(self):
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT), \
             patch.object(runner, "_run_docker", return_value=(True, "EXIT_0")):
            result = runner.run(TID)
        self.assertEqual(result["status"], "FULL_TEST_PASS_NOT_DEPLOYED")
        return result

    def report_path(self):
        return self.home / runner.TESTS_REL / TID / "TEST_REPORT.json"

    def test_real_local_hmac_attested_gate(self):
        result = self.run_mock()
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            checked = gate.inspect_tests(TID)
        self.assertEqual(checked["status"], "FULL_TEST_ATTESTED_NOT_DEPLOYED")
        self.assertEqual(checked["completed_suite_count"], len(runner.SUITES))
        self.assertFalse(checked["canary_start_authorized"])
        self.assertFalse(checked["production_modified"])

    def test_modified_pass_without_new_mac_denied(self):
        self.run_mock()
        path = self.report_path()
        data = json.loads(path.read_text())
        data["image"] = "fieldwork-canary-test-appliance@sha256:" + "6" * 64
        path.write_text(json.dumps(data))
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaisesRegex(q.QualificationDenied, "TEST_ATTESTATION_INVALID"):
                gate.inspect_tests(TID)

    def test_missing_suite_denied_even_with_valid_hmac(self):
        self.run_mock()
        path = self.report_path()
        data = json.loads(path.read_text())
        data["completed_suites"].pop()
        data["attestation_hmac_sha256"] = runner.attest(data)
        path.write_text(json.dumps(data))
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaisesRegex(q.QualificationDenied, "MISSING_TEST_SUITES"):
                gate.inspect_tests(TID)

    def test_wrong_order_denied_even_with_valid_hmac(self):
        self.run_mock()
        path = self.report_path()
        data = json.loads(path.read_text())
        data["completed_suites"] = list(reversed(data["completed_suites"]))
        data["attestation_hmac_sha256"] = runner.attest(data)
        path.write_text(json.dumps(data))
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaisesRegex(q.QualificationDenied, "TEST_SUITE_EVIDENCE_DENIED"):
                gate.inspect_tests(TID)

    def test_stale_stage_rejected(self):
        self.run_mock()
        changed = {**SNAPSHOT, "snapshot_tree_sha256": "7" * 64}
        with patch.object(stage, "inspect_stage", return_value=changed):
            with self.assertRaisesRegex(q.QualificationDenied,
                                        "TEST_RECEIPT_STAGE_MISMATCH"):
                gate.inspect_tests(TID)

    def test_pin_change_rejected(self):
        self.run_mock()
        cfg = self.home / runner.PIN_REL
        data = json.loads(cfg.read_text())
        data["image"] = "fieldwork-canary-test-appliance@sha256:" + "a" * 64
        cfg.write_text(json.dumps(data))
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaisesRegex(q.QualificationDenied, "TEST_PROFILE_PIN_MISMATCH"):
                gate.inspect_tests(TID)

    def test_report_not_started_denied(self):
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaises(q.QualificationDenied):
                gate.inspect_tests(TID)

    def test_forged_pass_without_mac_denied(self):
        self.run_mock()
        target = self.report_path()
        data = json.loads(target.read_text())
        data["attestation_hmac_sha256"] = "0" * 64
        target.write_text(json.dumps(data))
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaisesRegex(q.QualificationDenied, "TEST_ATTESTATION_INVALID"):
                gate.inspect_tests(TID)

    def test_root_or_symlink_report_denied(self):
        self.run_mock()
        report = self.report_path()
        backup = report.parent / "hidden"
        report.rename(backup)
        report.symlink_to(backup)
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT):
            with self.assertRaisesRegex(q.QualificationDenied, "TEST_POLICY_FILE_UNSAFE"):
                gate.inspect_tests(TID)


if __name__ == "__main__":
    unittest.main()
