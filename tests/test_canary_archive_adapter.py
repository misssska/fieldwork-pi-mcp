"""Exact tool schemas, negative parameters and replay-safe source integration."""
import unittest
from unittest.mock import patch

from updater import canary_archive_adapter as a
from updater import canary_archive_qualifier as q
from updater import canary_archive_overlay as o

BASE = (
    "import artifact_inbox_adapter\n"
    "TOOLS = [\n" + o.TOOLS_OLD + "]\n"
    "AUDIT = [" + o.ANNOTATION_OLD + "]\n"
).encode()
TID = "3" * 32


class AdapterTests(unittest.TestCase):
    def test_exact_transfer_id_only(self):
        with patch.object(q, "qualify_transfer", return_value={"status": "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED"}) as fn:
            self.assertEqual(a.qualify({"transfer_id": TID})["status"],
                             "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED")
            fn.assert_called_once_with(TID)

    def test_argument_injection_denied(self):
        with patch.object(q, "qualify_transfer") as fn:
            for bad in (None, {}, {"transfer_id": "../etc"},
                        {"transfer_id": TID, "execute": True},
                        {"transfer_id": TID, "path": "/opt/fieldwork"},
                        {"transfer_id": 123}, {"transfer_id": "A" * 32}):
                with self.subTest(bad=bad), self.assertRaises(q.QualificationDenied):
                    a.qualify(bad)
            fn.assert_not_called()


class OverlayTests(unittest.TestCase):
    def test_one_new_tool_without_removing_existing(self):
        output = o.overlay(BASE)
        self.assertEqual(output.count(b'("fieldwork_artifact_qualify"'), 1)
        self.assertEqual(output.count(b'("fieldwork_artifact_finalize"'), 1)
        self.assertIn(b"import canary_archive_qualifier", output)
        self.assertIn(b"import canary_archive_adapter", output)
        self.assertIn(b'"fieldwork_artifact_qualify"', output)

    def test_replay_denied(self):
        with self.assertRaisesRegex(o.SourceDrift, "ALREADY_PATCHED"):
            o.overlay(o.overlay(BASE))

    def test_source_anchor_mismatch_denied(self):
        for malformed in (
            BASE.replace(b"artifact_inbox_adapter.finalize",
                         b"artifact_inbox_adapter.something_else"),
            BASE.replace(b"import artifact_inbox_adapter",
                         b"import unrelated"),
            BASE + b"\n# fieldwork_artifact_qualify already present\n",
            BASE.replace(o.ANNOTATION_OLD.encode(), b'"fieldwork_artifact_finalize"'),
        ):
            with self.subTest(), self.assertRaises(o.SourceDrift):
                o.overlay(malformed)

    def test_invalid_python_and_binary_denied(self):
        for bad in (b"", b"\xff", b"syntax error <<<", b"X" * 1_000_001):
            with self.subTest(), self.assertRaises(o.SourceDrift):
                o.overlay(bad)

    def test_not_an_installer(self):
        import inspect
        source = inspect.getsource(o) + inspect.getsource(a)
        for forbidden in ("subprocess.", "os.system(", "eval(", "exec(",
                          "systemctl", "docker compose", "write_bytes("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
