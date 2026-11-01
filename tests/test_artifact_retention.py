"""Offline security and recovery tests for bounded artifact retirement."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import artifact_inbox as inbox
from updater import artifact_retention as retire

TID = "b" * 32
DATA = b"verified inert canary data"
SHA = hashlib.sha256(DATA).hexdigest()


class RetentionTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("run as unprivileged user")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.home_patch = patch.object(inbox.Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def start(self, tid=TID):
        inbox.begin(tid, len(DATA), SHA)
        inbox.append(tid, 0, base64.b64encode(DATA).decode())

    def verified(self, tid=TID):
        self.start(tid)
        inbox.finalize(tid)

    def test_completed_retire_and_idempotent_retry(self):
        self.verified()
        result = retire.retire(TID, SHA, retire.APPROVAL)
        self.assertEqual(result["status"], "RETIRED")
        self.assertFalse(result["production_modified"])
        self.assertFalse((self.home / inbox.STATE / TID).exists())
        self.assertEqual(retire.retire(TID, SHA, retire.APPROVAL)["status"], "RETIRED")
        with self.assertRaisesRegex(inbox.InboxDenied, "TRANSFER_ID_RETIRED"):
            inbox.begin(TID, len(DATA), SHA)

    def test_pending_upload_cannot_retire(self):
        self.start()
        with self.assertRaisesRegex(inbox.InboxDenied, "ONLY_VERIFIED"):
            retire.retire(TID, SHA, retire.APPROVAL)
        self.assertEqual(inbox.status(TID)["status"], "UPLOADING")
        self.assertFalse((self.home / inbox.STATE / ("retired-" + TID + ".json")).exists())

    def test_wrong_hash_and_wrong_approval_denied(self):
        self.verified()
        with self.assertRaisesRegex(inbox.InboxDenied, "ONLY_VERIFIED"):
            retire.retire(TID, "0" * 64, retire.APPROVAL)
        with self.assertRaisesRegex(inbox.InboxDenied, "EXPLICIT_RETIRE_APPROVAL_REQUIRED"):
            retire.retire(TID, SHA, "no")
        self.assertEqual(inbox.status(TID)["status"], "VERIFIED")

    def test_recovers_after_tombstone_before_rename(self):
        self.verified()
        base = self.home / inbox.STATE
        proof = {"schema": 1, "transfer_id": TID, "sha256": SHA, "state": "RETIRED"}
        inbox._write_exclusive(base / ("retired-" + TID + ".json"),
                               (json.dumps(proof) + "\n").encode())
        self.assertEqual(retire.retire(TID, SHA, retire.APPROVAL)["status"], "RETIRED")
        self.assertFalse((base / TID).exists())

    def test_recovers_after_rename_before_cleanup(self):
        self.verified()
        base = self.home / inbox.STATE
        proof = {"schema": 1, "transfer_id": TID, "sha256": SHA, "state": "RETIRED"}
        inbox._write_exclusive(base / ("retired-" + TID + ".json"),
                               (json.dumps(proof) + "\n").encode())
        os.replace(base / TID, base / (".retired-" + TID))
        self.assertEqual(retire.retire(TID, SHA, retire.APPROVAL)["status"], "RETIRED")
        self.assertFalse((base / (".retired-" + TID)).exists())

    def test_unexpected_file_blocks_retirement(self):
        self.verified()
        (self.home / inbox.STATE / TID / "unauthorized").write_bytes(b"x")
        with self.assertRaisesRegex(inbox.InboxDenied, "RETIRE_UNEXPECTED_FILE"):
            retire.retire(TID, SHA, retire.APPROVAL)

    def test_symlink_tombstone_denied(self):
        self.verified()
        base = self.home / inbox.STATE
        outside = self.home / "outside"
        outside.write_text("not a receipt")
        (base / ("retired-" + TID + ".json")).symlink_to(outside)
        with self.assertRaises(inbox.InboxDenied):
            retire.retire(TID, SHA, retire.APPROVAL)
        self.assertEqual(outside.read_text(), "not a receipt")

    def test_retires_one_to_reclaim_slot_not_arbitrary_files(self):
        self.verified()
        outside = self.home / "important.txt"
        outside.write_text("untouched")
        for n in range(1, 8):
            inbox.begin(f"{n:032x}", len(DATA), SHA)
        with self.assertRaisesRegex(inbox.InboxDenied, "INBOX_CAPACITY_REACHED"):
            inbox.begin("f" * 32, len(DATA), SHA)
        retire.retire(TID, SHA, retire.APPROVAL)
        self.assertEqual(inbox.begin("f" * 32, len(DATA), SHA)["status"], "UPLOAD_STARTED")
        self.assertEqual(outside.read_text(), "untouched")

    def test_only_exact_sha256_can_resume_retirement(self):
        self.verified()
        base = self.home / inbox.STATE
        proof = {"schema": 1, "transfer_id": TID, "sha256": SHA, "state": "RETIRED"}
        inbox._write_exclusive(base / ("retired-" + TID + ".json"),
                               (json.dumps(proof) + "\n").encode())
        with self.assertRaisesRegex(inbox.InboxDenied, "RETIRE_RECEIPT_MISMATCH"):
            retire.retire(TID, "0" * 64, retire.APPROVAL)


if __name__ == "__main__":
    unittest.main()
