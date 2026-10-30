"""Offline static admin-import diagnostic tests. No FieldWork code execution."""
from pathlib import Path
import tempfile
import unittest

from updater.admin_import_preflight import check_admin_imports, PreflightDenied


class AdminImportPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tests").mkdir()
        (self.root / "scripts").mkdir()
        self.test = self.root / "tests/test_admin_rotation.py"

    def write(self, text):
        self.test.write_text(text, encoding="utf-8")
        return check_admin_imports(self.root)

    def test_explicit_missing(self):
        result = self.write("from scripts.rotate_admin import rotate\n")
        self.assertEqual(result["status"], "MISSING_LOCAL_IMPORTS")
        self.assertEqual(result["explicit_missing"], ["scripts.rotate_admin"])

    def test_explicit_present(self):
        (self.root / "scripts/rotate_admin.py").write_text("x = 1\n")
        result = self.write("from scripts.rotate_admin import rotate\n")
        self.assertEqual(result["status"], "STATIC_IMPORT_PATHS_PRESENT")
        self.assertEqual(result["explicit_present"], ["scripts.rotate_admin"])

    def test_import_statement(self):
        result = self.write("import scripts.rotate_admin as rotate\n")
        self.assertEqual(result["explicit_missing"], ["scripts.rotate_admin"])

    def test_package_present(self):
        (self.root / "scripts/rotate_admin").mkdir()
        (self.root / "scripts/rotate_admin/__init__.py").write_text("")
        result = self.write("from scripts.rotate_admin import rotate\n")
        self.assertEqual(result["status"], "STATIC_IMPORT_PATHS_PRESENT")

    def test_ambiguous_from_import_not_falsely_missing(self):
        result = self.write("from scripts import rotate_admin\n")
        self.assertEqual(result["status"], "AMBIGUOUS_LOCAL_IMPORTS")
        self.assertEqual(result["explicit_missing"], [])
        self.assertEqual(result["ambiguous_from_import"], ["scripts.rotate_admin"])

    def test_ambiguous_import_with_module_present(self):
        (self.root / "scripts/rotate_admin.py").write_text("")
        result = self.write("from scripts import rotate_admin\n")
        self.assertEqual(result["status"], "STATIC_IMPORT_PATHS_PRESENT")

    def test_external_import_ignored(self):
        result = self.write("from sqlalchemy import create_engine\n")
        self.assertEqual(result["status"], "STATIC_IMPORT_PATHS_PRESENT")

    def test_duplicate_import_deduplicated(self):
        result = self.write("import scripts.rotate_admin\nimport scripts.rotate_admin\n")
        self.assertEqual(result["explicit_missing"], ["scripts.rotate_admin"])

    def test_sensitive_filename_is_intentionally_excluded(self):
        result = self.write("from scripts.rotate_admin_password import rotate\n")
        self.assertEqual(result["status"], "POLICY_EXCLUDED_IMPORTS")
        self.assertEqual(result["policy_excluded_count"], 1)
        self.assertEqual(result["explicit_missing"], [])
        self.assertNotIn("rotate_admin_password", repr(result))

    def test_sensitive_filename_is_not_copied_even_if_present(self):
        # The preflight must not read or copy a sensitive source file.
        result = self.write("import scripts.admin_password\n")
        self.assertEqual(result["status"], "POLICY_EXCLUDED_IMPORTS")
        self.assertFalse(result["executed_code"])

    def test_mixed_missing_reports_only_actionable(self):
        result = self.write("import scripts.admin_password\nimport scripts.rotate_admin\n")
        self.assertEqual(result["status"], "MISSING_LOCAL_IMPORTS")
        self.assertEqual(result["explicit_missing"], ["scripts.rotate_admin"])
        self.assertEqual(result["policy_excluded_count"], 1)

    def test_test_file_missing_denied(self):
        with self.assertRaisesRegex(PreflightDenied, "ADMIN_TEST_MISSING_OR_TOO_LARGE"):
            check_admin_imports(self.root)

    def test_symlink_test_denied(self):
        real = self.root / "real.py"
        real.write_text("import scripts.rotate_admin\n")
        self.test.symlink_to(real)
        with self.assertRaisesRegex(PreflightDenied, "SYMLINK_SOURCE_DENIED"):
            check_admin_imports(self.root)

    def test_symlink_module_denied(self):
        other = self.root / "outside.py"
        other.write_text("")
        (self.root / "scripts/rotate_admin.py").symlink_to(other)
        with self.assertRaisesRegex(PreflightDenied, "SYMLINK_SOURCE_DENIED"):
            self.write("import scripts.rotate_admin\n")

    def test_missing_path_not_executed(self):
        result = self.write("raise RuntimeError('SHOULD_NOT_EXECUTE')\nimport scripts.rotate_admin\n")
        self.assertFalse(result["executed_code"])
        self.assertFalse(result["production_modified"])


if __name__ == "__main__":
    unittest.main()
