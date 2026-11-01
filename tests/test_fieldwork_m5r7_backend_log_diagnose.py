from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).with_name('fieldwork_m5r7_backend_log_diagnose.py')
spec = importlib.util.spec_from_file_location('m5r7_diag', SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class LogDiagnostics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.base = self.home/'.local/state/fieldwork-pi-mcp-v03/stage-v06'/m.CANDIDATE
        self.base.mkdir(parents=True)
        self.path = self.base/'m5-backend-test.log'
        ph = patch.object(m.Path,'home',return_value=self.home)
        ph.start();self.addCleanup(ph.stop)
        self.m5 = sorted(m.REQUIRED)

    def write(self, content):
        self.path.write_text(content)
        return m.diagnose(self.path)

    def test_exact_success_metadata_without_content(self):
        lines = ['================ test session starts ================','collected 7 items']
        lines += [f'tests/test_photo_comments_m5.py::{x} PASSED [ 22%]' for x in self.m5]
        lines += ['tests/test_api.py::baseline PASSED [ 80%]']*2
        lines += ['================ 7 passed in 2.42s ================']
        result=self.write('\n'.join(lines)+'\nAWS_SECRET_VALUE=not-for-logs\n')
        self.assertEqual(result['strict_success_summary_counts'],[7])
        self.assertEqual(result['recognized_verbose_test_rows'],{'PASSED':7})
        self.assertEqual(set(result['required_m5_test_statuses'].values()),{'PASSED'})
        self.assertNotIn('not-for-logs',str(result))
        self.assertFalse(result['release_authorized'])

    def test_warning_format_generic_and_strict(self):
        r=self.write('==== 1 passed, 2 warnings in 3.1s ====')
        self.assertEqual(r['strict_success_summary_counts'],[1])
        self.assertEqual(r['generic_summary_numeric_tokens']['warnings'],2)

    def test_skipped_m5_not_silent(self):
        r=self.write('collected 1 item\ntests/test_photo_comments_m5.py::'+self.m5[0]+' SKIPPED [ 2%]\n==== 1 skipped in 1.0s ====')
        self.assertEqual(r['required_m5_test_statuses'][self.m5[0]],'SKIPPED')
        self.assertEqual(r['strict_success_summary_counts'],[])

    def test_empty_log_rejected(self):
        self.path.write_bytes(b'')
        with self.assertRaisesRegex(m.Denied,'LOG_MISSING'):
            m.diagnose(self.path)

    def test_binary_log_rejected(self):
        self.path.write_bytes(b'hello\x00world')
        with self.assertRaisesRegex(m.Denied,'BINARY_LOG'):
            m.diagnose(self.path)

    def test_unexpected_candidate_rejected(self):
        wrong=self.home/'m5-backend-test.log'
        wrong.write_text('hello')
        with self.assertRaisesRegex(m.Denied,'UNEXPECTED_CANDIDATE'):
            m.diagnose(wrong)

    def test_symlink_log_rejected(self):
        target=self.home/'another.log';target.write_text('x')
        self.path.symlink_to(target)
        with self.assertRaisesRegex(m.Denied,'EXACT_LOG_PATH'):
            m.diagnose(self.path)

    def test_unknown_status_does_not_fake_pass(self):
        r=self.write('tests/test_photo_comments_m5.py::'+self.m5[0]+' NOOP [ 50%]\n===== 1 passed in 1.0s =====')
        self.assertEqual(r['recognized_m5_test_rows'],0)
        self.assertEqual(r['required_m5_test_statuses'][self.m5[0]],'NOT_SEEN')

    def test_differing_summary_parser_does_not_authorize(self):
        r=self.write('=== 6 passed, 1 xfailed in 1.44s ===')
        self.assertEqual(r['strict_success_summary_counts'],[])
        self.assertEqual(r['generic_summary_numeric_tokens']['xfailed'],1)
        self.assertFalse(r['backend_verified'])

    def test_ansi_stripped(self):
        r=self.write('tests/test_photo_comments_m5.py::'+self.m5[0]+' \x1b[32mPASSED\x1b[0m\n=== 1 passed in 1.0s ===')
        self.assertEqual(r['required_m5_test_statuses'][self.m5[0]],'PASSED')

if __name__=='__main__':unittest.main()
