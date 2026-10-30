"""Fault-injection security tests for the four-runtime-file offline lifecycle lab."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from updater.lifecycle_transaction_lab import (
    FILES, MAIN, MODULES, LifecycleLabTransaction, LifecycleTransactionError,
)

ORIGINAL = b'original trusted MCP source\n'
PAYLOADS = {
    'fieldwork_mcp.py': b'new MCP source\n',
    'stage_async.py': b'async stage module\n',
    'stage_inspect.py': b'inspection module\n',
    'stage_start_async.py': b'async start module\n',
}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fieldwork-mcp-lifecycle-lab-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'mcp'
        self.root.mkdir(mode=0o700)
        (self.root / MAIN).write_bytes(ORIGINAL)
        self.tx = LifecycleLabTransaction(self.root)

    def prepare(self):
        return self.tx.prepare(PAYLOADS, hashlib.sha256(ORIGINAL).hexdigest())

    def test_prepare_does_not_change_runtime(self):
        self.assertEqual(self.prepare()['status'], 'LAB_PREPARED')
        self.assertEqual((self.root / MAIN).read_bytes(), ORIGINAL)
        for name in MODULES:
            self.assertFalse((self.root / name).exists())

    def test_full_apply_and_commit_is_not_activation(self):
        self.prepare()
        self.assertEqual(self.tx.apply(PAYLOADS)['status'], 'LAB_APPLIED_NOT_ACTIVATED')
        for name in FILES:
            self.assertEqual((self.root / name).read_bytes(), PAYLOADS[name])
        result = self.tx.mark_lab_verified()
        self.assertEqual(result['status'], 'LAB_BYTES_VERIFIED_ONLY')
        self.assertFalse(result['activation_authorized'])
        self.assertFalse(result['mcp_modified'])
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_NOT_RECOVERABLE'):
            self.tx.recover()

    def test_rollback_after_completed_apply(self):
        self.prepare()
        self.tx.apply(PAYLOADS)
        self.assertEqual(self.tx.recover()['status'], 'LAB_ROLLED_BACK')
        self.assertEqual((self.root / MAIN).read_bytes(), ORIGINAL)
        for name in MODULES:
            self.assertFalse((self.root / name).exists())

    def test_rollback_before_any_writes(self):
        self.prepare()
        self.tx.recover()
        self.assertEqual((self.root / MAIN).read_bytes(), ORIGINAL)

    def test_every_crash_point_recovers_from_new_instance(self):
        for crash in ('after_journal', *(f'after_{name}' for name in MODULES),
                      'after_main', 'after_applied'):
            with self.subTest(crash=crash):
                with tempfile.TemporaryDirectory(prefix='fieldwork-mcp-lifecycle-lab-') as t:
                    root = Path(t) / 'mcp'
                    root.mkdir(mode=0o700)
                    (root / MAIN).write_bytes(ORIGINAL)
                    transaction = LifecycleLabTransaction(root)
                    transaction.prepare(PAYLOADS, hashlib.sha256(ORIGINAL).hexdigest())
                    with self.assertRaisesRegex(RuntimeError, 'SIMULATED_CRASH'):
                        transaction.apply(PAYLOADS, fail_at=crash)
                    restarted = LifecycleLabTransaction(root)
                    self.assertEqual(restarted.recover()['state'], 'ROLLED_BACK')
                    self.assertEqual((root / MAIN).read_bytes(), ORIGINAL)
                    for name in MODULES:
                        self.assertFalse((root / name).exists())

    def test_real_process_failure_then_recovery(self):
        self.prepare()
        code = ("from pathlib import Path; from updater.lifecycle_transaction_lab "
                "import LifecycleLabTransaction; "
                f"LifecycleLabTransaction(Path({str(self.root)!r})).apply("
                f"{PAYLOADS!r}, fail_at='after_main')")
        process = subprocess.run([sys.executable, '-c', code],
                                 cwd=Path(__file__).resolve().parents[1],
                                 capture_output=True, timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual((self.root / MAIN).read_bytes(), PAYLOADS[MAIN])
        self.tx.recover()
        self.assertEqual((self.root / MAIN).read_bytes(), ORIGINAL)

    def test_payload_missing_or_extra_denied(self):
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_PAYLOAD_SET_DENIED'):
            self.tx.prepare({MAIN: b'new'}, hashlib.sha256(ORIGINAL).hexdigest())

    def test_wrong_installed_hash_denied(self):
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_ORIGINAL_SOURCE_DRIFT'):
            self.tx.prepare(PAYLOADS, 'f' * 64)

    def test_candidate_tamper_denied(self):
        self.prepare()
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_PAYLOAD_DRIFT'):
            self.tx.apply({**PAYLOADS, MODULES[0]: b'tampered'})
        self.assertEqual((self.root / MAIN).read_bytes(), ORIGINAL)

    def test_backup_tamper_denied(self):
        self.prepare()
        (self.root / '.lifecycle-original-backup').write_bytes(b'tampered')
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_BACKUP_DRIFT'):
            self.tx.apply(PAYLOADS)

    def test_module_tamper_refuses_partial_rollback(self):
        self.prepare()
        self.tx.apply(PAYLOADS)
        (self.root / MODULES[0]).write_bytes(b'tampered')
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_UNEXPECTED_MODULE_CHANGE'):
            self.tx.recover()
        self.assertEqual((self.root / MAIN).read_bytes(), PAYLOADS[MAIN])

    def test_main_tamper_refuses_rollback(self):
        self.prepare()
        self.tx.apply(PAYLOADS)
        (self.root / MAIN).write_bytes(b'concurrent user change')
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_UNEXPECTED_MAIN_CHANGE'):
            self.tx.recover()

    def test_symlink_module_blocked(self):
        (self.root / MODULES[0]).symlink_to(self.root / MAIN)
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_MODULE_ALREADY_PRESENT'):
            self.prepare()

    def test_duplicate_prepare_blocked(self):
        self.prepare()
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_ALREADY_PREPARED'):
            self.prepare()

    def test_no_implicit_health_authorization(self):
        self.prepare()
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_NOT_APPLIED'):
            self.tx.mark_lab_verified()

    def test_non_lab_paths_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(LifecycleTransactionError, 'NON_LAB_DESTINATION_DENIED'):
                LifecycleLabTransaction(Path(temp))

    def test_journal_tamper_denied(self):
        self.prepare()
        (self.root / '.lifecycle-transaction.json').write_bytes(b'{}')
        with self.assertRaisesRegex(LifecycleTransactionError, 'LAB_JOURNAL_SCHEMA_DENIED'):
            self.tx.apply(PAYLOADS)

    def test_symlink_lock_denied(self):
        (self.root / '.lifecycle-transaction.lock').symlink_to(self.root / MAIN)
        with self.assertRaises(OSError):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
