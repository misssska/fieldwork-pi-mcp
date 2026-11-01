import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest import mock

p = Path(__file__).resolve().parents[1] / 'updater' / 'fieldwork_source_findings_triage.py'
spec=importlib.util.spec_from_file_location('fieldwork_local_triage',p)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

FAKE_AUDITOR='''import re
import zipfile
SECRET_PATTERNS = {'suspicious_assignment': re.compile(rb'(?im)^\\s*(?:password|secret)\\s*[:=]\\s*["\\x27]?([^\\s,"\\x27]{10,})')}
PLACEHOLDER = re.compile(rb'\\bnever-matches-this-42\\b')
def line_no(content, start): return content.count(b"\\n",0,start)+1
def audit(archive):
    rows=[]
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            for match in SECRET_PATTERNS['suspicious_assignment'].finditer(z.read(name)):
                rows.append({'file':name,'line':line_no(z.read(name),match.start()),'rule':'suspicious_assignment'})
    return {'status':'SOURCE_STRUCTURE_AND_SHA_PASS','files':107,
            'findings_count':len(rows),'findings':rows,'findings_truncated':False}
'''

class FindingsTriageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.auditor=self.base/'audit.py'
        self.auditor.write_text(FAKE_AUDITOR)
        self.archive=self.base/'snapshot.zip'
        lines=['password = "literal-example-secret-012345"']*10 + ['secret = os.getenv("NOT_A_REAL_SECRET")']*8
        # 10 test literals, 8 env refs, 8 runtime literals, 8 template refs.
        lines += ['password = "another-literal-placeholder-567890"']*8
        lines += ['secret: ${ENV_VALUE_MUST_NOT_LOG}']*8
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr('server/tests/test_api.py','\n'.join(lines[:10])+'\n')
            z.writestr('server/app/config.py','\n'.join(lines[10:26])+'\n')
            z.writestr('docker-compose.test.yml','\n'.join(lines[26:])+'\n')
        self.patchers=[mock.patch.object(m,'AUDITOR_SHA256',hashlib.sha256(self.auditor.read_bytes()).hexdigest()),
                       mock.patch.object(m,'ARCHIVE_SHA256',hashlib.sha256(self.archive.read_bytes()).hexdigest())]
        for pt in self.patchers:
            pt.start();self.addCleanup(pt.stop)

    def test_all_thirtyfour_reported_without_values(self):
        result=m.triage(self.archive,self.auditor)
        self.assertEqual(result['status'],'LOCAL_ASSIGNMENT_TRIAGE_COMPLETE')
        self.assertEqual(result['findings_count'],34)
        self.assertEqual(len(result['findings']),34)
        self.assertTrue(result['human_review_required'])
        self.assertFalse(result['ready_to_upload'])
        self.assertFalse(result['git_push_performed'])
        raw=json.dumps(result)
        for forbidden in ('literal-example-secret-012345','another-literal-placeholder-567890','ENV_VALUE_MUST_NOT_LOG','NOT_A_REAL_SECRET'):
            self.assertNotIn(forbidden,raw)

    def test_test_source_categorized_review(self):
        report=m.triage(self.archive,self.auditor)
        subset=[f for f in report['findings'] if f['file'].startswith('server/tests/')]
        self.assertEqual(len(subset),10)
        self.assertTrue(all(x['category']=='test_fixture_assignment_review' for x in subset))

    def test_environment_reference_categorized_review(self):
        report=m.triage(self.archive,self.auditor)
        self.assertIn('runtime_or_environment_reference_review',report['categories'])
        self.assertEqual(report['categories']['runtime_or_environment_reference_review'],8)

    def test_environment_template_categorized_review(self):
        report=m.triage(self.archive,self.auditor)
        self.assertEqual(report['categories']['environment_template_review'],8)

    def test_quote_literal_in_app_requires_review(self):
        report=m.triage(self.archive,self.auditor)
        self.assertEqual(report['categories']['possible_literal_assignment_review'],8)

    def test_auditor_tampered_is_refused(self):
        self.auditor.write_text('attacker')
        with self.assertRaisesRegex(m.TriageDenied,'AUDITOR_SHA256_MISMATCH'):
            m.triage(self.archive,self.auditor)

    def test_zip_tamper_refused(self):
        with self.archive.open('ab') as f:f.write(b'tamper')
        with self.assertRaisesRegex(m.TriageDenied,'ARCHIVE_SHA256_MISMATCH'):
            m.triage(self.archive,self.auditor)

    def test_fewer_findings_refused(self):
        self.archive2=self.base/'tampered-fixture.zip'
        with zipfile.ZipFile(self.archive) as a,zipfile.ZipFile(self.archive2,'w') as b:
            for n in a.namelist():
                d=a.read(n)
                if n=='server/tests/test_api.py':d=d.replace(b'password',b'irrelev',1)
                b.writestr(n,d)
        with mock.patch.object(m,'ARCHIVE_SHA256',hashlib.sha256(self.archive2.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(m.TriageDenied,'AUDIT_RECEIPT_DRIFT'):
                m.triage(self.archive2,self.auditor)

    def test_relative_path_rejected(self):
        with self.assertRaisesRegex(m.TriageDenied,'INPUT_PATH_DENIED'):
            m.triage(Path('snapshot.zip'),self.auditor)

    def test_symlink_archive_rejected(self):
        other=self.base/'link.zip';other.symlink_to(self.archive)
        with self.assertRaisesRegex(m.TriageDenied,'INPUT_PATH_DENIED'):
            m.triage(other,self.auditor)

    def test_cli_is_not_a_publisher(self):
        code=p.read_text()
        self.assertNotIn('requests.post(',code)
        self.assertNotIn('git push',code)
        self.assertNotIn('subprocess.run',code)
        self.assertNotIn('http://',code)
        self.assertNotIn('https://',code)

    def test_no_secrets_in_stdout(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            print(json.dumps(m.triage(self.archive,self.auditor)))
        self.assertNotIn('literal-example-secret-012345',out.getvalue())
        self.assertNotIn('another-literal-placeholder-567890',out.getvalue())

if __name__=='__main__':unittest.main()
