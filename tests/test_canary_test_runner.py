"""Negative-first offline tests for a fixed, networkless canary test executor.

Every external Docker call is intercepted. These tests are NOT evidence that a
test-appliance image was built on the Pi or that FieldWork tests ran on the Pi.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import canary_test_runner as runner
from updater import canary_stage_inspect as stage
from updater import canary_archive_qualifier as q
from updater import artifact_inbox as inbox

TID = "6" * 32
IMAGE = "fieldwork-canary-test-appliance@sha256:" + "a" * 64
SNAPSHOT = {
    "status": "STAGE_VERIFIED_NOT_TESTED",
    "transfer_id": TID, "snapshot_tree_sha256": "b" * 64,
    "base_commit": "c" * 40,
    "snapshot_file_count": 6,
    "snapshot_total_bytes": 3500,
}


class TestRunnerTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Pi executor is explicitly non-root")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.src = self.home / inbox.STATE.parent / stage.STAGE_NAME / TID
        self.src.mkdir(parents=True, mode=0o700)
        deps = {}
        for key, relative in runner.DEPENDENCY_FILES.items():
            blob = (key + "\n").encode()
            path = self.src / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(blob)
            path.chmod(0o600)
            deps[key] = hashlib.sha256(blob).hexdigest()
        pin = self.home / runner.PIN_REL
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text(json.dumps({
            "schema": 1, "profile": runner.PROFILE, "image": IMAGE,
            "stage_testing_only": True, "locally_approved": True,
            **deps,
        }))
        pin.chmod(0o600)
        self.pin = pin
        key = self.home / runner.KEY_REL
        key.write_bytes(b"opaque-local-attestation-key-001")
        self.assertEqual(key.stat().st_size, 32)
        key.chmod(0o600)

    def test_local_policy_needs_exact_pinned_image(self):
        self.assertEqual(runner._config()["image"], IMAGE)
        for img in ("fieldwork:latest", "ubuntu:latest", "my/image@sha256:" + "a" * 64,
                    "fieldwork-canary-test-appliance@sha256:bad"):
            data = json.loads(self.pin.read_text())
            data["image"] = img
            self.pin.write_text(json.dumps(data))
            with self.subTest(img=img), self.assertRaisesRegex(
                    q.QualificationDenied, "TEST_IMAGE_NOT_LOCALLY_APPROVED"):
                runner._config()
        data["image"] = IMAGE
        data["locally_approved"] = False
        self.pin.write_text(json.dumps(data))
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "TEST_IMAGE_NOT_LOCALLY_APPROVED"):
            runner._config()

    def test_world_readable_pin_denied(self):
        self.pin.chmod(0o644)
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "TEST_POLICY_OWNER_OR_PERMISSIONS_DENIED"):
            runner._config()

    def test_symlink_pin_denied(self):
        self.pin.rename(self.home / "pin-backup.json")
        self.pin.symlink_to(self.home / "pin-backup.json")
        with self.assertRaisesRegex(q.QualificationDenied, "TEST_POLICY_FILE_UNSAFE"):
            runner._config()

    def test_no_shell_or_network_or_docker_socket(self):
        cmd = runner._command(TID, "frontend-vitest", IMAGE)
        self.assertEqual(cmd[0:3], ["docker", "run", "--rm"])
        self.assertIn("--network=none", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("--cap-drop=ALL", cmd)
        self.assertIn("--security-opt=no-new-privileges", cmd)
        self.assertIn("--pull=never", cmd)
        self.assertIn("type=bind,source=" + str(self.src) + ",target=/source,readonly",
                      cmd)
        self.assertEqual(cmd[-2:], [IMAGE, "frontend-vitest"])
        as_string = " ".join(cmd)
        for forbidden in ("/opt/fieldwork", "docker.sock", "--privileged",
                          "--network=host", "--volume=/", "sh -c", "bash -c"):
            self.assertNotIn(forbidden, as_string)

    def test_subprocess_execution_denies_altered_docker_argv(self):
        allowed = runner._command(TID, "frontend-lint", IMAGE)
        for mutated in (
            allowed + ["--privileged"],
            allowed[:3] + ["--network=host"] + allowed[3:],
            [*allowed[:-2], "ubuntu:latest", "frontend-lint"],
            [*allowed[:-1], "backend-pytest-postgres"],
        ):
            with self.subTest(mutated=mutated), patch.object(
                    runner.subprocess, "run") as proc:
                with self.assertRaises(q.QualificationDenied):
                    runner._run_docker(mutated, runner.TIME_LIMIT["frontend-lint"])
                proc.assert_not_called()

    def test_timeout_removes_only_own_container(self):
        from subprocess import CompletedProcess, TimeoutExpired
        argv = runner._command(TID, "frontend-lint", IMAGE)
        with patch.object(runner.subprocess, "run", side_effect=[
            TimeoutExpired(argv, 180),
            CompletedProcess(["docker", "rm", "-f"], 0)
        ]) as proc:
            passed, outcome = runner._run_docker(argv, 180)
        self.assertFalse(passed)
        self.assertEqual(outcome, "TIMEOUT_CONTAINER_REMOVED")
        self.assertEqual(proc.call_count, 2)
        self.assertEqual(proc.call_args.args[0], [
            "docker", "rm", "-f", "fw-canary-" + TID + "-1"])

    def test_timeout_cleanup_failure_does_not_report_pass(self):
        from subprocess import CompletedProcess, TimeoutExpired
        argv = runner._command(TID, "frontend-lint", IMAGE)
        with patch.object(runner.subprocess, "run", side_effect=[
            TimeoutExpired(argv, 180),
            CompletedProcess(["docker", "rm", "-f"], 1)
        ]):
            passed, outcome = runner._run_docker(argv, 180)
        self.assertFalse(passed)
        self.assertEqual(outcome, "TIMEOUT_CLEANUP_NOT_CONFIRMED")

    def test_arbitrary_suite_denied(self):
        for suite in ("shell", "docker compose up", "../etc/shadow", "backend-migrate-prod"):
            with self.assertRaisesRegex(q.QualificationDenied,
                                        "UNKNOWN_TEST_SUITE"):
                runner._command(TID, suite, IMAGE)

    def test_all_five_test_phases_write_durable_pass_receipt(self):
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT) as gate, \
             patch.object(runner, "_run_docker", return_value=(True, "EXIT_0")) as exec_:
            result = runner.run(TID)
        self.assertEqual(result["status"], "FULL_TEST_PASS_NOT_DEPLOYED")
        self.assertTrue(result["all_suites_pass"])
        self.assertEqual([r["suite"] for r in result["completed_suites"]],
                         list(runner.SUITES))
        self.assertEqual(exec_.call_count, 5)
        self.assertEqual(gate.call_count, 11)
        self.assertFalse(result["production_modified"])
        self.assertFalse(result["canary_started"])
        target = self.home / runner.TESTS_REL / TID / "TEST_REPORT.json"
        self.assertEqual(json.loads(target.read_text()), result)

    def test_failed_test_blocks_remaining_phases(self):
        def execute(cmd, timeout):
            if cmd[-1] == "frontend-lint":
                return (False, "NONZERO_EXIT")
            return (True, "EXIT_0")
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT), \
             patch.object(runner, "_run_docker", side_effect=execute) as exec_:
            result = runner.run(TID)
        self.assertEqual(result["status"], "TEST_FAILED")
        self.assertFalse(result["all_suites_pass"])
        self.assertEqual(exec_.call_count, 2)
        self.assertEqual(result["completed_suites"][-1]["suite"], "frontend-lint")

    def test_changed_source_stops_next_test(self):
        updated = dict(SNAPSHOT)
        updated["snapshot_tree_sha256"] = "e" * 64
        snapshots = [SNAPSHOT, SNAPSHOT, SNAPSHOT, updated]
        with patch.object(stage, "inspect_stage", side_effect=snapshots), \
             patch.object(runner, "_run_docker", return_value=(True, "EXIT_0")) as exec_:
            result = runner.run(TID)
        self.assertEqual(result["status"], "TEST_FAILED")
        self.assertEqual(len(result["completed_suites"]), 2)
        self.assertEqual(exec_.call_count, 1)
        self.assertEqual(result["completed_suites"][-1]["outcome"],
                         "STAGE_INTEGRITY_OR_POLICY_DENIED")

    def test_preflight_denied_before_docker(self):
        with patch.object(stage, "inspect_stage",
                          side_effect=q.QualificationDenied("MISSING_STAGE")), \
             patch.object(runner, "_run_docker") as exec_:
            with self.assertRaises(q.QualificationDenied):
                runner.run(TID)
            exec_.assert_not_called()

    def test_replay_does_not_execute_twice(self):
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT), \
             patch.object(runner, "_run_docker", return_value=(True, "EXIT_0")) as exec_:
            runner.run(TID)
            with self.assertRaisesRegex(q.QualificationDenied, "TEST_ALREADY_ATTEMPTED"):
                runner.run(TID)
            self.assertEqual(exec_.call_count, 5)

    def test_dependency_drift_denied_before_any_docker(self):
        dep = self.src / runner.DEPENDENCY_FILES["frontend_lock_sha256"]
        dep.write_bytes(b"new dependency without appliance rebuild")
        with patch.object(stage, "inspect_stage", return_value=SNAPSHOT), \
             patch.object(runner, "_run_docker") as exec_:
            with self.assertRaisesRegex(q.QualificationDenied,
                                        "TEST_DEPENDENCIES_NOT_MATCHING_APPROVED_IMAGE"):
                runner.run(TID)
            exec_.assert_not_called()
        self.assertFalse((self.home / runner.TESTS_REL / TID).exists())

    def test_missing_attestation_key_denied_before_test_execution(self):
        (self.home / runner.KEY_REL).unlink()
        with patch.object(stage, "inspect_stage") as gate, \
             patch.object(runner, "_run_docker") as exec_:
            with self.assertRaises(q.QualificationDenied):
                runner.run(TID)
            gate.assert_not_called()
            exec_.assert_not_called()

    def test_policy_fails_without_any_execution(self):
        self.pin.unlink()
        with patch.object(stage, "inspect_stage") as gate, \
             patch.object(runner, "_run_docker") as exec_:
            with self.assertRaises(q.QualificationDenied):
                runner.run(TID)
            gate.assert_not_called()
            exec_.assert_not_called()


if __name__ == "__main__":
    unittest.main()
