"""Async overlay transformation contract tests."""
import unittest

from updater.async_overlay import (
    ANNOTATION_OLD,
    IMPORT_OLD,
    TOOLS_OLD,
    SourceDriftError,
    overlay,
)


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            IMPORT_OLD + '\nTOOLS = [\n' + TOOLS_OLD + ']\n'
            + 'x = (' + ANNOTATION_OLD + ')\n'
        ).encode()

    def test_only_targeted_changes(self):
        changed = overlay(self.source)
        self.assertIn(b'import stage_async', changed)
        self.assertIn(b'fieldwork_stage_test_request', changed)
        self.assertIn(b'fieldwork_stage_test_status', changed)
        self.assertEqual(changed.count(b'fieldwork_stage_test_request'), 2)

    def test_reapply_denied(self):
        with self.assertRaisesRegex(SourceDriftError, 'ALREADY_PATCHED'):
            overlay(overlay(self.source))

    def test_missing_anchor_denied(self):
        with self.assertRaisesRegex(SourceDriftError, 'INTEGRATION_ANCHOR_MISMATCH'):
            overlay(self.source.replace(b'import stage_manager', b'import different'))

    def test_invalid_source_denied(self):
        with self.assertRaisesRegex(SourceDriftError, 'INVALID_INSTALLED_SOURCE'):
            overlay(b'def bad(:\n')


if __name__ == '__main__':
    unittest.main()
