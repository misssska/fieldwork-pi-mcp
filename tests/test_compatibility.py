"""Read-only compatibility inspector tests."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from updater.compatibility import inspect


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fieldwork_mcp.py"

    def test_unknown_source_does_not_authorize_install(self):
        data = b"x = 1\n"
        self.path.write_bytes(data)
        result = inspect(self.path)
        self.assertEqual(result["status"], "UNREVIEWED_INSTALLED_SOURCE")
        self.assertEqual(result["installed_sha256"], hashlib.sha256(data).hexdigest())
        self.assertIs(result["safe_to_overwrite"], False)

    def test_missing(self):
        self.assertEqual(inspect(self.path)["reason"], "MISSING_OR_SYMLINK")

    def test_symlink(self):
        real = Path(self.tmp.name) / "real.py"
        real.write_text("x = 1\n")
        self.path.symlink_to(real)
        self.assertEqual(inspect(self.path)["reason"], "MISSING_OR_SYMLINK")

    def test_invalid_python(self):
        self.path.write_text("def broken(:\n")
        self.assertEqual(inspect(self.path)["reason"], "SOURCE_NOT_VALID_PYTHON")

    def test_tool_names_not_registration_proof(self):
        self.path.write_text("s = 'fieldwork_stage_test_request fieldwork_stage_test_status'\n")
        result = inspect(self.path)
        self.assertIs(result["async_tool_name_presence"]["fieldwork_stage_test_request"], True)
        self.assertIs(result["safe_to_overwrite"], False)


if __name__ == "__main__":
    unittest.main()
