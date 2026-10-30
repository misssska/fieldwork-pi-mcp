import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bootstrap as b

COMMIT = 'a' * 40
SOURCES = {name: b'x = 1\n' for name in b.FILES}
MANIFEST = json.dumps({'schema': 1, 'files': [
    {'path': name, 'sha256': hashlib.sha256(SOURCES[name]).hexdigest()}
    for name in b.FILES
]}).encode()
DIGEST = hashlib.sha256(MANIFEST).hexdigest()


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(set(b.parse_manifest(MANIFEST)), set(b.FILES))

    def test_missing_file(self):
        bad = json.dumps({'schema': 1, 'files': []}).encode()
        with self.assertRaises(b.Stop):
            b.parse_manifest(bad)

    def test_traversal_denied(self):
        obj = json.loads(MANIFEST)
        obj['files'][0]['path'] = '../evil.py'
        with self.assertRaisesRegex(b.Stop, 'MANIFEST_UNSAFE_PATH'):
            b.parse_manifest(json.dumps(obj).encode())

    def test_duplicate_denied(self):
        obj = json.loads(MANIFEST)
        obj['files'][1] = obj['files'][0]
        with self.assertRaisesRegex(b.Stop, 'MANIFEST_UNSAFE_PATH'):
            b.parse_manifest(json.dumps(obj).encode())


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.dest = self.home / '.local/share/fieldwork-pi-mcp/update-agent'
        self.uid_patch = patch.object(b.os, 'geteuid', return_value=1000)
        self.uid_patch.start()
        self.addCleanup(self.uid_patch.stop)
        self.home_patch = patch.object(b.Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def fake_fetch(self, commit, path, limit):
        return MANIFEST if path == 'bootstrap/manifest.json' else SOURCES[path]

    def test_stage_only(self):
        with patch.object(b, 'fetch', side_effect=self.fake_fetch):
            result = b.prepare(COMMIT, DIGEST, self.dest)
        self.assertEqual(result['status'], 'UPDATER_STAGED_ONLY')
        self.assertFalse(result['mcp_modified'])
        self.assertFalse(result['tunnel_restarted'])
        self.assertTrue((Path(result['path']) / b.FILES[0]).exists())

    def test_manifest_mismatch(self):
        with patch.object(b, 'fetch', side_effect=self.fake_fetch):
            with self.assertRaisesRegex(b.Stop, 'MANIFEST_HASH_MISMATCH'):
                b.prepare(COMMIT, '0' * 64, self.dest)

    def test_file_mismatch(self):
        def wrong(commit, path, limit):
            return MANIFEST if path == 'bootstrap/manifest.json' else b'evil'
        with patch.object(b, 'fetch', side_effect=wrong):
            with self.assertRaisesRegex(b.Stop, 'FILE_HASH_MISMATCH'):
                b.prepare(COMMIT, DIGEST, self.dest)

    def test_invalid_destination(self):
        with self.assertRaisesRegex(b.Stop, 'DESTINATION_DENIED'):
            b.prepare(COMMIT, DIGEST, self.home / 'wrong')

    def test_symlink_destination(self):
        real = self.home / 'real'
        real.mkdir()
        self.dest.parent.mkdir(parents=True)
        self.dest.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(b.Stop, 'SYMLINK_DIRECTORY_DENIED'):
            b.prepare(COMMIT, DIGEST, self.dest)

    def test_existing_version_not_overwritten(self):
        with patch.object(b, 'fetch', side_effect=self.fake_fetch):
            b.prepare(COMMIT, DIGEST, self.dest)
            with self.assertRaisesRegex(b.Stop, 'VERSION_ALREADY_STAGED'):
                b.prepare(COMMIT, DIGEST, self.dest)


if __name__ == '__main__':
    unittest.main()
