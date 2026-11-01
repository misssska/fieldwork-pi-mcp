"""M5 private frontend CI contract; all Git repositories below are synthetic."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from updater import m5_private_frontend_gate as g

TESTS = {
    "src/api/client.test.ts": 5,
    "src/auth/AuthContext.test.tsx": 4,
    "src/data/FieldworkContext.integration.test.tsx": 6,
    "src/components/DocumentViewer.test.tsx": 3,
    "src/components/PhotoGalleryM5.test.tsx": 7,
    "src/components/Crud.integration.test.tsx": 9,
}

def receipt(tests=TESTS):
    rows = [f" ✓ {p} ({n} tests) 123ms" for p, n in tests.items()]
    return "\n".join([" RUN v3.2.7 /tmp/fixture", *rows,
                      f" Test Files  {len(tests)} passed ({len(tests)})",
                      f"      Tests  {sum(tests.values())} passed ({sum(tests.values())})", ""])

class RealGitPrivateSourceGate(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name).resolve()
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        git("init", "-q")
        git("config", "user.email", "m5-fixture@example.invalid")
        git("config", "user.name", "M5 Local Fixture")
        files = {
            "frontend/package.json": json.dumps({
                "private": True, "scripts": {**g.SCRIPTS, "dev": "vite", "test:e2e": "playwright test"},
                "devDependencies": {"vitest": "3.2.7"}}),
            "frontend/package-lock.json": json.dumps({
                "lockfileVersion": 3,
                "packages": {"node_modules/vitest": {"version": "3.2.7"}}}),
            "frontend/vite.config.ts": "include: ['src/**/*.test.{ts,tsx}']\n",
            "frontend/src/components/PhotoGallery.tsx": "export const x = 1\n",
        }
        for p in TESTS:
            files["frontend/"+p] = "export const fixture = true\n"
        for p, value in files.items():
            full = self.root/p
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(value)
        git("add", ".")
        git("commit", "-qm", "fixed fixture")
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.kw = dict(workspace=self.root, expected_commit=self.commit,
                       repository_private=True, runner_environment="github-hosted",
                       github_actions=True)
        self.pre = g.preflight(**self.kw)

    def test_preflight_admits_synthetic_private_checkout(self):
        self.assertEqual(self.pre["test_file_count"], 6)
        self.assertIn("frontend/src/api/client.test.ts", self.pre["source_hashes"])
        self.assertFalse(self.pre["release_authorized"])

    def test_positive_real_reporter_fixture(self):
        out = g.postflight(**self.kw, preflight_receipt=self.pre, log=receipt())
        self.assertEqual(out["tests"], 34)
        self.assertEqual(out["test_files"], 6)
        self.assertFalse(out["backend_pg_migrations_tested"])

    def test_public_repo_and_nonhosted_denied(self):
        for key, value in (("repository_private", False),
                           ("runner_environment", "self-hosted"),
                           ("github_actions", False)):
            k = {**self.kw, key: value}
            with self.subTest(key=key), self.assertRaises(g.M5PrivateCIGateDenied):
                g.preflight(**k)
            with self.subTest(key=key), self.assertRaises(g.M5PrivateCIGateDenied):
                g.postflight(**k, preflight_receipt=self.pre, log=receipt())

    def test_untracked_dirty_source_denied(self):
        (self.root/"frontend"/"new.tmp").write_text("bad")
        with self.assertRaisesRegex(g.M5PrivateCIGateDenied, "UNCLEAN"):
            g.preflight(**self.kw)

    def test_source_hash_drift_during_ci_denied(self):
        (self.root/"frontend/src/components/PhotoGallery.tsx").write_text("tampered")
        with self.assertRaises(g.M5PrivateCIGateDenied):
            g.postflight(**self.kw, preflight_receipt=self.pre, log=receipt())

    def test_m5_named_suite_missing_denied(self):
        partial = dict(TESTS)
        partial.pop("src/components/PhotoGalleryM5.test.tsx")
        with self.assertRaises(g.M5PrivateCIGateDenied):
            g.postflight(**self.kw, preflight_receipt=self.pre, log=receipt(partial))

    def test_silent_collection_gap_denied_even_if_summary_consistent(self):
        partial = dict(TESTS)
        partial.pop("src/api/client.test.ts")
        with self.assertRaisesRegex(g.M5PrivateCIGateDenied, "SILENT_TEST_COLLECTION_GAP"):
            g.postflight(**self.kw, preflight_receipt=self.pre, log=receipt(partial))

    def test_lockfile_vitest_version_drift_denied(self):
        file = self.root/"frontend/package-lock.json"
        file.write_text(file.read_text().replace("3.2.7", "3.2.8"))
        with self.assertRaises(g.M5PrivateCIGateDenied):
            g.preflight(**self.kw)

    def test_wrong_commit_denied(self):
        with self.assertRaisesRegex(g.M5PrivateCIGateDenied, "HEAD_SHA_NOT_EXACT"):
            g.preflight(**{**self.kw, "expected_commit": "f"*40})

    def test_symlink_testfile_denied(self):
        f = self.root/"frontend/src/api/client.test.ts"
        f.unlink()
        f.symlink_to(self.root/"frontend/src/components/PhotoGallery.tsx")
        with self.assertRaises(g.M5PrivateCIGateDenied):
            g.postflight(**self.kw, preflight_receipt=self.pre, log=receipt())

    def test_spoof_summary_wrong_count_denied(self):
        with self.assertRaises(g.M5PrivateCIGateDenied):
            g.postflight(**self.kw, preflight_receipt=self.pre,
                         log=receipt().replace("Tests  34 passed (34)", "Tests  33 passed (33)"))

    def test_git_not_arbitrary_shell(self):
        with self.assertRaisesRegex(g.M5PrivateCIGateDenied, "NOT_ALLOWLISTED"):
            g.git(self.root, "reset", "--hard", "HEAD")

if __name__ == "__main__":
    unittest.main()
