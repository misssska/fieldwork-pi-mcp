"""Read-only, end-to-end evidence gate for one FieldWork canary transfer.

This module only reads existing, independently generated evidence. It NEVER
creates stage snapshots, runs tests, starts containers, switches routes or
changes a production file. It is a candidate for a future narrowly-scoped
read-only MCP status operation, NOT a deployment permission.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import artifact_inbox as inbox
from . import canary_archive_qualifier as q
from . import canary_release_preflight as preflight
from . import canary_stage_inspect as stage
from . import canary_test_gate as gate
from . import canary_test_runner as runner

TRANSFER = "transfer"
BASE = "pinned_git_base"
STAGE = "private_stage"
TESTS = "test_attestation"
HEX40 = q.HEX40
HEX64 = q.HEX64


def _require_digest(value: object, length: int, label: str) -> None:
    pattern = HEX40 if length == 40 else HEX64
    q.require(type(value) is str and pattern.fullmatch(value) is not None,
              label + "_INVALID")


def _read_stage_receipt(transfer_id: str) -> dict:
    # inspect_stage has independently validated this receipt and the full
    # private tree. The receipt is read again to bind the ZIP and overlay-plan
    # hashes; we never trust a status label alone.
    root = Path.home() / inbox.STATE.parent / stage.STAGE_NAME / transfer_id
    data = stage._own_file(root / stage.RECEIPT, 16 * 1024)
    try:
        receipt = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise q.QualificationDenied("CANARY_STAGE_RECEIPT_INVALID") from exc
    q.require(type(receipt) is dict and set(receipt) == stage.EXPECTED,
              "CANARY_STAGE_RECEIPT_SCHEMA_DENIED")
    return receipt


def inspect(transfer_id: str) -> dict:
    """Inspect four ordered gates; fail closed with no paths or secret output.

    A complete evidence chain is deliberately NOT a deployment authorization.
    Missing prerequisites return READINESS_BLOCKED, without side effects.
    """
    inbox._valid_id(transfer_id)
    phase = TRANSFER
    result = {
        "transfer_id": transfer_id,
        "status": "READINESS_BLOCKED",
        "blocked_at": TRANSFER,
        "completed_gates": [],
        "canary_start_authorized": False,
        "deployment_authorized": False,
        "production_modified": False,
    }
    try:
        qualified = q.qualify_transfer(transfer_id)
        q.require(type(qualified) is dict and
                  qualified.get("status") ==
                  "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED" and
                  qualified.get("transfer_id") == transfer_id,
                  "TRANSFER_QUALIFICATION_NOT_PASSED")
        archive_hash = qualified.get("artifact_sha256")
        commit = qualified.get("base_commit")
        _require_digest(archive_hash, 64, "ARCHIVE_SHA256")
        _require_digest(commit, 40, "BASE_COMMIT")
        result["completed_gates"].append(TRANSFER)

        phase = BASE
        planned = preflight.preflight_transfer(transfer_id)
        q.require(type(planned) is dict and
                  planned.get("status") ==
                  "RELEASE_PREFLIGHT_PASS_NOT_TESTED_NOT_STAGED" and
                  planned.get("transfer_id") == transfer_id and
                  planned.get("archive_sha256") == archive_hash and
                  planned.get("base_commit") == commit and
                  planned.get("production_modified") is False and
                  planned.get("deployment_authorized") is False,
                  "PINNED_BASE_EVIDENCE_MISMATCH")
        plan_hash = planned.get("overlay_plan_sha256")
        changed_paths = planned.get("changed_paths")
        _require_digest(plan_hash, 64, "OVERLAY_PLAN")
        q.require(type(changed_paths) is list and
                  bool(changed_paths) and
                  len(changed_paths) == len(set(changed_paths)),
                  "CHANGE_SET_INVALID")
        result["completed_gates"].append(BASE)

        phase = STAGE
        inspected = stage.inspect_stage(transfer_id)
        q.require(type(inspected) is dict and
                  inspected.get("status") == "STAGE_VERIFIED_NOT_TESTED" and
                  inspected.get("transfer_id") == transfer_id and
                  inspected.get("base_commit") == commit and
                  inspected.get("production_modified") is False,
                  "PRIVATE_STAGE_EVIDENCE_MISMATCH")
        tree_hash = inspected.get("snapshot_tree_sha256")
        _require_digest(tree_hash, 64, "STAGE_TREE")
        receipt = _read_stage_receipt(transfer_id)
        q.require(receipt["transfer_id"] == transfer_id and
                  receipt["archive_sha256"] == archive_hash and
                  receipt["base_commit"] == commit and
                  receipt["overlay_plan_sha256"] == plan_hash and
                  receipt["changed_paths"] == changed_paths and
                  receipt["snapshot_tree_sha256"] == tree_hash and
                  receipt["status"] == "STAGE_MATERIALIZED_NOT_TESTED" and
                  receipt["production_modified"] is False and
                  receipt["canary_started"] is False and
                  receipt["tests_run"] is False,
                  "PRIVATE_STAGE_LINEAGE_MISMATCH")
        # Check again after binding the receipt; a stage mutation is a STOP.
        again = stage.inspect_stage(transfer_id)
        q.require(again == inspected, "PRIVATE_STAGE_CHANGED_DURING_READ")
        result["completed_gates"].append(STAGE)

        phase = TESTS
        attested = gate.inspect_tests(transfer_id)
        q.require(type(attested) is dict and
                  attested.get("status") == "FULL_TEST_ATTESTED_NOT_DEPLOYED" and
                  attested.get("transfer_id") == transfer_id and
                  attested.get("base_commit") == commit and
                  attested.get("snapshot_tree_sha256") == tree_hash and
                  attested.get("completed_suite_count") == len(runner.SUITES) and
                  attested.get("canary_start_authorized") is False and
                  attested.get("production_modified") is False,
                  "TEST_ATTESTATION_LINEAGE_MISMATCH")
        result["completed_gates"].append(TESTS)
        return {
            **result,
            "status": "READINESS_EVIDENCE_COMPLETE_NOT_DEPLOYABLE",
            "blocked_at": None,
            "artifact_sha256": archive_hash,
            "base_commit": commit,
            "snapshot_tree_sha256": tree_hash,
            "completed_suite_count": len(runner.SUITES),
        }
    except (q.QualificationDenied, inbox.InboxDenied, ValueError,
            TypeError, OSError, KeyError) as exc:
        # Do not leak filesystem paths or arbitrary underlying exception text.
        return {**result, "blocked_at": phase,
                "blocker_class": type(exc).__name__}
