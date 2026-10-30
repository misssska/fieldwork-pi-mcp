"""Activation plan tests: no host, Docker, systemd or production operations."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from updater.activation_plan import ActivationBlocked, build_plan

COMMIT = 'a' * 40
MANIFEST = 'b' * 64
OLD = b'import stage_manager\n'
NEW = b'import stage_manager\nimport stage_async\n'
EXT = b'def request(args): return {}\n'


def sha(value):
    return hashlib.sha256(value).hexdigest()


class ActivationPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fieldwork_mcp.py'
        self.path.write_bytes(OLD)
        self.q = {
            'status': 'STATIC_QUALIFICATION_PASS', 'commit': COMMIT,
            'release_manifest_sha256': MANIFEST, 'activation_authorized': False,
            'production_modified': False, 'mcp_modified': False,
            'tunnel_restarted': False, 'installed_source_sha256': sha(OLD),
            'candidate_source_sha256': sha(NEW), 'stage_async_sha256': sha(EXT),
        }

    def plan(self):
        return build_plan(installed=self.path, candidate=NEW, extension=EXT,
                          qualification=self.q, commit=COMMIT,
                          manifest_sha256=MANIFEST)

    def test_success_no_write(self):
        result = self.plan()
        self.assertEqual(result['status'], 'DRY_RUN_PLAN_ONLY')
        self.assertFalse(result['activation_authorized'])
        self.assertEqual(self.path.read_bytes(), OLD)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()),
                         ['fieldwork_mcp.py'])

    def test_installed_drift(self):
        self.path.write_bytes(b'x=2\n')
        with self.assertRaisesRegex(ActivationBlocked, 'INSTALLED_SOURCE_CHANGED'):
            self.plan()

    def test_candidate_tamper(self):
        self.q['candidate_source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ActivationBlocked, 'CANDIDATE_HASH_MISMATCH'):
            self.plan()

    def test_extension_tamper(self):
        self.q['stage_async_sha256'] = '0' * 64
        with self.assertRaisesRegex(ActivationBlocked, 'EXTENSION_HASH_MISMATCH'):
            self.plan()

    def test_approval_not_implicitly_granted(self):
        self.q['activation_authorized'] = True
        with self.assertRaisesRegex(ActivationBlocked, 'QUALIFICATION_FLAGS_UNEXPECTED'):
            self.plan()

    def test_qualification_release_mismatch(self):
        self.q['commit'] = 'c' * 40
        with self.assertRaisesRegex(ActivationBlocked, 'QUALIFICATION_RELEASE_MISMATCH'):
            self.plan()

    def test_unqualified(self):
        self.q['status'] = 'FAILED'
        with self.assertRaisesRegex(ActivationBlocked, 'QUALIFICATION_NOT_PASSED'):
            self.plan()

    def test_symlink_installed_denied(self):
        real = self.path.parent / 'real.py'
        real.write_bytes(OLD)
        self.path.unlink()
        self.path.symlink_to(real)
        with self.assertRaisesRegex(ActivationBlocked, 'SOURCE_MISSING_OR_SYMLINK'):
            self.plan()

    def test_extension_already_exists(self):
        (self.path.parent / 'stage_async.py').write_bytes(EXT)
        with self.assertRaisesRegex(ActivationBlocked, 'EXTENSION_ALREADY_PRESENT'):
            self.plan()

    def test_invalid_commit(self):
        with self.assertRaisesRegex(ActivationBlocked, 'COMMIT_REQUIRED'):
            build_plan(installed=self.path, candidate=NEW, extension=EXT,
                       qualification=self.q, commit='main',
                       manifest_sha256=MANIFEST)

    def test_invalid_manifest_hash(self):
        with self.assertRaisesRegex(ActivationBlocked, 'MANIFEST_HASH_REQUIRED'):
            build_plan(installed=self.path, candidate=NEW, extension=EXT,
                       qualification=self.q, commit=COMMIT,
                       manifest_sha256='latest')

    def test_oversized_candidate(self):
        with self.assertRaisesRegex(ActivationBlocked, 'CANDIDATE_TOO_LARGE'):
            build_plan(installed=self.path, candidate=b'a' * 1_000_001,
                       extension=EXT, qualification=self.q, commit=COMMIT,
                       manifest_sha256=MANIFEST)


if __name__ == '__main__':
    unittest.main()
