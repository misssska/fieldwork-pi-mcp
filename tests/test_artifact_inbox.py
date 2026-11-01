"""Offline tests for inert chunked delivery to a pinned private Pi inbox."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import artifact_inbox as inbox

ID = 'a' * 32
SRC = b'FieldWork canary test artifact\x00' * 100
SHA = hashlib.sha256(SRC).hexdigest()


def encoded(b: bytes) -> str:
    return base64.b64encode(b).decode('ascii')


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.home_patch = patch.object(inbox.Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.uid_patch = patch.object(inbox.os, 'geteuid', return_value=1000)
        # Actual euid often 0 in CI/container; filesystem ownership must match process uid.
        self.uid_patch = patch.object(inbox.os, 'geteuid', return_value=inbox.os.getuid() or 1000)
        self.uid_patch.start()
        self.addCleanup(self.uid_patch.stop)
        if inbox.os.getuid() == 0:
            self.skipTest('Run unprivileged; root is intentionally denied')

    def begin(self):
        return inbox.begin(ID, len(SRC), SHA)

    def test_complete_and_status_and_retry(self):
        self.begin()
        self.assertEqual(inbox.status(ID)['status'], 'UPLOADING')
        half = len(SRC) // 2
        inbox.append(ID, 0, encoded(SRC[:half]))
        self.assertEqual(inbox.append(ID, 0, encoded(SRC[:half]))['received_bytes'], half)
        inbox.append(ID, half, encoded(SRC[half:]))
        self.assertEqual(inbox.finalize(ID)['status'], 'VERIFIED_NOT_DEPLOYED')
        self.assertEqual(inbox.finalize(ID)['status'], 'VERIFIED_NOT_DEPLOYED')
        self.assertEqual(inbox.status(ID)['status'], 'VERIFIED')
        self.assertEqual((self.home / inbox.STATE / ID / 'artifact.bin').read_bytes(), SRC)

    def test_no_resume_overwrite_or_reordering(self):
        self.begin()
        with self.assertRaisesRegex(inbox.InboxDenied, 'TRANSFER_ALREADY_EXISTS'):
            self.begin()
        with self.assertRaisesRegex(inbox.InboxDenied, 'OUT_OF_ORDER_CHUNK'):
            inbox.append(ID, 1, encoded(SRC[:3]))
        inbox.append(ID, 0, encoded(SRC[:10]))
        with self.assertRaisesRegex(inbox.InboxDenied, 'REPLAY_DATA_MISMATCH'):
            inbox.append(ID, 0, encoded(b'XXXXXXXXXX'))
        with self.assertRaisesRegex(inbox.InboxDenied, 'OVERLAPPING_CHUNK_DENIED'):
            inbox.append(ID, 5, encoded(SRC[5:15]))

    def test_hash_and_undersize_are_refused(self):
        self.begin()
        with self.assertRaisesRegex(inbox.InboxDenied, 'UPLOAD_INCOMPLETE'):
            inbox.finalize(ID)
        inbox.append(ID, 0, encoded(b'X' * len(SRC)))
        with self.assertRaisesRegex(inbox.InboxDenied, 'ARTIFACT_HASH_MISMATCH'):
            inbox.finalize(ID)
        self.assertFalse((self.home / inbox.STATE / ID / 'artifact.bin').exists())

    def test_invalid_user_data_rejected(self):
        with self.assertRaisesRegex(inbox.InboxDenied, 'TRANSFER_ID_INVALID'):
            inbox.begin('../etc', 1, SHA)
        with self.assertRaisesRegex(inbox.InboxDenied, 'ARTIFACT_HASH_INVALID'):
            inbox.begin(ID, 1, 'f')
        with self.assertRaisesRegex(inbox.InboxDenied, 'ARTIFACT_SIZE_DENIED'):
            inbox.begin(ID, 0, SHA)
        with self.assertRaisesRegex(inbox.InboxDenied, 'ARTIFACT_SIZE_DENIED'):
            inbox.begin(ID, inbox.MAX_ARTIFACT + 1, SHA)

    def test_chunk_bounds_and_b64(self):
        self.begin()
        with self.assertRaisesRegex(inbox.InboxDenied, 'CHUNK_SIZE_DENIED'):
            inbox.append(ID, 0, encoded(b'X' * (inbox.MAX_CHUNK + 1)))
        with self.assertRaisesRegex(inbox.InboxDenied, 'CHUNK_ENCODING_INVALID'):
            inbox.append(ID, 0, '????')
        with self.assertRaisesRegex(inbox.InboxDenied, 'ARTIFACT_OVERRUN'):
            inbox.append(ID, 0, encoded(b'X' * (len(SRC) + 1)))

    def test_symlink_payload_denied(self):
        self.begin()
        path = self.home / inbox.STATE / ID / 'payload.part'
        path.unlink()
        path.symlink_to(self.home / 'victim')
        with self.assertRaisesRegex(inbox.InboxDenied, 'PAYLOAD_SYMLINK_DENIED'):
            inbox.append(ID, 0, encoded(b'X'))

    def test_symlink_state_denied(self):
        path = self.home / '.local'
        path.symlink_to(self.home)
        with self.assertRaisesRegex(inbox.InboxDenied, 'SYMLINK_DENIED'):
            self.begin()

    def test_tampered_verified_artifact_denied(self):
        self.begin()
        inbox.append(ID, 0, encoded(SRC))
        inbox.finalize(ID)
        p = self.home / inbox.STATE / ID / 'artifact.bin'
        p.write_bytes(b'NOT ORIGINAL')
        with self.assertRaisesRegex(inbox.InboxDenied, 'VERIFIED_ARTIFACT_TAMPERED'):
            inbox.status(ID)

    def test_capacity_denies_ninth_transfer(self):
        for n in range(8):
            inbox.begin(f'{n:032x}', 1, hashlib.sha256(b'a').hexdigest())
        with self.assertRaisesRegex(inbox.InboxDenied, 'INBOX_CAPACITY_REACHED'):
            self.begin()


if __name__ == '__main__':
    unittest.main()
