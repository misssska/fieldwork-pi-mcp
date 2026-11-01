import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

P = Path(__file__).with_name('fieldwork_local_18_risk_review.py')
spec = importlib.util.spec_from_file_location('review18', P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ORIGINAL_SHA_CHECK = m.checked_sha

class Review18Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.zpath = self.root / 'source.zip'
        self.auditor = self.root / 'auditor.py'
        self.triage = self.root / 'triage.py'
        self.auditor.write_text('fake')
        self.triage.write_text('fake')
        with zipfile.ZipFile(self.zpath, 'w') as z:
            for path, line_nums in m.EXPECTED.items():
                content = ['# filler'] * max(line_nums)
                for n in line_nums:
                    content[n-1] = ('password_hash = get_secure_value(user)' if path.endswith('.py')
                                    else 'POSTGRES_PASSWORD: super-real-secret-value-NEVER-PRINT')
                z.writestr(path, '\n'.join(content)+'\n')
        self.report={
            'status':'LOCAL_ASSIGNMENT_TRIAGE_COMPLETE',
            'findings_count':34,
            'sensitive_values_emitted':False,
            'ready_to_upload':False,
            'findings':[{'file':p,'line':n,'category':'expression_or_unknown_assignment_review'}
                        for p,nums in m.EXPECTED.items() for n in nums] +
                       [{'file':'server/tests/test_api.py','line':i+1,
                         'category':'test_fixture_assignment_review'} for i in range(16)],
        }
        class Fake:
            def __init__(this, resp): this.resp=resp
            def triage(this,*args): return this.resp
        patch1=mock.patch.object(m,'checked_sha',return_value=None)
        patch2=mock.patch.object(m,'import_checked',return_value=Fake(self.report))
        patch1.start();patch2.start();self.addCleanup(patch1.stop);self.addCleanup(patch2.stop)

    def test_review_returns_all_eighteen_without_values(self):
        result=m.review(self.zpath,self.triage,self.auditor)
        self.assertEqual(result['findings_examined'],18)
        self.assertFalse(result['ready_to_upload'])
        self.assertTrue(result['manual_secret_and_license_review_required'])
        body=json.dumps(result)
        self.assertNotIn('super-real-secret',body)
        self.assertNotIn('get_secure_value',body)
        self.assertEqual(result['categories']['yaml_inline_value_review'],9)
        self.assertEqual(result['categories']['python_function_result_review'],9)

    def test_bad_unknown_coverage_blocks(self):
        self.report['findings']=[x for x in self.report['findings'] if not
                                 (x['file']=='server/app/models.py' and x['line']==16)]
        with self.assertRaisesRegex(m.ReviewBlocked,'EXACT_18_FINDINGS_DRIFT'):
            m.review(self.zpath,self.triage,self.auditor)

    def test_too_many_unknowns_blocks(self):
        self.report['findings'][18]['category']='expression_or_unknown_assignment_review'
        with self.assertRaisesRegex(m.ReviewBlocked,'EXACT_18_FINDINGS_DRIFT'):
            m.review(self.zpath,self.triage,self.auditor)

    def test_tainted_triage_status_blocks(self):
        self.report['ready_to_upload']=True
        with self.assertRaisesRegex(m.ReviewBlocked,'TRIAGE_RECEIPT_DRIFT'):
            m.review(self.zpath,self.triage,self.auditor)

    def test_unsafe_python_ast_syntax_blocks(self):
        with zipfile.ZipFile(self.zpath) as z:
            files={n:z.read(n) for n in z.namelist()}
        content=files['server/scripts/init_db.py'].decode().splitlines()
        content[20]='password_hash = ('
        files['server/scripts/init_db.py']=('\n'.join(content)+'\n').encode()
        with zipfile.ZipFile(self.zpath,'w') as z:
            for n,b in files.items(): z.writestr(n,b)
        with self.assertRaisesRegex(m.ReviewBlocked,'PYTHON_SYNTAX_REVIEW_BLOCKED'):
            m.review(self.zpath,self.triage,self.auditor)

    def test_yaml_shape_static_not_approved(self):
        self.assertEqual(m.yaml_shape('DB_PASSWORD: very-private-static'), 'yaml_inline_value_review')
        self.assertEqual(m.yaml_shape('DB_PASSWORD: ${UNSEEN_VAR}'), 'yaml_variable_template_review')
        self.assertEqual(m.yaml_shape('DB_PASSWORD: {{ secrets.foo }}'), 'yaml_variable_template_review')
        self.assertEqual(m.yaml_shape('DB_PASSWORD: [one,two]'), 'yaml_structured_expression_review')

    def test_python_ast_static_and_runtime(self):
        t=ast.parse('password_hash = "do-not-print-opaque-value"\n')
        self.assertEqual(m.python_shape(t,1),'python_direct_literal_review')
        t=ast.parse('password_hash = read_secret()\n')
        self.assertEqual(m.python_shape(t,1),'python_function_result_review')
        t=ast.parse('password_hash = settings.password\n')
        self.assertEqual(m.python_shape(t,1),'python_runtime_reference_review')

    def test_python_annotated_model_shape(self):
        t=ast.parse('password_hash: Mapped[str] = mapped_column(String(255))\n')
        self.assertEqual(m.python_shape(t,1),'python_annotated_field_definition_review')

    def test_real_sha_gate_rejects_altered_input(self):
        with mock.patch.object(m,'checked_sha',side_effect=ORIGINAL_SHA_CHECK) as check:
            with self.assertRaisesRegex(m.ReviewBlocked,'ARCHIVE_SHA256_MISMATCH'):
                m.review(self.zpath,self.triage,self.auditor)
            self.assertTrue(check.called)

    def test_no_unsafe_io_and_explicit_no_publish(self):
        source=P.read_text()
        self.assertNotIn('requests.post',source)
        self.assertNotIn('subprocess.run',source)
        self.assertNotIn('git push',source)
        self.assertIn("'ready_to_upload':False",source)

if __name__=='__main__':
    unittest.main()
