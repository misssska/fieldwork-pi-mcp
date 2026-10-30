"""Offline approval verifier tests. Signing here is a TEST FIXTURE, not an issuer."""
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from updater import local_approval_lab as a

KEY = b"K" * 32
NOW = int(time.time())
EXPECTED = {
    "commit": "a" * 40, "manifest_sha256": "b" * 64,
    "installed_sha256": "c" * 64, "candidate_sha256": "d" * 64,
    "extension_sha256": "e" * 64,
}


def signed(payload):
    return {"payload": payload, "mac": hmac.new(
        KEY, a.canonical(payload), hashlib.sha256).hexdigest()}


class LocalApprovalLabTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "schema": 1, "purpose": a.PURPOSE, **EXPECTED,
            "nonce": "1" * 32, "issued_at": NOW - 10, "expires_at": NOW + 120,
        }

    def proof(self):
        return a.verify(signed(self.payload), KEY, expected=EXPECTED, now=NOW)

    def test_valid_proof_does_not_authorize(self):
        self.assertEqual(self.proof()["status"], "VALID_LOCAL_PROOF_NOT_CONSUMED")
        self.assertFalse(self.proof()["activation_authorized"])

    def test_payload_tamper(self):
        token = signed(self.payload)
        token["payload"]["expires_at"] += 10
        with self.assertRaisesRegex(a.ApprovalDenied, "SIGNATURE_DENIED"):
            a.verify(token, KEY, expected=EXPECTED, now=NOW)

    def test_bad_signature(self):
        token = signed(self.payload)
        token["mac"] = "0" * 64
        with self.assertRaisesRegex(a.ApprovalDenied, "SIGNATURE_DENIED"):
            a.verify(token, KEY, expected=EXPECTED, now=NOW)

    def test_commit_drift(self):
        self.payload["commit"] = "f" * 40
        with self.assertRaisesRegex(a.ApprovalDenied, "PIN_MISMATCH:commit"):
            self.proof()

    def test_candidate_drift(self):
        self.payload["candidate_sha256"] = "f" * 64
        with self.assertRaisesRegex(a.ApprovalDenied, "PIN_MISMATCH:candidate_sha256"):
            self.proof()

    def test_expired(self):
        self.payload["issued_at"] = NOW - 400
        self.payload["expires_at"] = NOW - 100
        with self.assertRaisesRegex(a.ApprovalDenied, "EXPIRED_OR_INVALID_WINDOW"):
            self.proof()

    def test_long_window(self):
        self.payload["expires_at"] = NOW + 400
        with self.assertRaisesRegex(a.ApprovalDenied, "EXPIRED_OR_INVALID_WINDOW"):
            self.proof()

    def test_future_issued(self):
        self.payload["issued_at"] = NOW + 40
        with self.assertRaisesRegex(a.ApprovalDenied, "EXPIRED_OR_INVALID_WINDOW"):
            self.proof()

    def test_wrong_purpose(self):
        self.payload["purpose"] = "fieldwork:deploy-production"
        with self.assertRaisesRegex(a.ApprovalDenied, "PURPOSE_DENIED"):
            self.proof()

    def test_extra_field_denied(self):
        self.payload["command"] = "sh"
        with self.assertRaisesRegex(a.ApprovalDenied, "PAYLOAD_SCHEMA_DENIED"):
            self.proof()

    def test_short_key_denied(self):
        with self.assertRaisesRegex(a.ApprovalDenied, "LOCAL_KEY_REQUIRED"):
            a.verify(signed(self.payload), b"short", expected=EXPECTED, now=NOW)

    def test_one_use_claim_and_replay_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            used = home / ".local/state/fieldwork-pi-mcp/local-approval/used"
            used.mkdir(parents=True, mode=0o700)
            with patch.object(a.Path, "home", return_value=home):
                result = a.verify_and_consume(signed(self.payload), KEY, expected=EXPECTED, replay_dir=used, now=NOW)
                self.assertEqual(result["status"], "PROOF_CONSUMED_NO_ACTIVATION")
                self.assertFalse(result["activation_authorized"])
                with self.assertRaisesRegex(a.ApprovalDenied, "APPROVAL_REPLAY_DENIED"):
                    a.verify_and_consume(signed(self.payload), KEY, expected=EXPECTED, replay_dir=used, now=NOW)

    def test_arbitrary_claim_destination_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            used = Path(temp)
            with self.assertRaisesRegex(a.ApprovalDenied, "REPLAY_DESTINATION_DENIED"):
                a.verify_and_consume(signed(self.payload), KEY, expected=EXPECTED, replay_dir=used, now=NOW)

    def test_fake_unverified_proof_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(a.ApprovalDenied, "TOKEN_SCHEMA_DENIED"):
                a.verify_and_consume({"nonce": "1" * 32}, KEY, expected=EXPECTED,
                                     replay_dir=Path(temp), now=NOW)

    def test_symlink_replay_directory_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            real = home / "real"
            real.mkdir(mode=0o700)
            used = home / ".local/state/fieldwork-pi-mcp/local-approval/used"
            used.parent.mkdir(parents=True)
            used.symlink_to(real, target_is_directory=True)
            with patch.object(a.Path, "home", return_value=home):
                with self.assertRaisesRegex(a.ApprovalDenied, "REPLAY_DIR_UNSAFE"):
                    a.verify_and_consume(signed(self.payload), KEY, expected=EXPECTED, replay_dir=used, now=NOW)


if __name__ == "__main__":
    unittest.main()
