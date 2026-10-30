"""Offline tests for the Async Stage release staging security boundary."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import stage_release as sr

COMMIT = "a" * 40
SOURCES = {
    "stage_async.py": b"def request(args):\n    return {}\n",
    "async_overlay.py": b"def overlay(source):\n    return source\n",
}
FILES = [
    {"path": path, "sha256": hashlib.sha256(source).hexdigest()}
    for path, source in SOURCES.items()
]


def manifest(paths=None):
    return json.dumps({"schema": 1, "files": FILES if paths is None else paths}).encode()


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual({p for p, _ in sr.parse_manifest(manifest())}, set(SOURCES))

    def test_traversal_denied(self):
        with self.assertRaisesRegex(sr.StageError, "UNSAFE_FILE_PATH"):
            sr.parse_manifest(manifest([
                {"path": "../stage_async.py", "sha256": FILES[0]["sha256"]}, FILES[1]
            ]))

    def test_duplicate_denied(self):
        with self.assertRaisesRegex(sr.StageError, "DUPLICATE_FILE_PATH"):
            sr.parse_manifest(manifest([FILES[0], FILES[0], FILES[1]]))

    def test_unknown_keys_denied(self):
        with self.assertRaisesRegex(sr.StageError, "INVALID_MANIFEST_KEYS"):
            sr.parse_manifest(b'{"schema":1,"files":[],"command":"sh"}')

    def test_bad_hash_denied(self):
        with self.assertRaisesRegex(sr.StageError, "INVALID_FILE_HASH"):
            sr.parse_manifest(manifest([
                {"path": "stage_async.py", "sha256": "bad"}, FILES[1]
            ]))

    def test_full_mcp_replacement_denied(self):
        with self.assertRaisesRegex(sr.StageError, "UNSAFE_FILE_PATH"):
            sr.parse_manifest(manifest([
                {"path": "fieldwork_mcp.py", "sha256": FILES[0]["sha256"]}, FILES[1]
            ]))

    def test_overlay_required(self):
        with self.assertRaisesRegex(sr.StageError, "ASYNC_RELEASE_FILES_REQUIRED"):
            sr.parse_manifest(manifest([FILES[0]]))


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / ".local/state/fieldwork-pi-mcp/update-staging"
        self.home_patch = patch.object(sr.Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.uid_patch = patch.object(sr.os, "geteuid", return_value=1000)
        self.uid_patch.start()
        self.addCleanup(self.uid_patch.stop)

    def fake_fetch(self, commit, path, limit):
        return manifest() if path == "release/manifest.json" else SOURCES[path.removeprefix("release/")]

    def test_stage_only(self):
        with patch.object(sr, "fetch", side_effect=self.fake_fetch):
            dest = sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.state)
        for name, content in SOURCES.items():
            self.assertEqual((dest / name).read_bytes(), content)
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
        self.state.parent.mkdir(parents=True)
        self.state.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(sr.StageError, "SYMLINK_PATH_DENIED"):
            sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.state)

    def test_arbitrary_destination_denied(self):
        with self.assertRaisesRegex(sr.StageError, "STAGE_DESTINATION_DENIED"):
            sr.stage(COMMIT, hashlib.sha256(manifest()).hexdigest(), self.home / "other")


if __name__ == "__main__":
    unittest.main()
