"""No Pi, Docker or host commands; only source-to-source transformation tests."""
import ast
import unittest
from updater.async_overlay import overlay as async_overlay, TOOLS_OLD as ATOOLS, ANNOTATION_OLD as AANN
from experimental.lifecycle_overlay import overlay as lifecycle_overlay, SourceDriftError, TOOLS_OLD as LTOOLS

BASE = ('import stage_manager\nTOOLS = [\n' + ATOOLS + LTOOLS + ']\n'
        + 'annotations = (' + AANN + ', "fieldwork_stage_stop")\n').encode()

class LifecycleOverlayPortableTests(unittest.TestCase):
    def test_chained_overlay(self):
        candidate = lifecycle_overlay(async_overlay(BASE))
        ast.parse(candidate)
        self.assertEqual(candidate.count(b'fieldwork_stage_inspect'), 1)
        self.assertEqual(candidate.count(b'fieldwork_stage_start_request'), 2)
        self.assertEqual(candidate.count(b'fieldwork_stage_start_status'), 1)
        self.assertEqual(candidate.count(b'import stage_start_async'), 1)
    def test_missing_async_stage_denied(self):
        with self.assertRaisesRegex(SourceDriftError, 'INTEGRATION_ANCHOR_MISMATCH'):
            lifecycle_overlay(BASE)
    def test_repeat_denied(self):
        candidate = lifecycle_overlay(async_overlay(BASE))
        with self.assertRaisesRegex(SourceDriftError, 'ALREADY_PATCHED_OR_PARTIAL'):
            lifecycle_overlay(candidate)
    def test_malformed_denied(self):
        with self.assertRaisesRegex(SourceDriftError, 'INVALID_CANDIDATE_SOURCE'):
            lifecycle_overlay(b'\xff')
    def test_anchor_drift_denied(self):
        candidate = async_overlay(BASE).replace(b'fieldwork_stage_status', b'fieldwork_stage_status_other')
        with self.assertRaisesRegex(SourceDriftError, 'INTEGRATION_ANCHOR_MISMATCH'):
            lifecycle_overlay(candidate)

if __name__ == '__main__': unittest.main()
