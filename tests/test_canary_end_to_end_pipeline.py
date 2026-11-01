"""End-to-end release evidence contract with a real private Git repository.

REAL: local Git commit/clone, byte-exact source transfer, ZIP qualification,
stage materialization, tree SHA256, durable HMAC test receipt.
MOCKED: Docker application test execution. This suite cannot assert that
FieldWork's actual frontend/backend passed or that any canary started.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from updater import artifact_inbox as inbox
from updater import canary_archive_builder as builder
from updater import canary_archive_qualifier as qualifier
from updater import canary_git_base_bootstrap as bootstrap
from updater import canary_stage_materializer as materializer
from updater import canary_stage_inspect as inspector
from updater import canary_test_runner as tests
from updater import canary_test_gate as gate

TID = "7" * 32
IMAGE = "fieldwork-canary-test-appliance@sha256:" + "a" * 64
ORIGINAL = {
    "frontend/package-lock.json": b'{"lockfileVersion":3}\n',
    "frontend/package.json": b'{"name":"fixture"}\n',
    "frontend/src/App.tsx": b"export const App = 'before';\n",
    "server/requirements.txt": b"fastapi==0.1\n",
    "server/requirements-dev.txt": b"pytest==8.4.2\n",
    "server/app/main.py": b"def version():\n    return 1\n",
    "server/tests/test_app.py": b"def test_basic():\n    assert True\n",
}
PATCH = {
    "frontend/src/App.tsx": b"export const App = 'after';\n",
    "server/app/main.py": b"def version():\n    return 2\n",
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args],
                                   stderr=subprocess.DEVNULL).strip()


class EndToEndReleaseTest(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("all stage operations require an unprivileged account")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir(mode=0o700)
        self.original = Path(self.tmp.name) / "production-fixture"
        self.original.mkdir(mode=0o700)
        git(self.original, "init", "-q")
        git(self.original, "config", "user.name", "Test Author")
        git(self.original, "config", "user.email", "test@example.invalid")
        for rel, data in ORIGINAL.items():
            path = self.original / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.original / ".github/workflows").mkdir(parents=True)
        (self.original / ".github/workflows/safe.yml").write_text("name: safe\n")
        git(self.original, "add", ".")
        git(self.original, "commit", "-qm", "Clean base")
        self.commit = git(self.original, "rev-parse", "HEAD").decode()
        p1 = patch.object(Path, "home", return_value=self.home)
        p2 = patch.object(bootstrap, "SOURCE", self.original)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def upload(self, *, previous=None, commit=None, tid=TID):
        expected = {path: qualifier.digest(ORIGINAL[path]) for path in PATCH}
        if previous:
            expected.update(previous)
        zipbytes, report = builder.make_archive(
            base_commit=commit or self.commit, files=PATCH,
            previous_sha256=expected,
        )
        inbox.begin(tid, len(zipbytes), report["artifact_sha256"])
        # Multiple chunks to exercise ordered byte transfer.
        midpoint = len(zipbytes) // 2
        inbox.append(tid, 0, base64.b64encode(zipbytes[:midpoint]).decode())
        inbox.append(tid, midpoint, base64.b64encode(zipbytes[midpoint:]).decode())
        inbox.finalize(tid)
        return zipbytes, report

    def approve_tests(self, tid=TID):
        root = self.home / inbox.STATE.parent / inspector.STAGE_NAME / tid
        pins = {}
        for key, relative in tests.DEPENDENCY_FILES.items():
            pins[key] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        policy = self.home / tests.PIN_REL
        policy.write_text(json.dumps({
            "schema": 1, "profile": tests.PROFILE,
            "image": IMAGE, "stage_testing_only": True,
            "locally_approved": True, **pins
        }))
        policy.chmod(0o600)
        attestation = self.home / tests.KEY_REL
        attestation.write_bytes(b"0123456789abcdef0123456789abcdef")
        attestation.chmod(0o600)

    def test_full_source_flow_and_mocked_test_attestation(self):
        # Dirty production working-tree bytes are not part of the pinned source.
        (self.original / "frontend/src/App.tsx").write_bytes(
            b"uncommitted local working changes\n")
        original_git_status = git(self.original, "status", "--porcelain=v1")
        bootstrap.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        zipbytes, report = self.upload()
        verified = qualifier.qualify_transfer(TID)
        self.assertEqual(verified["status"], "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED")
        self.assertEqual(verified["artifact_sha256"], report["artifact_sha256"])
        materialized = materializer.materialize_transfer(TID)
        inspected = inspector.inspect_stage(TID)
        self.assertEqual(inspected["status"], "STAGE_VERIFIED_NOT_TESTED")
        self.assertEqual(materialized["snapshot_tree_sha256"],
                         inspected["snapshot_tree_sha256"])
        private = self.home / inbox.STATE.parent / inspector.STAGE_NAME / TID
        for rel, data in PATCH.items():
            self.assertEqual((private / rel).read_bytes(), data)
        self.assertEqual((self.home / bootstrap.TARGET /
                          "frontend/src/App.tsx").read_bytes(),
                         ORIGINAL["frontend/src/App.tsx"])
        self.assertEqual(git(self.original, "status", "--porcelain=v1"),
                         original_git_status)
        self.assertEqual((self.original / "frontend/src/App.tsx").read_bytes(),
                         b"uncommitted local working changes\n")

        # A code-execution test is MOCKED, not actual FieldWork tests.
        self.approve_tests()
        with patch.object(tests, "_run_docker", return_value=(True, "EXIT_0")) as invoke:
            candidate = tests.run(TID)
        self.assertEqual(invoke.call_count, 5)
        self.assertEqual(candidate["status"], "FULL_TEST_PASS_NOT_DEPLOYED")
        checked = gate.inspect_tests(TID)
        self.assertEqual(checked["status"], "FULL_TEST_ATTESTED_NOT_DEPLOYED")
        self.assertFalse(checked["canary_start_authorized"])
        self.assertFalse(checked["production_modified"])

    def test_old_stage_pass_cannot_replace_new_stage_attestation(self):
        bootstrap.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        self.upload()
        materializer.materialize_transfer(TID)
        self.approve_tests()
        with self.assertRaises(qualifier.QualificationDenied):
            gate.inspect_tests(TID)

    def test_bad_previous_file_sha_prevents_stage_creation(self):
        bootstrap.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        self.upload(previous={"server/app/main.py": "f" * 64})
        with self.assertRaisesRegex(qualifier.QualificationDenied, "BASE_FILE_SHA256_DRIFT"):
            materializer.materialize_transfer(TID)
        self.assertFalse(
            (self.home / inbox.STATE.parent / inspector.STAGE_NAME / TID).exists())

    def test_older_base_commit_rejected_after_private_bootstrap(self):
        bootstrap.bootstrap(self.commit, "LETREHOZOM_A_PRIVAT_GIT_BAZIST")
        self.upload(commit="e" * 40)
        with self.assertRaisesRegex(qualifier.QualificationDenied, "CANARY_BASE_COMMIT_DRIFT"):
            materializer.materialize_transfer(TID)


if __name__ == "__main__":
    unittest.main()
