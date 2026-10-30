"""PIN, AST, exact-source qualification tests; no Pi files or service writes."""
import hashlib
from pathlib import Path
import unittest

from updater import artifact_inbox_overlay as overlay
from updater import artifact_adapter_qualification as q

SOURCE = ("import stage_manager\nTOOLS = [\n" + overlay.TOOLS_OLD + "]\n"
          'ANNOTATED = ["fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start"]\n').encode()


def inputs():
    folder = Path(q.__file__).parent
    modules = {name: (folder / name).read_bytes() for name in q.MODULES}
    return modules, {name: q.sha(content) for name, content in modules.items()}


class QualificationTests(unittest.TestCase):
    def test_exact_pins_read_only(self):
        modules, pins = inputs()
        result = q.qualify(SOURCE, q.sha(SOURCE), modules, pins)
        self.assertEqual(result["status"], "STATIC_ARTIFACT_ADAPTER_QUALIFIED")
        self.assertEqual(len(result["tool_names"]), 4)
        self.assertNotEqual(result["candidate_source_sha256"], q.sha(SOURCE))
        for name in ("runtime_tested", "activation_authorized", "mcp_modified",
                     "tunnel_restarted", "production_modified"):
            self.assertFalse(result[name])

    def test_source_drift_fails(self):
        modules, pins = inputs()
        with self.assertRaisesRegex(q.QualificationDenied, "SOURCE_HASH_DRIFT"):
            q.qualify(SOURCE, "0" * 64, modules, pins)

    def test_no_unreviewed_module(self):
        modules, pins = inputs()
        modules["install.sh"] = b"echo unsafe"
        with self.assertRaisesRegex(q.QualificationDenied, "MODULE_SET_INVALID"):
            q.qualify(SOURCE, q.sha(SOURCE), modules, pins)

    def test_changed_module_hash_denied(self):
        modules, pins = inputs()
        modules["artifact_inbox_adapter.py"] += b"\n# changed"
        with self.assertRaisesRegex(q.QualificationDenied, "MODULE_PIN_MISMATCH"):
            q.qualify(SOURCE, q.sha(SOURCE), modules, pins)

    def test_overlay_implementation_substitution_denied(self):
        modules, pins = inputs()
        modules["artifact_inbox_overlay.py"] += b"\n# arbitrary but valid"
        pins["artifact_inbox_overlay.py"] = q.sha(modules["artifact_inbox_overlay.py"])
        with self.assertRaisesRegex(q.QualificationDenied, "OVERLAY_IMPLEMENTATION_DRIFT"):
            q.qualify(SOURCE, q.sha(SOURCE), modules, pins)

    def test_invalid_python_denied(self):
        modules, pins = inputs()
        modules["artifact_inbox.py"] = b"syntax error !@#$"
        pins["artifact_inbox.py"] = q.sha(modules["artifact_inbox.py"])
        with self.assertRaisesRegex(q.QualificationDenied, "MODULE_SYNTAX_INVALID"):
            q.qualify(SOURCE, q.sha(SOURCE), modules, pins)

    def test_unexpected_mcp_anchor_denied(self):
        modules, pins = inputs()
        drifted = SOURCE.replace(b"stage_manager.full_test", b"stage_manager.some_other_function")
        with self.assertRaisesRegex(q.QualificationDenied, "INTEGRATION_ANCHOR_MISMATCH"):
            q.qualify(drifted, q.sha(drifted), modules, pins)

    def test_candidate_does_not_touch_host(self):
        modules, pins = inputs()
        result = q.qualify(SOURCE, q.sha(SOURCE), modules, pins)
        self.assertEqual(result["installed_source_sha256"], hashlib.sha256(SOURCE).hexdigest())


if __name__ == "__main__":
    unittest.main()
