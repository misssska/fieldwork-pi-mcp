"""Exact-argument retirement MCP adapter negative tests."""
import unittest
from unittest.mock import patch
from updater import artifact_retention_adapter as a
from updater import artifact_retention as r
from updater import artifact_inbox as inbox
from updater import canary_archive_overlay as overlay

TID = "d" * 32
HASH = "e" * 64


class RetirementAdapterTests(unittest.TestCase):
    def test_exact_sha_and_consent(self):
        with patch.object(r, "retire", return_value={"status": "RETIRED"}) as func:
            self.assertEqual(a.retire({"transfer_id": TID, "sha256": HASH,
                                       "approval": r.APPROVAL})["status"], "RETIRED")
            func.assert_called_once_with(TID, HASH, r.APPROVAL)

    def test_reject_unapproved_or_arbitrary_inputs(self):
        cases = [
            {}, None, {"transfer_id": TID, "sha256": HASH},
            {"transfer_id": TID, "sha256": HASH, "approval": "no"},
            {"transfer_id": TID, "sha256": HASH, "approval": r.APPROVAL,
             "command": "rm -rf /"},
            {"transfer_id": "../etc", "sha256": HASH, "approval": r.APPROVAL},
            {"transfer_id": TID, "sha256": "unknown", "approval": r.APPROVAL},
            {"transfer_id": TID, "sha256": HASH, "approval": r.APPROVAL,
             "path": "/opt/fieldwork"},
        ]
        with patch.object(r, "retire") as func:
            for case in cases:
                with self.subTest(case=case), self.assertRaises(inbox.InboxDenied):
                    a.retire(case)
            func.assert_not_called()

    def test_both_tools_added_fail_closed_in_memory(self):
        base = (
            "import artifact_inbox_adapter\n"
            "TOOLS = [\n" + overlay.TOOLS_OLD + "]\n"
            "AUDIT = [" + overlay.ANNOTATION_OLD + "]\n"
        ).encode()
        transformed = overlay.overlay(base)
        self.assertEqual(transformed.count(b'("fieldwork_artifact_qualify"'), 1)
        self.assertEqual(transformed.count(b'("fieldwork_artifact_retire"'), 1)
        self.assertIn(b"import artifact_retention_adapter", transformed)
        with self.assertRaises(overlay.SourceDrift):
            overlay.overlay(transformed)


if __name__ == "__main__":
    unittest.main()
