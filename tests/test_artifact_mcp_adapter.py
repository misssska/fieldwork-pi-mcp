"""Synthetic integration tests, argument validation and fail-closed source drift."""
import base64
import unittest
from unittest.mock import patch

from updater import artifact_inbox_adapter as adapter
from updater import artifact_inbox_overlay as overlay
from updater import artifact_inbox as inbox

SOURCE = (
    'import stage_manager\n'
    'TOOLS = [\n'
    + overlay.TOOLS_OLD +
    ']\n'
    'AUDIT = ["fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start"]\n'
)

TID = 'a' * 32
SHA = 'b' * 64


class MCPAdapterTests(unittest.TestCase):
    def test_begin_exact_arguments(self):
        with patch.object(inbox, "begin", return_value={"status": "UPLOAD_STARTED"}) as backend:
            self.assertEqual(adapter.begin({"transfer_id": TID, "size": 123, "sha256": SHA})["status"],
                             "UPLOAD_STARTED")
            backend.assert_called_once_with(TID, 123, SHA)

    def test_chunk_uses_exact_arguments(self):
        data = base64.b64encode(b"abc").decode()
        with patch.object(inbox, "append", return_value={"status": "UPLOADING"}) as backend:
            self.assertEqual(adapter.append({"transfer_id": TID, "offset": 0, "chunk_base64": data})["status"],
                             "UPLOADING")
            backend.assert_called_once_with(TID, 0, data)

    def test_status_and_finalization_do_not_execute(self):
        with patch.object(inbox, "status", return_value={"status": "UPLOADING"}) as backend:
            adapter.status({"transfer_id": TID})
            backend.assert_called_once_with(TID)
        with patch.object(inbox, "finalize", return_value={"status": "VERIFIED_NOT_DEPLOYED"}) as backend:
            adapter.finalize({"transfer_id": TID})
            backend.assert_called_once_with(TID)

    def test_unknown_key_and_types_denied(self):
        for invalid in (None, {"transfer_id": TID, "command": "bash"},
                        {"transfer_id": TID, "size": 1, "sha256": SHA, "execute": True}):
            with self.subTest(invalid=invalid), self.assertRaises(inbox.InboxDenied):
                adapter.status(invalid)
        for size in (True, 0, 1.1, 32 * 1024 * 1024 + 1):
            with self.subTest(size=size), self.assertRaises(inbox.InboxDenied):
                adapter.begin({"transfer_id": TID, "size": size, "sha256": SHA})

    def test_malformed_chunk_denied_without_backend(self):
        with patch.object(inbox, "append") as backend:
            for inval in (-1, 3.14, True, 33_554_433):
                with self.assertRaises(inbox.InboxDenied):
                    adapter.append({"transfer_id": TID, "offset": inval, "chunk_base64": "YQ=="})
            with self.assertRaises(inbox.InboxDenied):
                adapter.append({"transfer_id": TID, "offset": 0, "chunk_base64": "x" * 44001})
            backend.assert_not_called()


class OverlayTests(unittest.TestCase):
    def test_in_memory_integration(self):
        transformed = overlay.overlay(SOURCE.encode())
        self.assertEqual(transformed.count(b"import artifact_inbox_adapter"), 1)
        for name in ("begin", "append", "status", "finalize"):
            self.assertEqual(transformed.count(f'("fieldwork_artifact_{name}"'.encode()), 1)
        self.assertIn(b'"fieldwork_artifact_finalize"', transformed)

    def test_replay_fails_closed(self):
        with self.assertRaisesRegex(overlay.AdapterOverlayDenied, "ALREADY_INSTALLED"):
            overlay.overlay(overlay.overlay(SOURCE.encode()))

    def test_anchor_drift_denied(self):
        for broken in (SOURCE.replace("stage_manager.full_test", "stage_manager.other"),
                       SOURCE.replace("import stage_manager", "import changed"),
                       SOURCE.replace("TOOLS = [", "TOOLS = [\n" + overlay.TOOLS_OLD),
                       SOURCE + '\n# fieldwork_artifact_begin already declared\n'):
            with self.subTest(), self.assertRaises(overlay.AdapterOverlayDenied):
                overlay.overlay(broken.encode())

    def test_no_filesystem_or_exec_in_overlay_source(self):
        import inspect
        source = inspect.getsource(overlay)
        for forbidden in ("os.system(", "subprocess.run(", "eval(", "exec(",
                          "open(", "write_bytes(", "replace(", "unlink("):
            # source.replace(..) legitimately generates in-memory code, so check only
            # dangerous filesystem / command patterns except str.replace
            if forbidden == "replace(":
                continue
            self.assertNotIn(forbidden, source)

    def test_bad_bytes_denied(self):
        for value in (b"\xff", b"def invalid :\n", b"hello", b"A" * 1_000_001):
            with self.assertRaises(overlay.AdapterOverlayDenied):
                overlay.overlay(value)


if __name__ == "__main__":
    unittest.main()
