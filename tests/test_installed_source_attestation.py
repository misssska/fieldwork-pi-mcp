"""Regression and security tests for read-only installed source attestation."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from updater import installed_source_attestation as a


class SourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pi-attestation-lab-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / a.RELATIVE_SOURCE
        self.path.parent.mkdir(parents=True, mode=0o700)
        self.path.write_text('''TOOLS = [
    ("fieldwork_stage_test_request", "safe", {}, None),
    ("fieldwork_stage_test_status", "safe", {}, None),
]
def status():
    return "super-secret-token-must-not-appear"
''')
        self.uid = os.getuid()

    def inspect(self):
        with patch.object(a.os, 'geteuid', return_value=1001):
            return a.inspect(home=self.home, uid=self.uid)

    def test_unreviewed_hash_fails_closed(self):
        x = self.inspect()
        self.assertEqual(x['status'], 'UNKNOWN_SOURCE_HASH')
        self.assertFalse(x['activation_authorized'])
        self.assertFalse(x['source_reviewed'])
        self.assertEqual(x['stage_registration_tuple_counts']['fieldwork_stage_test_request'], 1)
        self.assertNotIn('super-secret-token', str(x))

    def test_never_executes_installed_source(self):
        self.path.write_text('raise RuntimeError("should never execute")\n')
        self.assertEqual(self.inspect()['status'], 'UNKNOWN_SOURCE_HASH')

    def test_syntax_error_blocked(self):
        self.path.write_text('def foo(:\n')
        self.assertEqual(self.inspect()['reason'], 'INVALID_PYTHON')

    def test_oversize_source_blocked(self):
        self.path.write_bytes(b'a' * (a.MAX_BYTES + 1))
        self.assertEqual(self.inspect()['reason'], 'SOURCE_SIZE_DENIED')

    def test_empty_source_blocked(self):
        self.path.write_bytes(b'')
        self.assertEqual(self.inspect()['reason'], 'SOURCE_SIZE_DENIED')

    def test_symlink_source_blocked(self):
        other = self.home / 'other.py'
        other.write_text('print(1)\n')
        self.path.unlink()
        self.path.symlink_to(other)
        self.assertEqual(self.inspect()['status'], 'BLOCKED')

    def test_symlink_parent_blocked(self):
        parent = self.path.parent
        replacement = self.home / 'replacement'
        parent.rename(replacement)
        parent.symlink_to(replacement, target_is_directory=True)
        self.assertEqual(self.inspect()['reason'], 'UNSAFE_PARENT_TYPE')

    def test_group_writable_source_blocked(self):
        self.path.chmod(0o664)
        self.assertEqual(self.inspect()['reason'], 'UNSAFE_SOURCE_MODE')

    def test_group_writable_parent_blocked(self):
        self.path.parent.chmod(0o777)
        self.assertEqual(self.inspect()['reason'], 'UNSAFE_PARENT_MODE')

    def test_hardlink_source_blocked(self):
        os.link(self.path, self.home / 'hardlink.py')
        self.assertEqual(self.inspect()['reason'], 'UNSAFE_SOURCE_TYPE')

    def test_missing_source_blocked(self):
        self.path.unlink()
        self.assertEqual(self.inspect()['status'], 'BLOCKED')

    def test_root_denied(self):
        with patch.object(a.os, 'geteuid', return_value=0):
            self.assertEqual(a.inspect(home=self.home, uid=self.uid)['reason'],
                             'ROOT_EXECUTION_DENIED')

    def test_foreign_owner_denied(self):
        with patch.object(a.os, 'geteuid', return_value=1001):
            self.assertEqual(a.inspect(home=self.home, uid=self.uid + 100)['status'],
                             'BLOCKED')

    def test_duplicate_stage_tuples_only_counted(self):
        self.path.write_text('x=[("fieldwork_stage_inspect",), ("fieldwork_stage_inspect",)]')
        x = self.inspect()
        self.assertEqual(x['stage_registration_tuple_counts']['fieldwork_stage_inspect'], 2)
        self.assertFalse(x['activation_authorized'])

    def test_fixed_source_path_denial(self):
        with self.assertRaisesRegex(a.AuditBlocked, 'SOURCE_PATH_DENIED'):
            a._safe_ancestors(self.home / 'another.py', self.home, self.uid)


if __name__ == '__main__':
    unittest.main()
