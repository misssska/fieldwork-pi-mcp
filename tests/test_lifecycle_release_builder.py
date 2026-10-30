"""Offline review ZIP builder: deterministic packaging and adversarial tamper tests.

All test inputs are synthetic. Tests never touch Pi MCP, Docker, systemd or
production files. Exact release ZIP bytes are separately qualified.
"""
from __future__ import annotations

from contextlib import ExitStack
from io import BytesIO
import hashlib
import json
from unittest.mock import patch
import unittest
import zipfile

from updater import lifecycle_release_builder as b

ORIGINAL = b'def installed_mcp():\n    return 1\n'
CANDIDATE = b'def candidate_mcp():\n    return 2\n'
MODULES = {
    'release/stage_async.py': b'def test_async():\n    return 3\n',
    'release/async_overlay.py': b'def overlay(data):\n    return data\n',
    'experimental/stage_inspect.py': b'def inspect():\n    return 4\n',
    'experimental/stage_start_async.py': b'def start():\n    return 5\n',
    'experimental/lifecycle_overlay.py': b'def overlay(data):\n    return data\n',
}
MANIFEST_SHA = '3' * 64


class ReleaseBuilderTests(unittest.TestCase):
    def setUp(self):
        self.mocks = ExitStack()
        self.addCleanup(self.mocks.close)
        self.mocks.enter_context(patch.object(
            b, 'PINNED_MANIFEST_SHA256', MANIFEST_SHA))
        self.mocks.enter_context(patch.object(
            b, 'PINNED_MODULE_SHA256', {
                target: b.sha(MODULES[src])
                for target, src in b.MODULE_PATHS.items()}))
        self.mocks.enter_context(patch.object(
            b.schemafix_lineage, 'SCHEMAFIX_SHA', b.sha(ORIGINAL)))
        self.mocks.enter_context(patch.object(
            b.schemafix_lineage, 'LIFECYCLE_SCHEMAFIX_SHA', b.sha(CANDIDATE)))
        self.mocks.enter_context(patch.object(
            b.qualfication if hasattr(b, 'qualfication') else b.qualification,
            'qualify', return_value={
                'status': 'LIFECYCLE_STATIC_QUALIFICATION_PASS',
                'candidate_sha256': b.sha(CANDIDATE),
                'activation_authorized': False, 'mcp_modified': False,
            }))
        self.mocks.enter_context(patch.object(
            b.async_overlay, 'overlay', return_value=b'first overlay'))
        self.mocks.enter_context(patch.object(
            b.lifecycle_overlay, 'overlay', return_value=CANDIDATE))

    def build(self, **extra):
        payload = dict(source=ORIGINAL, manifest=b'ignored by fake qualifier',
                       expected_manifest_sha256=MANIFEST_SHA,
                       modules=dict(MODULES))
        payload.update(extra)
        return b.build(**payload)

    def test_build_and_verify_fixed_files(self):
        packed, status = self.build()
        self.assertEqual(status['status'], 'REVIEW_ZIP_READY_NOT_INSTALLABLE')
        self.assertFalse(status['activation_authorized'])
        self.assertEqual(status['zip_sha256'], b.sha(packed))
        result = b.verify(packed, expected_manifest_sha256=MANIFEST_SHA)
        self.assertEqual(result['status'],
                         'ARCHIVE_BYTE_INTEGRITY_PASS_NOT_AUTHORIZED')
        with zipfile.ZipFile(BytesIO(packed)) as archive:
            self.assertEqual(set(archive.namelist()), b.ZIP_NAMES)
            self.assertEqual(archive.read('fieldwork_mcp.py'), CANDIDATE)
            record = json.loads(archive.read(b.META_NAME))
            self.assertFalse(record['real_pi_readiness_verified'])
            self.assertEqual(record['source_sha256'], b.sha(ORIGINAL))

    def test_deterministic_same_bytes_across_two_runs(self):
        one, _ = self.build()
        two, _ = self.build()
        self.assertEqual(one, two)

    def test_untrusted_manifest_denied_even_if_syntactically_valid(self):
        with self.assertRaisesRegex(b.BundleRejected, 'UNTRUSTED_RELEASE_MANIFEST'):
            self.build(expected_manifest_sha256='a' * 64)

    def test_source_drift_denied(self):
        with self.assertRaisesRegex(b.BundleRejected, 'SCHEMAFIX_SOURCE_HASH_DENIED'):
            self.build(source=ORIGINAL + b'# tampered\n')

    def test_missing_module_denied(self):
        reduced = dict(MODULES)
        reduced.pop('release/stage_async.py')
        with self.assertRaisesRegex(b.BundleRejected, 'MODULE_FILE_SET_DENIED'):
            self.build(modules=reduced)

    def test_wrong_qualification_denied(self):
        with patch.object(b.qualification, 'qualify', return_value={
                'status': 'LIFECYCLE_STATIC_QUALIFICATION_PASS',
                'candidate_sha256': b.sha(CANDIDATE),
                'activation_authorized': True, 'mcp_modified': False}):
            with self.assertRaisesRegex(b.BundleRejected, 'QUALIFICATION_DENIED'):
                self.build()

    def test_mismatched_qualification_hash_denied(self):
        with patch.object(b.qualification, 'qualify', return_value={
                'status': 'LIFECYCLE_STATIC_QUALIFICATION_PASS',
                'candidate_sha256': '0' * 64,
                'activation_authorized': False, 'mcp_modified': False}):
            with self.assertRaisesRegex(b.BundleRejected, 'QUALIFICATION_CANDIDATE_DRIFT'):
                self.build()

    def test_wrong_candidate_hash_denied(self):
        with patch.object(b.schemafix_lineage, 'LIFECYCLE_SCHEMAFIX_SHA', 'f' * 64):
            with self.assertRaisesRegex(b.BundleRejected, 'CANDIDATE_SHA_DENIED'):
                self.build()

    def test_invalid_payload_python_denied(self):
        modules = dict(MODULES)
        modules['experimental/stage_inspect.py'] = b'def broken(:'
        with self.assertRaisesRegex(b.BundleRejected,
                                    'INVALID_PYTHON:stage_inspect.py'):
            self.build(modules=modules)

    def test_tampered_zip_file_hash_denied(self):
        packed, _ = self.build()
        with zipfile.ZipFile(BytesIO(packed)) as source:
            members = [(entry, source.read(entry)) for entry in source.namelist()]
        output = BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, raw in members:
                info = zipfile.ZipInfo(name, date_time=b.TIMESTAMP)
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                info.compress_type = zipfile.ZIP_STORED
                if name == 'stage_async.py':
                    raw += b'#tamper\n'
                archive.writestr(info, raw)
        with self.assertRaisesRegex(b.BundleRejected, 'PAYLOAD_HASH_MISMATCH'):
            b.verify(output.getvalue(), expected_manifest_sha256=MANIFEST_SHA)

    def test_payload_plus_self_declared_manifest_hash_tamper_denied(self):
        """Updating both the ZIP file and its own manifest must NOT bypass pinning."""
        packed, _ = self.build()
        with zipfile.ZipFile(BytesIO(packed)) as source:
            members = [(entry, source.read(entry)) for entry in source.namelist()]
        output = BytesIO()
        altered = b'def malicious_stage_inspect():\n    return True\n'
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, raw in members:
                info = zipfile.ZipInfo(name, date_time=b.TIMESTAMP)
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                info.compress_type = zipfile.ZIP_STORED
                if name == 'stage_inspect.py':
                    raw = altered
                elif name == b.META_NAME:
                    metadata = json.loads(raw)
                    metadata['files']['stage_inspect.py'] = b.sha(altered)
                    raw = b._json(metadata)
                archive.writestr(info, raw)
        with self.assertRaisesRegex(b.BundleRejected,
                                    'TRUSTED_MODULE_HASH_MISMATCH:stage_inspect.py'):
            b.verify(output.getvalue(), expected_manifest_sha256=MANIFEST_SHA)

    def test_verify_untrusted_manifest_denied_even_when_well_formed(self):
        packed, _ = self.build()
        with self.assertRaisesRegex(b.BundleRejected, 'UNTRUSTED_RELEASE_MANIFEST'):
            b.verify(packed, expected_manifest_sha256='f' * 64)

    def test_wrong_manifest_pin_denied(self):
        packed, _ = self.build()
        with self.assertRaisesRegex(b.BundleRejected, 'UNTRUSTED_RELEASE_MANIFEST'):
            b.verify(packed, expected_manifest_sha256='4' * 64)

    def test_duplicate_member_denied(self):
        packed, _ = self.build()
        with zipfile.ZipFile(BytesIO(packed)) as archive:
            items = [(name, archive.read(name)) for name in archive.namelist()]
        output = BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, raw in items:
                info = zipfile.ZipInfo(name, b.TIMESTAMP)
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                archive.writestr(info, raw)
            info = zipfile.ZipInfo('fieldwork_mcp.py', b.TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, CANDIDATE)
        with self.assertRaisesRegex(b.BundleRejected, 'ARCHIVE_FILE_SET_DENIED'):
            b.verify(output.getvalue(), expected_manifest_sha256=MANIFEST_SHA)

    def test_added_path_traversal_denied(self):
        packed, _ = self.build()
        with zipfile.ZipFile(BytesIO(packed)) as archive:
            items = [(name, archive.read(name)) for name in archive.namelist()]
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, raw in items:
                info = zipfile.ZipInfo(name, b.TIMESTAMP)
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                archive.writestr(info, raw)
            archive.writestr('../escape', b'bad')
        with self.assertRaisesRegex(b.BundleRejected, 'ARCHIVE_FILE_SET_DENIED'):
            b.verify(output.getvalue(), expected_manifest_sha256=MANIFEST_SHA)

    def test_truncated_zip_denied(self):
        with self.assertRaisesRegex(b.BundleRejected, 'ARCHIVE_INVALID'):
            b.verify(b'not-a-zip', expected_manifest_sha256=MANIFEST_SHA)

    def test_unexpected_archive_mode_denied(self):
        packed, _ = self.build()
        with zipfile.ZipFile(BytesIO(packed)) as source:
            members = [(name, source.read(name)) for name in source.namelist()]
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, raw in members:
                info = zipfile.ZipInfo(name, b.TIMESTAMP)
                info.create_system = 3
                info.external_attr = ((0o120777 if name == 'stage_async.py'
                                       else 0o100600) << 16)
                archive.writestr(info, raw)
        with self.assertRaisesRegex(b.BundleRejected, 'ARCHIVE_ENTRY_UNSAFE'):
            b.verify(output.getvalue(), expected_manifest_sha256=MANIFEST_SHA)

    def test_malformed_manifest_pin_denied(self):
        packed, _ = self.build()
        with self.assertRaisesRegex(b.BundleRejected, 'MANIFEST_PIN_DENIED'):
            b.verify(packed, expected_manifest_sha256='bad')
        with self.assertRaisesRegex(b.BundleRejected, 'MANIFEST_PIN_DENIED'):
            b.verify(packed, expected_manifest_sha256='F' * 64)

    def test_no_arbitrary_paths_in_release(self):
        packed, status = self.build()
        with zipfile.ZipFile(BytesIO(packed)) as archive:
            self.assertEqual(len(archive.namelist()), 5)
            self.assertFalse(any('/' in name for name in archive.namelist()))
            self.assertFalse(status['production_modified'])


if __name__ == '__main__':
    unittest.main()
