"""Independent read-only gate for locally attested full canary test results.

No Docker calls, stage writes, shell, source execution or deployment.
A successful gate is still NOT canary authorization. It is only a prerequisite.
"""
from __future__ import annotations

import hmac
import json
from pathlib import Path
import re

from . import artifact_inbox as inbox
from . import canary_archive_qualifier as q
from . import canary_stage_inspect as stage
from . import canary_test_runner as runner

REPORT_KEYS = frozenset({
    "schema", "status", "transfer_id", "snapshot_tree_sha256",
    "base_commit", "image", "profile", "completed_suites",
    "all_suites_pass", "canary_started", "production_modified",
    "attestation_hmac_sha256",
})


def inspect_tests(transfer_id: str) -> dict:
    inbox._valid_id(transfer_id)
    allowed = runner._config()
    checked = stage.inspect_stage(transfer_id)
    root = Path.home()
    for piece in runner.TESTS_REL.parts:
        root = root / piece
        q.require(root.is_dir() and not root.is_symlink(),
                  "TEST_RECEIPT_DIRECTORY_UNSAFE")
    root = root / transfer_id
    runner._owner_private(root, directory=True)
    file = root / "TEST_REPORT.json"
    runner._owner_private(file, directory=False)
    q.require(file.stat().st_size <= 16_384, "TEST_REPORT_TOO_LARGE")
    try:
        report = json.loads(file.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise q.QualificationDenied("TEST_REPORT_INVALID") from exc
    q.require(type(report) is dict and set(report) == REPORT_KEYS and
              type(report["schema"]) is int and report["schema"] == 1,
              "TEST_REPORT_SCHEMA_DENIED")
    signature = report["attestation_hmac_sha256"]
    q.require(type(signature) is str and
              q.HEX64.fullmatch(signature) is not None,
              "TEST_ATTESTATION_FORMAT_INVALID")
    q.require(hmac.compare_digest(signature, runner.attest(report)),
              "TEST_ATTESTATION_INVALID")
    q.require(report["status"] == "FULL_TEST_PASS_NOT_DEPLOYED" and
              report["all_suites_pass"] is True and
              report["production_modified"] is False and
              report["canary_started"] is False,
              "FULL_TEST_NOT_PASSED")
    q.require(report["transfer_id"] == transfer_id and
              report["snapshot_tree_sha256"] == checked["snapshot_tree_sha256"] and
              report["base_commit"] == checked["base_commit"],
              "TEST_RECEIPT_STAGE_MISMATCH")
    q.require(report["profile"] == runner.PROFILE and
              report["image"] == allowed["image"],
              "TEST_PROFILE_PIN_MISMATCH")
    suites = report["completed_suites"]
    q.require(type(suites) is list and
              len(suites) == len(runner.SUITES),
              "MISSING_TEST_SUITES")
    for position, item in enumerate(suites):
        q.require(type(item) is dict and set(item) == {
            "suite", "passed", "outcome"} and
            item["suite"] == runner.SUITES[position] and
            item["passed"] is True and item["outcome"] == "EXIT_0",
            "TEST_SUITE_EVIDENCE_DENIED")
    return {
        "status": "FULL_TEST_ATTESTED_NOT_DEPLOYED",
        "transfer_id": transfer_id,
        "base_commit": checked["base_commit"],
        "snapshot_tree_sha256": checked["snapshot_tree_sha256"],
        "image": report["image"],
        "completed_suite_count": len(suites),
        "canary_start_authorized": False,
        "production_modified": False,
    }
