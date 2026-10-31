"""Acceptance and negative tests for pinned-base source-only planning."""
from __future__ import annotations

import hashlib
import unittest

from updater import canary_archive_builder as builder
from updater import canary_archive_qualifier as qualifier
from updater import canary_change_planner as planner

COMMIT = "a" * 40
EXISTING = "frontend/src/components/TaskDetail.tsx"
NEW = "frontend/src/components/PhotoZoomControls.tsx"
OLD_BYTES = b"export const zoom = false;\n"
NEW_BYTES = b"export const zoom = true;\n"
ADDED_BYTES = b"export const maxZoom = 8;\n"


def archive():
    files = {EXISTING: NEW_BYTES, NEW: ADDED_BYTES}
    previous = {EXISTING: qualifier.digest(OLD_BYTES), NEW: None}
    data, report = builder.make_archive(
        base_commit=COMMIT, files=files, previous_sha256=previous)
    return data, report


class ChangePlannerTests(unittest.TestCase):
    def plan(self, *, old=OLD_BYTES, absent=None, commit=COMMIT):
        contents, report = archive()
        return planner.prepare(
            archive_bytes=contents,
            archive_sha256=report["artifact_sha256"],
            independently_observed_commit=commit,
            observed_base_files={EXISTING: old, NEW: absent},
        )

    def test_overlay_plan_without_mutations(self):
        original = bytes(OLD_BYTES)
        plan = self.plan()
        self.assertEqual(plan.files[EXISTING], NEW_BYTES)
        self.assertEqual(plan.files[NEW], ADDED_BYTES)
        self.assertEqual(plan.receipt["status"], "CANARY_OVERLAY_PREPARED_NOT_MATERIALIZED")
        self.assertEqual(plan.receipt["changed_file_count"], 2)
        self.assertEqual(original, OLD_BYTES)
        for k in ("source_executed", "stage_written", "canary_started",
                  "production_modified"):
            self.assertIs(plan.receipt[k], False)
        self.assertNotIn("export const", repr(plan))

    def test_wrong_git_commit_is_refused(self):
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "CANARY_BASE_COMMIT_DRIFT"):
            self.plan(commit="b" * 40)
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "OBSERVED_GIT_COMMIT_INVALID"):
            self.plan(commit="main")

    def test_old_file_modification_detected(self):
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "BASE_FILE_SHA256_DRIFT"):
            self.plan(old=b"unexpected concurrent change")

    def test_file_missing_when_replacement_expected(self):
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "BASE_FILE_MISSING"):
            self.plan(old=None)

    def test_new_file_must_not_overwrite_existing(self):
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "UNDECLARED_OVERWRITE_DENIED"):
            self.plan(absent=b"another contributor created file")

    def test_missing_base_map_denied(self):
        data, report = archive()
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "OBSERVED_BASE_MAP_INCOMPLETE"):
            planner.prepare(
                archive_bytes=data,
                archive_sha256=report["artifact_sha256"],
                independently_observed_commit=COMMIT,
                observed_base_files={EXISTING: OLD_BYTES},
            )

    def test_unknown_base_map_path_denied(self):
        data, report = archive()
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "OBSERVED_BASE_MAP_INCOMPLETE"):
            planner.prepare(
                archive_bytes=data,
                archive_sha256=report["artifact_sha256"],
                independently_observed_commit=COMMIT,
                observed_base_files={
                    EXISTING: OLD_BYTES, NEW: None,
                    "/opt/fieldwork/.env": b"not allowed"},
            )

    def test_non_bytes_base_denied(self):
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "OBSERVED_BASE_FILE_INVALID"):
            self.plan(old="source text, not bytes")

    def test_exactly_same_source_denied(self):
        data, report = builder.make_archive(
            base_commit=COMMIT, files={EXISTING: OLD_BYTES},
            previous_sha256={EXISTING: qualifier.digest(OLD_BYTES)})
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "REDUNDANT_SOURCE_PATCH_DENIED"):
            planner.prepare(
                archive_bytes=data,
                archive_sha256=report["artifact_sha256"],
                independently_observed_commit=COMMIT,
                observed_base_files={EXISTING: OLD_BYTES},
            )

    def test_archive_corruption_denied(self):
        data, report = archive()
        with self.assertRaisesRegex(qualifier.QualificationDenied,
                                    "ARCHIVE_HASH_MISMATCH"):
            planner.prepare(
                archive_bytes=data + b"changed",
                archive_sha256=report["artifact_sha256"],
                independently_observed_commit=COMMIT,
                observed_base_files={EXISTING: OLD_BYTES, NEW: None},
            )

    def test_idempotent_receipt(self):
        self.assertEqual(self.plan().receipt, self.plan().receipt)


if __name__ == "__main__":
    unittest.main()
