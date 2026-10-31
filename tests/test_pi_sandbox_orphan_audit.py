"""M10 negative-first host orphan inventory tests, with Docker fully mocked."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from updater import pi_sandbox_orphan_audit as audit

FAILED_RUN = "b901aaabbbcccdddeeefff0000000020"
CID = "a" * 64
PROD_ID = "b" * 64


def line(id=CID, name="fieldwork-api-1", labels="", state="running"):
    return json.dumps({"ID": id, "Names": name,
                       "Labels": labels, "State": state}).encode() + b"\n"


class PureClassification(unittest.TestCase):
    def parsed(self, payload=b"", run_id=FAILED_RUN, failed=True):
        return audit.classify_inventory(
            payload, run_id, historical_cleanup_failed=failed)

    def denied(self, payload, error):
        with self.assertRaisesRegex(audit.HostAuditDenied, error):
            self.parsed(payload)

    def test_empty_inventory_never_clears_prior_cleanup_failure(self):
        result = self.parsed()
        self.assertEqual(result["status"],
                         "HISTORICAL_CLEANUP_UNVERIFIED_NO_EXACT_MATCH")
        self.assertEqual(result["inventory_container_count"], 0)
        self.assertEqual(result["candidate_count"], 0)
        self.assertFalse(result["historical_cleanup_receipt_resolved"])
        self.assertFalse(result["sandbox_test_retry_authorized"])
        self.assertFalse(result["container_removal_authorized"])
        self.assertFalse(result["production_modified"])

    def test_unrelated_production_and_stage_are_not_classified(self):
        result = self.parsed(line(PROD_ID, "fieldwork-api-1",
                                  "com.docker.compose.project=fieldwork") +
                             line(CID, "fieldwork-stage-db-1",
                                  "com.docker.compose.project=fieldwork-stage"))
        self.assertEqual(result["inventory_container_count"], 2)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["status"],
                         "HISTORICAL_CLEANUP_UNVERIFIED_NO_EXACT_MATCH")

    def test_exact_name_run_id_matches_review_only(self):
        result = self.parsed(line(CID, "sandbox-" + FAILED_RUN,
                                  "app=fieldwork", "running"))
        self.assertEqual(result["status"],
                         "HISTORICAL_ORPHAN_CANDIDATE_FOUND_REVIEW_REQUIRED")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["container_id"], CID)
        self.assertEqual(result["candidates"][0]["match_type"], "name")
        self.assertEqual(result["candidates"][0]["state"], "running")
        self.assertFalse(result["container_removal_authorized"])
        self.assertFalse(result["historical_cleanup_receipt_resolved"])

    def test_exact_label_value_matches_review_only(self):
        result = self.parsed(line(CID, "some-other-name",
                                  "com.example.run_id=" + FAILED_RUN,
                                  "exited"))
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["match_type"], "label")
        self.assertEqual(result["candidates"][0]["state"], "exited")

    def test_partial_id_does_not_match(self):
        self.assertEqual(self.parsed(line(CID, "sandbox-"+FAILED_RUN[:-1]))[
                         "candidate_count"], 0)
        self.assertEqual(self.parsed(line(CID, "sandbox-"+FAILED_RUN+"a"))[
                         "candidate_count"], 0)
        self.assertEqual(self.parsed(line(CID, "sandbox-a"+FAILED_RUN))[
                         "candidate_count"], 0)

    def test_multiple_candidates_are_not_silently_collapsed(self):
        value = self.parsed(line(CID, "sandbox-"+FAILED_RUN) +
                            line(PROD_ID, "some-label",
                                 "runid="+FAILED_RUN))
        self.assertEqual(value["candidate_count"], 2)
        self.assertEqual(len(value["candidates"]), 2)
        self.assertFalse(value["container_removal_authorized"])

    def test_never_exposes_raw_name_or_labels(self):
        r = self.parsed(line(CID, "secret-identifier-"+FAILED_RUN,
                             "password=arbitrary-opaque-secret,runid="+FAILED_RUN))
        rendered = json.dumps(r)
        self.assertNotIn("password", rendered)
        self.assertNotIn("arbitrary-opaque", rendered)
        self.assertNotIn("secret-identifier", rendered)
        self.assertNotIn("Labels", rendered)
        self.assertTrue(r["inventory_sha256"])

    def test_production_name_spoofed_with_run_id_is_not_delete_permission(self):
        r = self.parsed(line(CID, "fieldwork-api-"+FAILED_RUN,
                             "com.docker.compose.project=fieldwork"))
        self.assertEqual(r["candidate_count"], 1)
        self.assertFalse(r["container_removal_authorized"])
        self.assertFalse(r["sandbox_test_retry_authorized"])

    def test_nonhex_run_id_denied(self):
        for bad in (None, "", "x"*32, FAILED_RUN+"a", "aa", "../../etc"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(
                        audit.HostAuditDenied, "AUDIT_RUN_ID_INVALID"):
                    self.parsed(run_id=bad)

    def test_prior_receipt_is_required(self):
        with self.assertRaisesRegex(
                audit.HostAuditDenied,
                "AUDIT_HISTORICAL_CLEANUP_RECEIPT_REQUIRED"):
            self.parsed(failed=False)

    def test_invalid_json_denied(self):
        self.denied(b"not a json object\n", "AUDIT_OUTPUT_INVALID")

    def test_json_array_denied(self):
        self.denied(b"[]\n", "AUDIT_DOCKER_OUTPUT_SCHEMA_DENIED")

    def test_shortened_docker_id_denied(self):
        self.denied(line("abc", "sandbox-"+FAILED_RUN),
                    "AUDIT_CONTAINER_ID_INVALID")

    def test_duplicate_docker_id_denied(self):
        self.denied(line() + line(), "AUDIT_DUPLICATE_CONTAINER_ID")

    def test_unicode_invalid_denied(self):
        self.denied(b"\xff\xfe", "AUDIT_OUTPUT_INVALID")

    def test_output_limit_denied(self):
        self.denied(b"x" * (audit.MAX_OUTPUT_BYTES + 1),
                    "AUDIT_OUTPUT_BOUNDS_DENIED")

    def test_record_limit_denied(self):
        self.denied(line() * (audit.MAX_CONTAINERS + 1),
                    "AUDIT_TOO_MANY_CONTAINERS")

    def test_name_and_label_size_denied(self):
        self.denied(line(CID, "n" * 1025),
                    "AUDIT_DOCKER_FIELDS_INVALID")
        self.denied(line(CID, "name", "a"*8193),
                    "AUDIT_DOCKER_FIELDS_INVALID")

    def test_invalid_unknown_state_is_redacted(self):
        r = self.parsed(line(CID, "sandbox-"+FAILED_RUN,
                             "", "state-secret-value"))
        self.assertEqual(r["candidates"][0]["state"], "unknown")
        self.assertNotIn("state-secret-value", str(r))


class LocalHostCommandContract(unittest.TestCase):
    def run_mock(self, *, argv_result=None):
        if os.geteuid() == 0:
            self.skipTest("local host audit must refuse root")
        good = line(CID, "sandbox-"+FAILED_RUN)
        mock_result = argv_result or subprocess.CompletedProcess(
            audit.FIXED_DOCKER_COMMAND, 0, good, b"")
        with patch.object(audit.subprocess, "run",
                          return_value=mock_result) as run:
            result = audit.inspect_host(FAILED_RUN)
        self.assertEqual(run.call_count, 1)
        argv = run.call_args.args[0]
        self.assertEqual(argv, audit.FIXED_DOCKER_COMMAND)
        self.assertIn("container", argv)
        self.assertIn("ls", argv)
        self.assertNotIn("rm", argv)
        self.assertNotIn("prune", argv)
        self.assertNotIn("stop", argv)
        self.assertNotIn("--filter", argv)
        self.assertIn("unix:///var/run/docker.sock", argv)
        self.assertEqual(run.call_args.kwargs["timeout"],
                         audit.TIMEOUT_SECONDS)
        self.assertEqual(run.call_args.kwargs["stdin"],
                         subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"],
                         subprocess.DEVNULL)
        self.assertNotIn("DOCKER_HOST", run.call_args.kwargs["env"])
        self.assertFalse(result["container_removal_authorized"])
        self.assertFalse(result["sandbox_test_retry_authorized"])

    def test_exact_argv_and_redacted_output(self):
        self.run_mock()

    def test_nonzero_docker_exit_is_blocked(self):
        if os.geteuid() == 0:
            self.skipTest("local audit root denial")
        bad = subprocess.CompletedProcess(
            audit.FIXED_DOCKER_COMMAND, 2, b"", b"opaque daemon error")
        with patch.object(audit.subprocess, "run",
                          return_value=bad):
            with self.assertRaisesRegex(audit.HostAuditDenied,
                                        "AUDIT_DOCKER_QUERY_FAILED"):
                audit.inspect_host(FAILED_RUN)

    def test_invalid_run_id_does_not_contact_docker(self):
        with patch.object(audit.subprocess, "run") as proc:
            with self.assertRaises(audit.HostAuditDenied):
                audit.inspect_host("NOT-AN-ID")
            proc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
