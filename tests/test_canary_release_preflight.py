"""End-to-end safe release preflight in a disposable artifact home."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import artifact_inbox as inbox
from updater import canary_archive_builder as builder
from updater import canary_release_preflight as release
from updater import canary_git_base as gitbase
from updater import canary_archive_qualifier as q

TID = "3" * 32
COMMIT = "a" * 40
PATH = "frontend/src/components/TaskDetail.tsx"
OLD = b"export const detail = false;\n"
NEW = b"export const detail = true;\n"


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("inbox prohibits root")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.patch_home = patch.object(inbox.Path, "home",
                                       return_value=self.home)
        self.patch_home.start()
        self.addCleanup(self.patch_home.stop)
        self.archive, report = builder.make_archive(
            base_commit=COMMIT,
            files={PATH: NEW},
            previous_sha256={PATH: q.digest(OLD)})
        self.sha = report["artifact_sha256"]

    def begin(self):
        inbox.begin(TID, len(self.archive), self.sha)

    def verified(self):
        self.begin()
        inbox.append(TID, 0, base64.b64encode(self.archive).decode())
        inbox.finalize(TID)

    def test_complete_end_to_end_preflight(self):
        self.verified()
        with patch.object(gitbase, "preflight") as plan:
            from updater.canary_change_planner import PreparedOverlay
            plan.return_value = PreparedOverlay(files={PATH: NEW}, receipt={
                "status": "CANARY_OVERLAY_PREPARED_NOT_MATERIALIZED",
                "changed_file_count": 1, "production_modified": False})
            result = release.preflight_transfer(TID)
            plan.assert_called_once_with(self.archive, self.sha)
        self.assertEqual(result["status"],
                         "RELEASE_PREFLIGHT_PASS_NOT_TESTED_NOT_STAGED")
        self.assertFalse(result["stage_written"])
        self.assertFalse(result["tests_run"])
        self.assertFalse(result["deployment_authorized"])
        self.assertFalse(result["production_modified"])
        self.assertEqual(result["transfer_id"], TID)

    def test_unfinished_transfer_rejected_before_base_inspection(self):
        self.begin()
        with patch.object(gitbase, "preflight") as read:
            with self.assertRaisesRegex(q.QualificationDenied,
                                        "RELEASE_TRANSFER_NOT_VERIFIED"):
                release.preflight_transfer(TID)
            read.assert_not_called()

    def test_missing_transfer_rejected(self):
        with self.assertRaises(inbox.InboxDenied):
            release.preflight_transfer(TID)

    def test_wrong_or_malicious_transfer_id_rejected(self):
        for tid in ("../../opt/fieldwork", "A" * 32, "", 123):
            with self.subTest(tid=tid), self.assertRaises(inbox.InboxDenied):
                release.preflight_transfer(tid)

    def test_git_preflight_fail_closed(self):
        self.verified()
        with patch.object(gitbase, "preflight",
                          side_effect=q.QualificationDenied("CANARY_BASE_COMMIT_DRIFT")):
            with self.assertRaisesRegex(q.QualificationDenied,
                                        "CANARY_BASE_COMMIT_DRIFT"):
                release.preflight_transfer(TID)
        self.assertEqual(inbox.status(TID)["status"], "VERIFIED")

    def test_no_host_writes_on_failed_git_gate(self):
        self.verified()
        before = (self.home / inbox.STATE / TID / "artifact.bin").read_bytes()
        with patch.object(gitbase, "preflight",
                          side_effect=q.QualificationDenied("ISOLATED_GIT_BASE_DIRTY")):
            with self.assertRaises(q.QualificationDenied):
                release.preflight_transfer(TID)
        self.assertEqual((self.home / inbox.STATE / TID / "artifact.bin").read_bytes(),
                         before)


if __name__ == "__main__":
    unittest.main()
