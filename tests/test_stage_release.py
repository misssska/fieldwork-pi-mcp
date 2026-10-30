"""Offline tests for the release staging security boundary."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import stage_release as sr

COMMIT = "a" * 40
MAIN = b"def main():\n    return 1\n"
SHA = hashlib.sha256(MAIN).hexdigest()


def manifest(paths=None):
    return json.dumps({"schema": 1, "files": paths or [
        {"path": "fieldwork_mcp.py", "sha256": SHA}
    ]}).encode()


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sr.parse_manifest(manifest()), [("fieldwork_mcp.py", SHA)])

    def test_traversal_denied(self):
        with self.assertRaisesRegex(sr.StageError, "UNSAFE_FILE_PATH"):
            sr.parse_manifest(manifest([{"path": "../fieldwork_mcp.py", "sha256": SHA}]))

    def test_duplicate_denied(self):
        with self.assertRaisesRegex(sr.StageError, "DUPLICATE_FILE_PATH"):
            sr.parse_manifest(manifest([
                {"path": "fieldwork_mcp.py", "sha256": SHA},
                {"path": "fieldwork_mcp.py", "sha256": SHA},
            ]))

    def test_unknown_keys_denied(self):
        with self.assertRaisesRegex(sr.StageError, "INVALID_MANIFEST_KEYS"):
            sr.parse_manifest(b'{"schema":1,"files":[],"command":"sh"}')

    def test_bad_hash_denied(self):
        with self.assertRaisesRegex(sr.StageError, "INVALID_FILE_HASH"):
            sr.parse_manifest(manifest([{"path": "fieldwork_mcp.py", "sha256": "bad"}]))


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"

    def fake_fetch(self, commit, path, limit):
        return manifest() if path == "release/manifest.json" else MAIN

    def test_stage_only(self):
        with patch.object(sr, "fetch", side_effect=self.fake_fetch):
            dest = sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.state)
        self.assertEqual((dest / "fieldwork_mcp.py").read_bytes(), MAIN)
        self.assertEqual(json.loads((dest / "receipt.json").read_text())["status"],
                         "STAGED_NOT_INSTALLED")

    def test_manifest_mismatch(self):
        with patch.object(sr, "fetch", side_effect=self.fake_fetch):
            with self.assertRaisesRegex(sr.StageError, "MANIFEST_HASH_MISMATCH"):
                sr.stage(COMMIT, "0" * 64, self.state)

    def test_source_mismatch(self):
        def wrong_source(commit, path, limit):
            return manifest() if path == "release/manifest.json" else b"evil"
        with patch.object(sr, "fetch", side_effect=wrong_source):
            with self.assertRaisesRegex(sr.StageError, "FILE_HASH_MISMATCH"):
                sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.state)

    def test_existing_stage_denied(self):
        with patch.object(sr, "fetch", side_effect=self.fake_fetch):
            sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.state)
            with self.assertRaisesRegex(sr.StageError, "STAGE_ALREADY_EXISTS"):
                sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.state)

    def test_symlink_state_denied(self):
        real = Path(self.temp.name) / "real"
        real.mkdir()
        link = Path(self.temp.name) / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(sr.StageError, "SYMLINK_PATH_DENIED"):
            sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), link)


if __name__ == "__main__":
    unittest.main()
