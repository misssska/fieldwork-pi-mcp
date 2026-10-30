"""Portable offline tests for SHA-pinned lifecycle candidate qualification."""
import hashlib
import json
import unittest
from pathlib import Path

from updater.async_overlay import TOOLS_OLD as ATOOLS, ANNOTATION_OLD as AANN
from experimental.lifecycle_overlay import TOOLS_OLD as LTOOLS
from experimental.lifecycle_qualification import qualify, QualificationBlocked, FILES

BASE = ('import stage_manager\nTOOLS = [\n' + ATOOLS + LTOOLS + ']\n'
        + 'annotations = (' + AANN + ', "fieldwork_stage_stop")\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fixture():
    blobs = {name: b'pass\n' for name in FILES}
    blobs['release/async_overlay.py'] = Path('updater/async_overlay.py').read_bytes()
    blobs['experimental/lifecycle_overlay.py'] = Path('experimental/lifecycle_overlay.py').read_bytes()
    manifest = json.dumps({
        'schema': 1, 'purpose': 'fieldwork-pi-mcp-lifecycle-static',
        'files': [{'path': key, 'sha256': sha(value)}
                  for key, value in sorted(blobs.items())],
    }, sort_keys=True).encode()
    return dict(installed_source=BASE, expected_installed_sha256=sha(BASE),
                manifest_bytes=manifest, expected_manifest_sha256=sha(manifest),
                blobs=blobs)


class QualificationTests(unittest.TestCase):
    def test_pass_never_authorizes(self):
        result = qualify(**fixture())
        self.assertEqual(result['status'], 'LIFECYCLE_STATIC_QUALIFICATION_PASS')
        self.assertEqual(len(result['new_tools']), 5)
        self.assertFalse(result['activation_authorized'])
        self.assertFalse(result['production_modified'])

    def test_installed_drift(self):
        args = fixture()
        args['installed_source'] += b'# changed\n'
        with self.assertRaisesRegex(QualificationBlocked, 'INSTALLED_SOURCE_DRIFT'):
            qualify(**args)

    def test_manifest_tamper(self):
        args = fixture()
        args['manifest_bytes'] += b' '
        with self.assertRaisesRegex(QualificationBlocked, 'MANIFEST_HASH_MISMATCH'):
            qualify(**args)

    def test_bundle_tamper(self):
        args = fixture()
        args['blobs']['experimental/stage_inspect.py'] += b'# changed\n'
        with self.assertRaisesRegex(QualificationBlocked, 'BUNDLE_HASH_MISMATCH'):
            qualify(**args)

    def test_missing_module(self):
        args = fixture()
        del args['blobs']['experimental/stage_start_async.py']
        with self.assertRaisesRegex(QualificationBlocked, 'BUNDLE_FILE_SET_DENIED'):
            qualify(**args)

    def test_overlay_implementation_drift(self):
        args = fixture()
        data = args['blobs']['experimental/lifecycle_overlay.py'] + b'\n# changed\n'
        args['blobs']['experimental/lifecycle_overlay.py'] = data
        obj = json.loads(args['manifest_bytes'])
        next(entry for entry in obj['files']
             if entry['path'] == 'experimental/lifecycle_overlay.py')['sha256'] = sha(data)
        args['manifest_bytes'] = json.dumps(obj, sort_keys=True).encode()
        args['expected_manifest_sha256'] = sha(args['manifest_bytes'])
        with self.assertRaisesRegex(QualificationBlocked, 'LIFECYCLE_OVERLAY_IMPLEMENTATION_DRIFT'):
            qualify(**args)

    def test_wrong_purpose(self):
        args = fixture()
        obj = json.loads(args['manifest_bytes'])
        obj['purpose'] = 'install'
        args['manifest_bytes'] = json.dumps(obj).encode()
        args['expected_manifest_sha256'] = sha(args['manifest_bytes'])
        with self.assertRaisesRegex(QualificationBlocked, 'MANIFEST_PURPOSE_DENIED'):
            qualify(**args)

    def test_extra_bundle_file(self):
        args = fixture()
        args['blobs']['/opt/fieldwork/.env'] = b'secret'
        with self.assertRaisesRegex(QualificationBlocked, 'BUNDLE_FILE_SET_DENIED'):
            qualify(**args)

    def test_duplicate_tool_denied(self):
        args = fixture()
        args['installed_source'] = BASE.replace(
            b'TOOLS = [\n', b'TOOLS = [\n    ("fieldwork_stage_inspect", {}, None),\n')
        args['expected_installed_sha256'] = sha(args['installed_source'])
        with self.assertRaisesRegex(QualificationBlocked, 'CANDIDATE_INCOMPATIBLE'):
            qualify(**args)


if __name__ == '__main__':
    unittest.main()
