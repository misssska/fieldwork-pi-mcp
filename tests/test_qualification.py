"""Offline qualification tests; no Pi access, Docker or systemd."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from updater import qualification as q
from updater import async_overlay as o

COMMIT = "a" * 40
MANIFEST = "b" * 64
SOURCE = (
    o.IMPORT_OLD + "\nTOOLS = [\n" + o.TOOLS_OLD + "]\n"
    + "x = (" + o.ANNOTATION_OLD + ")\n"
).encode()
EXTENSION = b"def request(args): return {}\ndef status(args): return {}\n"


class QualificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.mcp = root / "installed"
        self.staging = root / "staging"
        self.mcp.mkdir(mode=0o700)
        self.staging.mkdir(mode=0o700)
        self.stage = self.staging / (COMMIT + "-" + MANIFEST[:12])
        self.stage.mkdir(mode=0o700)
        (self.mcp / "fieldwork_mcp.py").write_bytes(SOURCE)
        (self.stage / "stage_async.py").write_bytes(EXTENSION)
        shutil.copyfile(Path(o.__file__), self.stage / "async_overlay.py")
        self.receipt = {
            "commit": COMMIT, "manifest_sha256": MANIFEST,
            "files": ["stage_async.py", "async_overlay.py"],
            "status": "STAGED_NOT_INSTALLED",
        }
        self.write_receipt()
        for name, value in (("STAGING", self.staging), ("MCP", self.mcp)):
            p = patch.object(q, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(q.os, "geteuid", return_value=1000)
        p.start()
        self.addCleanup(p.stop)
        self.hash = hashlib.sha256(SOURCE).hexdigest()

    def write_receipt(self):
        (self.stage / "receipt.json").write_text(json.dumps(self.receipt))

    def test_pass_does_not_install(self):
        result = q.qualify(COMMIT, MANIFEST, self.hash)
        self.assertEqual(result["status"], "STATIC_QUALIFICATION_PASS")
        self.assertFalse(result["activation_authorized"])
        self.assertFalse(result["unit_tests_run"])
        self.assertEqual((self.mcp / "fieldwork_mcp.py").read_bytes(), SOURCE)
        self.assertFalse((self.mcp / "stage_async.py").exists())

    def test_drift_denied(self):
        with self.assertRaisesRegex(q.QualificationError, "INSTALLED_SOURCE_DRIFT"):
            q.qualify(COMMIT, MANIFEST, "0" * 64)

    def test_bad_receipt_denied(self):
        self.receipt["status"] = "INSTALLED"
        self.write_receipt()
        with self.assertRaisesRegex(q.QualificationError, "STAGE_NOT_READY"):
            q.qualify(COMMIT, MANIFEST, self.hash)

    def test_overlay_tamper_denied(self):
        (self.stage / "async_overlay.py").write_text("x = 1\n")
        with self.assertRaisesRegex(q.QualificationError, "OVERLAY_IMPLEMENTATION_DRIFT"):
            q.qualify(COMMIT, MANIFEST, self.hash)

    def test_symlink_denied(self):
        target = self.stage / "stage_async.py"
        target.unlink()
        target.symlink_to(self.mcp / "fieldwork_mcp.py")
        with self.assertRaisesRegex(q.QualificationError, "FILE_MISSING_OR_SYMLINK"):
            q.qualify(COMMIT, MANIFEST, self.hash)

    def test_partial_install_denied(self):
        (self.mcp / "stage_async.py").write_text("x=1\n")
        with self.assertRaisesRegex(q.QualificationError, "ASYNC_ALREADY_PRESENT"):
            q.qualify(COMMIT, MANIFEST, self.hash)

    def test_anchor_drift_denied(self):
        altered = SOURCE.replace(b"import stage_manager", b"import different")
        (self.mcp / "fieldwork_mcp.py").write_bytes(altered)
        with self.assertRaisesRegex(q.QualificationError, "CANDIDATE_INCOMPATIBLE"):
            q.qualify(COMMIT, MANIFEST, hashlib.sha256(altered).hexdigest())


if __name__ == "__main__":
    unittest.main()
