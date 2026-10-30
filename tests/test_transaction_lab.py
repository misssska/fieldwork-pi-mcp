"""Fault injection and fail-closed tests for the isolated transaction engine."""
import hashlib
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from updater.transaction_lab import LabTransaction, TransactionError

OLD = b'original MCP\n'
NEW = b'new MCP\n'
EXT = b'extension\n'


class TransactionLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fieldwork-mcp-lab-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'mcp'
        self.root.mkdir(mode=0o700)
        self.main = self.root / 'fieldwork_mcp.py'
        self.main.write_bytes(OLD)
        self.tx = LabTransaction(self.root)

    def prepare(self):
        return self.tx.prepare(NEW, EXT, hashlib.sha256(OLD).hexdigest())

    def test_prepare_never_modifies_installed_source(self):
        self.prepare()
        self.assertEqual(self.main.read_bytes(), OLD)
        self.assertFalse((self.root / 'stage_async.py').exists())

    def test_apply_then_rollback(self):
        self.prepare()
        self.tx.apply(NEW, EXT)
        self.assertEqual(self.main.read_bytes(), NEW)
        self.assertEqual(self.tx.recover()['status'], 'ROLLED_BACK')
        self.assertEqual(self.main.read_bytes(), OLD)
        self.assertFalse((self.root / 'stage_async.py').exists())

    def test_crash_after_journal_recovers(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'SIMULATED_CRASH'):
            self.tx.apply(NEW, EXT, fail_at='after_journal')
        self.assertEqual(LabTransaction(self.root).recover()['status'], 'ROLLED_BACK')

    def test_crash_after_extension_recovers(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'SIMULATED_CRASH'):
            self.tx.apply(NEW, EXT, fail_at='after_extension')
        self.assertEqual(LabTransaction(self.root).recover()['status'], 'ROLLED_BACK')
        self.assertFalse((self.root / 'stage_async.py').exists())

    def test_crash_after_main_recovers(self):
        self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'SIMULATED_CRASH'):
            self.tx.apply(NEW, EXT, fail_at='after_main')
        self.assertEqual(LabTransaction(self.root).recover()['status'], 'ROLLED_BACK')
        self.assertEqual(self.main.read_bytes(), OLD)

    def test_real_subprocess_crash_then_recover(self):
        self.prepare()
        code = (
            'from pathlib import Path; '
            'from updater.transaction_lab import LabTransaction; '
            f'LabTransaction(Path({str(self.root)!r})).apply('
            f"{NEW!r}, {EXT!r}, fail_at='after_main')"
        )
        result = subprocess.run([sys.executable, '-c', code],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main.read_bytes(), NEW)
        self.assertEqual(LabTransaction(self.root).recover()['status'], 'ROLLED_BACK')
        self.assertEqual(self.main.read_bytes(), OLD)

    def test_wrong_installed_hash_denied(self):
        with self.assertRaisesRegex(TransactionError, 'INSTALLED_SOURCE_DRIFT'):
            self.tx.prepare(NEW, EXT, '0' * 64)

    def test_payload_tamper_denied(self):
        self.prepare()
        with self.assertRaisesRegex(TransactionError, 'PAYLOAD_HASH_MISMATCH'):
            self.tx.apply(b'evil', EXT)
        self.assertEqual(self.main.read_bytes(), OLD)

    def test_backup_tamper_denied(self):
        self.prepare()
        (self.root / '.transaction-backup').write_bytes(b'evil')
        with self.assertRaisesRegex(TransactionError, 'BACKUP_HASH_MISMATCH'):
            self.tx.apply(NEW, EXT)

    def test_unexpected_main_change_blocks_recovery(self):
        self.prepare()
        self.tx.apply(NEW, EXT)
        self.main.write_bytes(b'other change')
        with self.assertRaisesRegex(TransactionError, 'UNEXPECTED_MAIN_CHANGE'):
            self.tx.recover()

    def test_unexpected_extension_change_blocks_recovery(self):
        self.prepare()
        self.tx.apply(NEW, EXT)
        (self.root / 'stage_async.py').write_bytes(b'other change')
        with self.assertRaisesRegex(TransactionError, 'UNEXPECTED_EXTENSION_CHANGE'):
            self.tx.recover()

    def test_symlink_extension_denied(self):
        (self.root / 'stage_async.py').symlink_to(self.main)
        with self.assertRaisesRegex(TransactionError, 'EXTENSION_ALREADY_EXISTS'):
            self.prepare()

    def test_arbitrary_directory_denied(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaisesRegex(TransactionError, 'NON_TEST_DESTINATION_DENIED'):
                LabTransaction(Path(other))

    def test_duplicate_transaction_denied(self):
        self.prepare()
        with self.assertRaisesRegex(TransactionError, 'TRANSACTION_ALREADY_EXISTS'):
            self.prepare()

    def test_commit_marker_no_service_claim(self):
        self.prepare()
        self.tx.apply(NEW, EXT)
        self.assertEqual(self.tx.mark_health_verified_for_lab()['status'], 'COMMITTED')
        with self.assertRaisesRegex(TransactionError, 'TRANSACTION_NOT_RECOVERABLE'):
            self.tx.recover()

    def test_cannot_commit_before_apply(self):
        self.prepare()
        with self.assertRaisesRegex(TransactionError, 'NOT_APPLIED'):
            self.tx.mark_health_verified_for_lab()


if __name__ == '__main__':
    unittest.main()
