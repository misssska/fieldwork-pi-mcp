"""Fail-closed evidence-chain tests; NO real Git, Docker or Pi operations."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from updater import canary_readiness_gate as sut

TID = "4" * 32
ARCHIVE = "a" * 64
COMMIT = "b" * 40
PLAN = "c" * 64
TREE = "d" * 64
CHANGED = ["frontend/src/App.tsx"]


class ReadinessGateTests(unittest.TestCase):
    def setUp(self):
        self.transfer = {
            "status": "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED",
            "transfer_id": TID, "artifact_sha256": ARCHIVE,
            "base_commit": COMMIT,
        }
        self.base = {
            "status": "RELEASE_PREFLIGHT_PASS_NOT_TESTED_NOT_STAGED",
            "transfer_id": TID, "archive_sha256": ARCHIVE,
            "base_commit": COMMIT, "overlay_plan_sha256": PLAN,
            "changed_paths": CHANGED,
            "deployment_authorized": False, "production_modified": False,
        }
        self.stage = {
            "status": "STAGE_VERIFIED_NOT_TESTED", "transfer_id": TID,
            "base_commit": COMMIT, "snapshot_tree_sha256": TREE,
            "production_modified": False,
        }
        self.receipt = {
            "schema": 1, "status": "STAGE_MATERIALIZED_NOT_TESTED",
            "transfer_id": TID, "archive_sha256": ARCHIVE,
            "base_commit": COMMIT, "overlay_plan_sha256": PLAN,
            "changed_paths": CHANGED, "snapshot_tree_sha256": TREE,
            "snapshot_file_count": 1, "snapshot_total_bytes": 10,
            "tests_run": False, "canary_started": False,
            "production_modified": False,
        }
        self.attested = {
            "status": "FULL_TEST_ATTESTED_NOT_DEPLOYED",
            "transfer_id": TID, "base_commit": COMMIT,
            "snapshot_tree_sha256": TREE, "completed_suite_count": 5,
            "canary_start_authorized": False, "production_modified": False,
        }
        def begin(obj, name, value):
            p = patch.object(obj, name, return_value=value)
            mock = p.start()
            self.addCleanup(p.stop)
            return mock
        self.qualify = begin(sut.q, "qualify_transfer", self.transfer)
        self.preflight = begin(sut.preflight, "preflight_transfer", self.base)
        self.inspect_stage = begin(sut.stage, "inspect_stage", self.stage)
        self.read_receipt = begin(sut.stage, "_own_file",
                                  json.dumps(self.receipt).encode())
        self.tests = begin(sut.gate, "inspect_tests", self.attested)
        self.forbidden = begin(sut.runner, "run", None)

    def assertBlocked(self, at, completed):
        result = sut.inspect(TID)
        self.assertEqual(result["status"], "READINESS_BLOCKED")
        self.assertEqual(result["blocked_at"], at)
        self.assertEqual(result["completed_gates"], completed)
        self.assertFalse(result["canary_start_authorized"])
        self.assertFalse(result["deployment_authorized"])
        self.assertFalse(result["production_modified"])
        self.forbidden.assert_not_called()

    def test_complete_evidence_is_explicitly_non_deployable(self):
        result = sut.inspect(TID)
        self.assertEqual(result["status"],
                         "READINESS_EVIDENCE_COMPLETE_NOT_DEPLOYABLE")
        self.assertEqual(result["completed_gates"], list((
            sut.TRANSFER, sut.BASE, sut.STAGE, sut.TESTS)))
        self.assertIsNone(result["blocked_at"])
        self.assertEqual(result["base_commit"], COMMIT)
        self.assertEqual(result["artifact_sha256"], ARCHIVE)
        self.assertEqual(result["snapshot_tree_sha256"], TREE)
        self.assertFalse(result["deployment_authorized"])
        self.assertFalse(result["canary_start_authorized"])
        self.forbidden.assert_not_called()
        self.assertEqual(self.inspect_stage.call_count, 2)

    def test_invalid_transfer_id_denied_before_any_fetch(self):
        with self.assertRaises(Exception):
            sut.inspect("../bad")
        self.qualify.assert_not_called()
        self.forbidden.assert_not_called()

    def test_unqualified_transfer_stops_immediately(self):
        self.transfer["status"] = "VERIFIED"
        self.assertBlocked(sut.TRANSFER, [])
        self.preflight.assert_not_called()

    def test_transfer_sha_invalid_stops_immediately(self):
        self.transfer["artifact_sha256"] = "bad"
        self.assertBlocked(sut.TRANSFER, [])

    def test_transfer_base_is_synthetic_but_valid_shape(self):
        self.transfer["base_commit"] = "z" * 40
        self.assertBlocked(sut.TRANSFER, [])

    def test_private_base_missing(self):
        self.preflight.side_effect = FileNotFoundError("private internal path")
        self.assertBlocked(sut.BASE, [sut.TRANSFER])
        self.inspect_stage.assert_not_called()

    def test_base_archive_mismatch(self):
        self.base["archive_sha256"] = "e" * 64
        self.assertBlocked(sut.BASE, [sut.TRANSFER])

    def test_base_commit_mismatch(self):
        self.base["base_commit"] = "f" * 40
        self.assertBlocked(sut.BASE, [sut.TRANSFER])

    def test_base_not_qualified(self):
        self.base["status"] = "FULL_TEST_PASS"
        self.assertBlocked(sut.BASE, [sut.TRANSFER])

    def test_base_false_permission_is_mandatory(self):
        self.base["deployment_authorized"] = True
        self.assertBlocked(sut.BASE, [sut.TRANSFER])

    def test_stage_missing_or_incomplete(self):
        self.inspect_stage.side_effect = FileNotFoundError("stage")
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])
        self.tests.assert_not_called()

    def test_stage_tree_hash_mismatch(self):
        self.stage["base_commit"] = "e" * 40
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])

    def test_receipt_archive_lineage_mismatch(self):
        self.receipt["archive_sha256"] = "f" * 64
        self.read_receipt.return_value = json.dumps(self.receipt).encode()
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])

    def test_receipt_plan_lineage_mismatch(self):
        self.receipt["overlay_plan_sha256"] = "f" * 64
        self.read_receipt.return_value = json.dumps(self.receipt).encode()
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])

    def test_receipt_changed_paths_mismatch(self):
        self.receipt["changed_paths"] = ["server/app/main.py"]
        self.read_receipt.return_value = json.dumps(self.receipt).encode()
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])

    def test_receipt_extra_key_rejected(self):
        self.receipt["unsafe"] = "ignored?"
        self.read_receipt.return_value = json.dumps(self.receipt).encode()
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])

    def test_stage_mutated_between_reads(self):
        changed = dict(self.stage, snapshot_tree_sha256="e" * 64)
        self.inspect_stage.side_effect = [self.stage, changed]
        self.assertBlocked(sut.STAGE, [sut.TRANSFER, sut.BASE])

    def test_test_gate_missing(self):
        self.tests.side_effect = ValueError("no signed receipt")
        self.assertBlocked(sut.TESTS, [sut.TRANSFER, sut.BASE, sut.STAGE])

    def test_hmac_gate_fake_success_not_enough(self):
        self.attested["snapshot_tree_sha256"] = "e" * 64
        self.assertBlocked(sut.TESTS, [sut.TRANSFER, sut.BASE, sut.STAGE])

    def test_missing_suite_denied(self):
        self.attested["completed_suite_count"] = 4
        self.assertBlocked(sut.TESTS, [sut.TRANSFER, sut.BASE, sut.STAGE])

    def test_report_cannot_authorize_deploy(self):
        self.attested["canary_start_authorized"] = True
        self.assertBlocked(sut.TESTS, [sut.TRANSFER, sut.BASE, sut.STAGE])

    def test_underlying_exception_message_not_leaked(self):
        self.tests.side_effect = OSError("sensitive-private-path")
        report = sut.inspect(TID)
        self.assertNotIn("sensitive-private-path", json.dumps(report))
        self.assertEqual(report["blocker_class"], "OSError")

    def test_transfer_retired_while_checking_tests_is_blocked(self):
        self.qualify.side_effect = [self.transfer, ValueError("retired")]
        self.assertBlocked(sut.TESTS, [sut.TRANSFER, sut.BASE, sut.STAGE])
        self.assertEqual(self.qualify.call_count, 2)

    def test_read_only_functions_only(self):
        sut.inspect(TID)
        self.assertEqual(self.qualify.call_count, 2)
        self.assertEqual([x.args for x in self.qualify.call_args_list],
                         [(TID,), (TID,)])
        self.preflight.assert_called_once_with(TID)
        self.tests.assert_called_once_with(TID)
        self.forbidden.assert_not_called()


if __name__ == "__main__":
    unittest.main()
