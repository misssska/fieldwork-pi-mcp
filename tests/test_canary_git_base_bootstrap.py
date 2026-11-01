"""Private read-only Git bootstrap integration, using disposable fixture repos."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from updater import canary_git_base_bootstrap as b
from updater import canary_archive_qualifier as q


def git(folder, *args):
    return subprocess.check_output(["git", "-C", str(folder), *args],
                                   stderr=subprocess.DEVNULL).strip()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("this installer is non-root")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir(mode=0o700)
        self.source = Path(self.tmp.name) / "fixture-git"
        self.source.mkdir(mode=0o700)
        git(self.source, "init", "-q")
        git(self.source, "config", "user.name", "Fixture")
        git(self.source, "config", "user.email", "fixture@example.invalid")
        f = self.source / "frontend/src/App.tsx"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"export const x = 1;\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "-qm", "Immutable fixture")
        self.commit = git(self.source, "rev-parse", "HEAD").decode()
        p1 = patch.object(b.Path, "home", return_value=self.home)
        p2 = patch.object(b, "SOURCE", self.source)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_private_clone_only_reads_committed_source(self):
        changed = self.source / "frontend/src/App.tsx"
        changed.write_bytes(b"uncommitted data\n")
        before = git(self.source, "status", "--porcelain=v1")
        receipt = b.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        private = self.home / b.TARGET
        self.assertEqual(receipt["status"], "PRIVATE_GIT_BASE_READY")
        self.assertFalse(receipt["production_modified"])
        self.assertEqual((private / "frontend/src/App.tsx").read_bytes(),
                         b"export const x = 1;\n")
        self.assertEqual(changed.read_bytes(), b"uncommitted data\n")
        self.assertEqual(git(self.source, "status", "--porcelain=v1"), before)
        self.assertEqual(git(private, "rev-parse", "HEAD").decode(), self.commit)

    def test_wrong_commit_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "PRODUCTION_HEAD_PIN_MISMATCH"):
            b.bootstrap("f" * 40, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")

    def test_missing_consent_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "LOCAL_BOOTSTRAP_APPROVAL_REQUIRED"):
            b.bootstrap(self.commit, "NO")

    def test_existing_private_base_never_overwritten(self):
        b.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "PRIVATE_BASE_ALREADY_EXISTS"):
            b.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")

    def test_attributes_denied(self):
        p = self.source / ".gitattributes"
        p.write_text("*.tsx filter=custom\n")
        git(self.source, "add", ".gitattributes")
        git(self.source, "commit", "-qm", "Config fixture")
        current = git(self.source, "rev-parse", "HEAD").decode()
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "GIT_ATTRIBUTES_OR_SUBMODULES_DENIED"):
            b.preflight(current)

    def test_untracked_file_not_cloned(self):
        (self.source / "untracked.txt").write_text("temporary")
        b.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        self.assertFalse((self.home / b.TARGET / "untracked.txt").exists())

    def test_unpinned_commit_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "EXPECTED_COMMIT_REQUIRED"):
            b.preflight("HEAD")


if __name__ == "__main__":
    unittest.main()
