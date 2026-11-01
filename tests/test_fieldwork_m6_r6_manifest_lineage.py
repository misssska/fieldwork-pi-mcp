"""Exact manifest R4 lineage regression; synthetic files only; no Docker/production."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SRC=Path(__file__).resolve().parents[1]/'updater/fieldwork_m6r5_first_canary_18086.py'
spec=importlib.util.spec_from_file_location('fieldwork_m6r9_r6',SRC)
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

class ReceiptLineage(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.f=Path(self.d.name)/'test_account_m6.py'
        self.f.write_text('test-only fixture',encoding='utf-8')

    def test_original_receipt_plus_exact_r4_digest_passes(self):
        with patch.object(g,'digest_file',return_value=g.R4_ACCOUNT_SHA) as h:
            g.verify_overlay_pin(g.R4_ACCOUNT_TEST,g.R4_ACCOUNT_OLD_SHA,self.f)
            h.assert_called_once_with(self.f)

    def test_original_unpatched_bytes_not_accepted(self):
        with patch.object(g,'digest_file',return_value=g.R4_ACCOUNT_OLD_SHA):
            with self.assertRaisesRegex(RuntimeError,'M6_R4_PATCHED_TEST_SHA_DRIFT'):
                g.verify_overlay_pin(g.R4_ACCOUNT_TEST,g.R4_ACCOUNT_OLD_SHA,self.f)

    def test_forged_receipt_claiming_patched_hash_rejected(self):
        with patch.object(g,'digest_file',return_value=g.R4_ACCOUNT_SHA) as h:
            with self.assertRaisesRegex(RuntimeError,'M6_R4_ORIGINAL_MANIFEST_SHA_DRIFT'):
                g.verify_overlay_pin(g.R4_ACCOUNT_TEST,g.R4_ACCOUNT_SHA,self.f)
            h.assert_not_called()

    def test_any_other_receipt_drift_rejected(self):
        with patch.object(g,'digest_file',return_value=g.R4_ACCOUNT_SHA):
            with self.assertRaisesRegex(RuntimeError,'M6_R4_ORIGINAL_MANIFEST_SHA_DRIFT'):
                g.verify_overlay_pin(g.R4_ACCOUNT_TEST,'0'*64,self.f)

    def test_r4_current_file_tamper_denied(self):
        with patch.object(g,'digest_file',return_value='a'*64):
            with self.assertRaisesRegex(RuntimeError,'M6_R4_PATCHED_TEST_SHA_DRIFT'):
                g.verify_overlay_pin(g.R4_ACCOUNT_TEST,g.R4_ACCOUNT_OLD_SHA,self.f)

    def test_unrelated_overlay_still_exact_manifest_pinned(self):
        label='server/app/main.py'
        with patch.object(g,'digest_file',return_value='b'*64):
            g.verify_overlay_pin(label,'b'*64,self.f)
            with self.assertRaisesRegex(RuntimeError,'M6_OVERLAY_FILE_SHA_DRIFT'):
                g.verify_overlay_pin(label,'c'*64,self.f)

    def test_missing_file_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError,'M6_OVERLAY_FILE_MISSING_OR_UNSAFE'):
            g.verify_overlay_pin(g.R4_ACCOUNT_TEST,g.R4_ACCOUNT_OLD_SHA,self.f.with_name('missing.py'))

    def test_symlink_file_fail_closed(self):
        target=self.f.with_name('link.py')
        target.symlink_to(self.f)
        with self.assertRaisesRegex(RuntimeError,'M6_OVERLAY_FILE_MISSING_OR_UNSAFE'):
            g.verify_overlay_pin(g.R4_ACCOUNT_TEST,g.R4_ACCOUNT_OLD_SHA,target)

if __name__=='__main__':
    unittest.main()
