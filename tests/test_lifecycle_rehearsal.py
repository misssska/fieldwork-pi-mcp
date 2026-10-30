"""End-to-end LAB ONLY: signature binding, one-use claim, simulated health, rollback."""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
from pathlib import Path
import unittest

from updater import lifecycle_rehearsal as lab
from updater import local_approval_lab as approval
from updater.lifecycle_transaction_lab import (
    LifecycleLabTransaction, LifecycleTransactionError, MAIN, MODULES,
)

KEY = b'L' * 32
COMMIT = 'a' * 40
MANIFEST = 'b' * 64
ORIGINAL = b'original MCP source\n'
FILES = {
    'fieldwork_mcp.py': b'candidate MCP source\n',
    'stage_async.py': b'async stage\n',
    'stage_inspect.py': b'fixed stage inspection\n',
    'stage_start_async.py': b'async stage start\n',
}
ORIGINAL_SHA = hashlib.sha256(ORIGINAL).hexdigest()


def sign(payload, key=KEY):
    return {'payload': payload, 'mac': hmac.new(
        key, approval.canonical(payload), hashlib.sha256).hexdigest()}


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fieldwork-mcp-lifecycle-lab-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'mcp'
        self.root.mkdir(mode=0o700)
        (self.root / MAIN).write_bytes(ORIGINAL)
        self.payloads = dict(FILES)
        self.expected = lab.pins(commit=COMMIT, manifest_sha256=MANIFEST,
                                 installed_sha256=ORIGINAL_SHA,
                                 payloads=self.payloads)
        now = int(time.time())
        self.token = sign({'schema': 1, 'purpose': approval.PURPOSE,
                           **self.expected, 'nonce': '1' * 32,
                           'issued_at': now - 5, 'expires_at': now + 120})

    def run_lab(self, **overrides):
        args = {'root': self.root, 'payloads': self.payloads,
                'installed_sha256': ORIGINAL_SHA, 'commit': COMMIT,
                'manifest_sha256': MANIFEST, 'token': self.token, 'lab_key': KEY,
                'simulated_health': 'pass'}
        args.update(overrides)
        return lab.rehearse(**args)

    def assert_original(self):
        self.assertEqual((self.root / MAIN).read_bytes(), ORIGINAL)
        for name in MODULES:
            self.assertFalse((self.root / name).exists(), name)

    def test_signed_simulated_success_is_not_real_activation(self):
        result = self.run_lab()
        self.assertEqual(result['status'], 'LAB_SIMULATED_HEALTH_PASS_BYTES_VERIFIED')
        self.assertFalse(result['real_health_verified'])
        self.assertFalse(result['local_activation_authorized'])
        self.assertFalse(result['mcp_modified'])
        for name, value in FILES.items():
            self.assertEqual((self.root / name).read_bytes(), value)

    def test_simulated_health_fail_rolls_back(self):
        result = self.run_lab(simulated_health='fail')
        self.assertEqual(result['status'], 'LAB_SIMULATED_HEALTH_FAIL_ROLLED_BACK')
        self.assert_original()

    def test_simulated_health_error_rolls_back(self):
        result = self.run_lab(simulated_health='error')
        self.assertEqual(result['status'], 'LAB_SIMULATED_HEALTH_ERROR_ROLLED_BACK')
        self.assert_original()

    def test_injected_crashes_all_recover(self):
        crashes = ('after_journal', *(f'after_{name}' for name in MODULES),
                   'after_main', 'after_applied')
        for crash in crashes:
            with self.subTest(crash=crash):
                with tempfile.TemporaryDirectory(
                    prefix='fieldwork-mcp-lifecycle-lab-'
                ) as tmp:
                    root = Path(tmp) / 'mcp'
                    root.mkdir(mode=0o700)
                    (root / MAIN).write_bytes(ORIGINAL)
                    with self.assertRaisesRegex(RuntimeError, 'SIMULATED_CRASH'):
                        self.run_lab(root=root, fail_at=crash)
                    self.assertEqual((root / MAIN).read_bytes(), ORIGINAL)
                    for filename in MODULES:
                        self.assertFalse((root / filename).exists())

    def test_bad_signature_blocks_all_changes(self):
        token = dict(self.token)
        token['mac'] = '0' * 64
        with self.assertRaisesRegex(approval.ApprovalDenied, 'SIGNATURE_DENIED'):
            self.run_lab(token=token)
        self.assert_original()
        self.assertFalse(list(self.root.glob('.lab-approval-used-*')))

    def test_replay_rejected_even_after_health_failure(self):
        self.run_lab(simulated_health='fail')
        self.assert_original()
        with self.assertRaisesRegex(lab.RehearsalDenied, 'LAB_APPROVAL_REPLAY_DENIED'):
            self.run_lab()
        self.assert_original()

    def test_module_payload_tamper_denied_before_write(self):
        self.payloads['stage_inspect.py'] = b'evil'
        with self.assertRaisesRegex(approval.ApprovalDenied,
                                    'PIN_MISMATCH:extension_sha256'):
            self.run_lab()
        self.assert_original()

    def test_main_payload_tamper_denied_before_write(self):
        self.payloads[MAIN] = b'evil main'
        with self.assertRaisesRegex(approval.ApprovalDenied,
                                    'PIN_MISMATCH:candidate_sha256'):
            self.run_lab()
        self.assert_original()

    def test_wrong_commit_denied(self):
        with self.assertRaisesRegex(approval.ApprovalDenied, 'PIN_MISMATCH:commit'):
            self.run_lab(commit='f' * 40)
        self.assert_original()

    def test_wrong_manifest_denied(self):
        with self.assertRaisesRegex(approval.ApprovalDenied,
                                    'PIN_MISMATCH:manifest_sha256'):
            self.run_lab(manifest_sha256='f' * 64)
        self.assert_original()

    def test_wrong_installed_pin_denied(self):
        with self.assertRaisesRegex(approval.ApprovalDenied,
                                    'PIN_MISMATCH:installed_sha256'):
            self.run_lab(installed_sha256='f' * 64)
        self.assert_original()

    def test_installed_source_changed_after_proof(self):
        (self.root / MAIN).write_bytes(b'concurrent edit')
        with self.assertRaisesRegex(LifecycleTransactionError,
                                    'LAB_ORIGINAL_SOURCE_DRIFT'):
            self.run_lab()
        self.assertEqual((self.root / MAIN).read_bytes(), b'concurrent edit')
        self.assertFalse((self.root / 'stage_async.py').exists())

    def test_expired_proof_denied(self):
        now = int(time.time())
        expired = {**self.token['payload'],
                   'issued_at': now - 200, 'expires_at': now - 100}
        with self.assertRaisesRegex(approval.ApprovalDenied,
                                    'EXPIRED_OR_INVALID_WINDOW'):
            self.run_lab(token=sign(expired))
        self.assert_original()

    def test_untrusted_unsigned_token_denied(self):
        with self.assertRaisesRegex(approval.ApprovalDenied, 'TOKEN_SCHEMA_DENIED'):
            self.run_lab(token={'payload': self.token['payload']})
        self.assert_original()

    def test_extra_token_field_denied(self):
        p = {**self.token['payload'], 'command': 'sh'}
        with self.assertRaisesRegex(approval.ApprovalDenied, 'PAYLOAD_SCHEMA_DENIED'):
            self.run_lab(token=sign(p))
        self.assert_original()

    def test_missing_payload_denied(self):
        with self.assertRaisesRegex(lab.RehearsalDenied, 'PAYLOAD_SET_DENIED'):
            self.run_lab(payloads={MAIN: FILES[MAIN]})
        self.assert_original()

    def test_wrong_simulation_mode_denied(self):
        with self.assertRaisesRegex(lab.RehearsalDenied, 'SIMULATION_MODE_DENIED'):
            self.run_lab(simulated_health='real')
        self.assert_original()

    def test_invalid_fault_mode_denied(self):
        with self.assertRaisesRegex(lab.RehearsalDenied, 'FAULT_INJECTION_MODE_DENIED'):
            self.run_lab(fail_at='outside_laboratory')
        self.assert_original()

    def test_nonlab_path_denied_even_with_valid_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(LifecycleTransactionError,
                                        'NON_LAB_DESTINATION_DENIED'):
                self.run_lab(root=Path(temp))
        self.assert_original()

    def test_nonce_file_is_durable_and_private(self):
        self.run_lab(simulated_health='fail')
        marker = self.root / ('.lab-approval-used-' + '1' * 32)
        self.assertEqual(marker.read_text(), '1' * 32 + '\n')
        self.assertEqual(marker.stat().st_mode & 0o077, 0)

    def test_all_module_digests_are_bound(self):
        baseline = self.expected['extension_sha256']
        for name in MODULES:
            with self.subTest(module=name):
                variant = dict(FILES)
                variant[name] += b'changed'
                self.assertNotEqual(
                    lab.pins(commit=COMMIT, manifest_sha256=MANIFEST,
                             installed_sha256=ORIGINAL_SHA,
                             payloads=variant)['extension_sha256'], baseline)

    def test_bad_key_rejected(self):
        with self.assertRaisesRegex(approval.ApprovalDenied, 'SIGNATURE_DENIED'):
            self.run_lab(lab_key=b'Q' * 32)
        self.assert_original()


if __name__ == '__main__':
    unittest.main()
