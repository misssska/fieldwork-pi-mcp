"""Repository-local integrity check for the non-installing lifecycle candidate."""
import hashlib
import json
from pathlib import Path
import unittest

from updater.async_overlay import TOOLS_OLD as ATOOLS, ANNOTATION_OLD as AANN
from experimental.lifecycle_overlay import TOOLS_OLD as LTOOLS
from experimental.lifecycle_qualification import qualify, FILES


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'experimental/lifecycle_manifest.json'


def sha(value):
    return hashlib.sha256(value).hexdigest()


class PinnedLifecycleManifestTests(unittest.TestCase):
    def test_exact_pinned_file_inventory(self):
        obj = json.loads(MANIFEST.read_text())
        self.assertEqual(obj['schema'], 1)
        self.assertEqual(obj['purpose'], 'fieldwork-pi-mcp-lifecycle-static')
        self.assertEqual({e['path'] for e in obj['files']}, FILES)
        self.assertEqual(len(obj['files']), len(FILES))
        for entry in obj['files']:
            self.assertEqual(sha((ROOT / entry['path']).read_bytes()), entry['sha256'])

    def test_pinned_candidate_is_non_authorizing(self):
        main = ('import stage_manager\nTOOLS = [\n' + ATOOLS + LTOOLS + ']\n'
                + 'annotations = (' + AANN + ', "fieldwork_stage_stop")\n').encode()
        result = qualify(
            installed_source=main,
            expected_installed_sha256=sha(main),
            manifest_bytes=MANIFEST.read_bytes(),
            expected_manifest_sha256=sha(MANIFEST.read_bytes()),
            blobs={path: (ROOT / path).read_bytes() for path in FILES},
        )
        self.assertEqual(result['status'], 'LIFECYCLE_STATIC_QUALIFICATION_PASS')
        self.assertEqual(len(result['new_tools']), 5)
        self.assertFalse(result['activation_authorized'])
        self.assertFalse(result['mcp_modified'])
        self.assertFalse(result['production_modified'])
        self.assertFalse(result['tunnel_restarted'])


if __name__ == '__main__':
    unittest.main()
