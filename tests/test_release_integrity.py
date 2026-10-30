"""Offline end-to-end test of the published overlay-only release."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import stage_release

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'a' * 40


class ReleaseIntegrityTests(unittest.TestCase):
    def test_release_manifest_and_overlay_identity(self):
        manifest = stage_release.parse_manifest((ROOT / 'release/manifest.json').read_bytes())
        self.assertEqual({path for path, _ in manifest}, {'stage_async.py', 'async_overlay.py'})
        for path, digest in manifest:
            self.assertEqual(hashlib.sha256((ROOT / 'release' / path).read_bytes()).hexdigest(),
                             digest, path)
        self.assertEqual((ROOT / 'release/async_overlay.py').read_bytes(),
                         (ROOT / 'updater/async_overlay.py').read_bytes())

    def test_full_offline_staging_never_installs(self):
        manifest = (ROOT / 'release/manifest.json').read_bytes()
        def fetch(commit, path, limit):
            data = (ROOT / path).read_bytes()
            self.assertLessEqual(len(data), limit)
            return data
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(stage_release, 'fetch', side_effect=fetch), \
             patch.object(stage_release.os, 'geteuid', return_value=1000), \
             patch.object(stage_release.Path, 'home', return_value=Path(tmp)):
            dest = stage_release.stage(COMMIT, hashlib.sha256(manifest).hexdigest(),
                                       Path(tmp) / '.local/state/fieldwork-pi-mcp/update-staging')
            receipt = json.loads((dest / 'receipt.json').read_text())
            self.assertEqual(receipt['status'], 'STAGED_NOT_INSTALLED')
            self.assertEqual(set(receipt['files']), {'stage_async.py', 'async_overlay.py'})


if __name__ == '__main__':
    unittest.main()
