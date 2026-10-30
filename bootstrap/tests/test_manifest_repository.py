"""CI gate: manifest must pin the exact checked-in updater bytes."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RepoIntegrityTests(unittest.TestCase):
    def test_manifest_pins_every_updater_module(self):
        manifest = json.loads((ROOT / 'bootstrap/manifest.json').read_text())
        self.assertEqual(manifest['schema'], 1)
        paths = {entry['path'] for entry in manifest['files']}
        self.assertEqual(paths, {
            'updater/stage_release.py',
            'updater/compatibility.py',
            'updater/async_overlay.py',
        })
        for entry in manifest['files']:
            path = ROOT / entry['path']
            self.assertTrue(path.is_file(), entry['path'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             entry['sha256'], entry['path'])

    def test_no_production_path_in_bootstrap(self):
        code = (ROOT / 'bootstrap/bootstrap.py').read_text()
        self.assertNotIn('/opt/fieldwork', code)
        self.assertNotIn('systemctl', code)
        self.assertNotIn('docker ', code)


if __name__ == '__main__':
    unittest.main()
