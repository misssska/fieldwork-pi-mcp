"""Integration tests using a disposable, private Git repository.

No Pi production files, Docker, tunnel or network access.
"""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from updater import canary_git_base as g
from updater import canary_archive_builder as b
from updater import canary_archive_qualifier as q

TARGET = "frontend/src/components/TaskDetail.tsx"
CREATED = "frontend/src/components/ZoomToolbar.tsx"
ORIGINAL = b"export const original = true;\n"
REPLACEMENT = b"export const original = false;\n"
ADDED = b"export const zoom = 2;\n"


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args],
                                   stderr=subprocess.DEVNULL).strip()


class GitSourceGateTests(unittest.TestCase):
    def setUp(self):
        if g.os.geteuid() == 0:
            self.skipTest("Git snapshot reads require an unprivileged owner")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / g.BASE_REL
        self.root.mkdir(parents=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Git Gate Test")
        git(self.root, "config", "user.email", "test@invalid.local")
        path = self.root / TARGET
        path.parent.mkdir(parents=True)
        path.write_bytes(ORIGINAL)
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "Pinned base")
        self.commit = git(self.root, "rev-parse", "HEAD").decode()
        self.home_patch = patch.object(g.Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def archive(self, previous=None):
        data, receipt = b.make_archive(
            base_commit=self.commit,
            files={TARGET: REPLACEMENT, CREATED: ADDED},
            previous_sha256={
                TARGET: q.digest(ORIGINAL) if previous is None else previous,
                CREATED: None,
            })
        return data, receipt["artifact_sha256"]

    def test_clean_pinned_checkout_prepares_source_only(self):
        data, sha = self.archive()
        receipt = g.preflight(data, sha)
        self.assertEqual(receipt.receipt["status"],
                         "CANARY_OVERLAY_PREPARED_NOT_MATERIALIZED")
        self.assertEqual(receipt.files[TARGET], REPLACEMENT)
        self.assertEqual(receipt.files[CREATED], ADDED)
        self.assertEqual((self.root / TARGET).read_bytes(), ORIGINAL)
        self.assertFalse((self.root / CREATED).exists())

    def test_dirty_checkout_denied_even_if_git_HEAD_matches(self):
        (self.root / TARGET).write_bytes(b"uncommitted")
        data, sha = self.archive()
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "ISOLATED_GIT_BASE_DIRTY"):
            g.preflight(data, sha)

    def test_new_untracked_file_denied(self):
        (self.root / CREATED).parent.mkdir(exist_ok=True)
        (self.root / CREATED).write_bytes(b"untracked")
        data, sha = self.archive()
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "ISOLATED_GIT_BASE_DIRTY"):
            g.preflight(data, sha)

    def test_wrong_commit_denied(self):
        data, sha = b.make_archive(
            base_commit="a" * 40,
            files={TARGET: REPLACEMENT},
            previous_sha256={TARGET: q.digest(ORIGINAL)})
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "CANARY_BASE_COMMIT_DRIFT"):
            g.preflight(data, sha["artifact_sha256"])

    def test_stale_previous_blob_denied(self):
        data, sha = self.archive(previous="f" * 64)
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "BASE_FILE_SHA256_DRIFT"):
            g.preflight(data, sha)

    def test_git_file_mode_exec_denied(self):
        f = self.root / TARGET
        f.chmod(0o755)
        git(self.root, "add", TARGET)
        git(self.root, "commit", "-qm", "Executable mode")
        commit = git(self.root, "rev-parse", "HEAD").decode()
        data, sha = b.make_archive(base_commit=commit,
                                   files={TARGET: REPLACEMENT},
                                   previous_sha256={TARGET: q.digest(ORIGINAL)})
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "GIT_SOURCE_FILE_TYPE_DENIED"):
            g.preflight(data, sha["artifact_sha256"])

    def test_git_symlink_mode_denied(self):
        f = self.root / TARGET
        f.unlink()
        f.symlink_to("another.tsx")
        git(self.root, "add", TARGET)
        git(self.root, "commit", "-qm", "Symlink mode")
        commit = git(self.root, "rev-parse", "HEAD").decode()
        data, sha = b.make_archive(base_commit=commit,
                                   files={TARGET: REPLACEMENT},
                                   previous_sha256={TARGET: "a" * 64})
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "GIT_SOURCE_FILE_TYPE_DENIED"):
            g.preflight(data, sha["artifact_sha256"])

    def test_unsafe_base_checkout_symlink_denied(self):
        rel = self.root / ".git"
        other = self.root / ".git-backup"
        rel.rename(other)
        rel.symlink_to(other, target_is_directory=True)
        data, sha = self.archive()
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "GIT_BASE_NOT_REPO"):
            g.preflight(data, sha)

    def test_not_arbitrary_path_or_production_repo(self):
        self.assertEqual(g.BASE_REL.as_posix(),
                         ".local/state/fieldwork-pi-mcp/canary-git-base")
        self.assertNotIn("/opt/fieldwork", g.BASE_REL.as_posix())
        self.assertFalse(any(callable(getattr(g, name, None))
                             for name in ("deploy", "checkout", "push", "restart")))


if __name__ == "__main__":
    unittest.main()
