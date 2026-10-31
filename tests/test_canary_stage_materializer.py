"""Real-Git, non-root, source-only private release materialization tests."""
from __future__ import annotations

import base64
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from updater import artifact_inbox as inbox
from updater import canary_archive_builder as builder
from updater import canary_archive_qualifier as q
from updater import canary_git_base as gitbase
from updater import canary_stage_materializer as stage

TID = "1" * 32
EXISTING = "frontend/src/components/TaskDetail.tsx"
ADDED = "frontend/src/components/ZoomControls.tsx"
OLD = b"export const zoom = 1;\n"
NEW = b"export const zoom = 3;\n"
ADD = b"export const zoomButton = true;\n"


def git(root: Path, *cmd: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *cmd],
                                   stderr=subprocess.DEVNULL).strip()


class MaterializerTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("The private stage must never be created by root")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

        self.base = self.home / gitbase.BASE_REL
        self.base.mkdir(parents=True)
        git(self.base, "init", "-q")
        git(self.base, "config", "user.email", "test@invalid.local")
        git(self.base, "config", "user.name", "Canary Test")
        file = self.base / EXISTING
        file.parent.mkdir(parents=True)
        file.write_bytes(OLD)
        (self.base / "server" / "app").mkdir(parents=True)
        # Empty tracked Python modules are valid and must stay empty.
        (self.base / "server" / "app" / "__init__.py").write_bytes(b"")
        git(self.base, "add", ".")
        git(self.base, "commit", "-qm", "Trusted separate base")
        self.commit = git(self.base, "rev-parse", "HEAD").decode()
        self.output_root = self.home / inbox.STATE.parent / stage.STAGE_NAME

    def add_transfer(self, *, base=None, previous=None, transfer_id=TID):
        zipdata, receipt = builder.make_archive(
            base_commit=base or self.commit,
            files={EXISTING: NEW, ADDED: ADD},
            previous_sha256={EXISTING: previous or q.digest(OLD), ADDED: None},
        )
        inbox.begin(transfer_id, len(zipdata), receipt["artifact_sha256"])
        inbox.append(transfer_id, 0, base64.b64encode(zipdata).decode())
        inbox.finalize(transfer_id)
        return zipdata

    def test_full_real_git_materialization_without_exec(self):
        self.add_transfer()
        receipt = stage.materialize_transfer(TID)
        work = self.output_root / TID
        self.assertEqual(receipt["status"], "STAGE_MATERIALIZED_NOT_TESTED")
        self.assertEqual(receipt["snapshot_file_count"], 3)
        self.assertEqual((work / EXISTING).read_bytes(), NEW)
        self.assertEqual((work / ADDED).read_bytes(), ADD)
        self.assertEqual((work / "server/app/__init__.py").read_bytes(), b"")
        self.assertEqual((self.base / EXISTING).read_bytes(), OLD)
        self.assertFalse((self.base / ADDED).exists())
        self.assertEqual(inbox.status(TID)["status"], "VERIFIED")
        self.assertEqual(os.stat(work).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(work / EXISTING).st_mode & 0o777, 0o600)
        self.assertFalse(receipt["tests_run"])
        self.assertFalse(receipt["canary_started"])
        self.assertFalse(receipt["production_modified"])

    def test_replay_fails_without_writing(self):
        self.add_transfer()
        stage.materialize_transfer(TID)
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "STAGE_ALREADY_EXISTS_OR_PARTIAL"):
            stage.materialize_transfer(TID)
        self.assertEqual((self.output_root / TID / EXISTING).read_bytes(), NEW)

    def test_bad_previous_hash_does_not_create_stage(self):
        self.add_transfer(previous="f" * 64)
        with self.assertRaisesRegex(q.QualificationDenied, "BASE_FILE_SHA256_DRIFT"):
            stage.materialize_transfer(TID)
        self.assertFalse((self.output_root / TID).exists())

    def test_wrong_commit_does_not_create_stage(self):
        self.add_transfer(base="d" * 40)
        with self.assertRaisesRegex(q.QualificationDenied, "CANARY_BASE_COMMIT_DRIFT"):
            stage.materialize_transfer(TID)
        self.assertFalse((self.output_root / TID).exists())

    def test_incomplete_upload_does_not_create_stage(self):
        self.add_transfer()
        other = "2" * 32
        inbox.begin(other, 10, "f" * 64)
        with self.assertRaisesRegex(q.QualificationDenied, "TRANSFER_NOT_VERIFIED"):
            stage.materialize_transfer(other)
        self.assertFalse((self.output_root / other).exists())

    def test_dirty_base_denied(self):
        self.add_transfer()
        (self.base / EXISTING).write_bytes(b"malicious drift")
        with self.assertRaisesRegex(q.QualificationDenied, "ISOLATED_GIT_BASE_DIRTY"):
            stage.materialize_transfer(TID)
        self.assertFalse((self.output_root / TID).exists())

    def test_untracked_base_denied(self):
        self.add_transfer()
        (self.base / "untracked.txt").write_bytes(b"untracked")
        with self.assertRaisesRegex(q.QualificationDenied, "ISOLATED_GIT_BASE_DIRTY"):
            stage.materialize_transfer(TID)
        self.assertFalse((self.output_root / TID).exists())

    def test_stage_directory_collision_denied(self):
        self.add_transfer()
        self.output_root.mkdir(parents=True)
        (self.output_root / TID).mkdir()
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "STAGE_ALREADY_EXISTS_OR_PARTIAL"):
            stage.materialize_transfer(TID)

    def test_git_symlink_in_base_denied_without_unsafe_copy(self):
        path = self.base / "frontend/src/components/link.tsx"
        path.symlink_to(EXISTING)
        git(self.base, "add", ".")
        git(self.base, "commit", "-qm", "Prohibited symlink")
        self.add_transfer(base=git(self.base, "rev-parse", "HEAD").decode())
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "GIT_TREE_SPECIAL_FILE_DENIED"):
            stage.materialize_transfer(TID)
        self.assertFalse((self.output_root / TID).exists())

    def test_archive_with_secret_path_is_denied(self):
        self.assertFalse(stage._segments is None)
        for unsafe in (".git/config", ".env", "server/app/.env", "private/key.pem",
                       "frontend/src/../other.tsx"):
            with self.subTest(unsafe=unsafe), self.assertRaisesRegex(
                    q.QualificationDenied, "GIT_TREE_PATH_DENIED"):
                stage._segments(unsafe)


if __name__ == "__main__":
    unittest.main()
