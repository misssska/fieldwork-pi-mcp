"""Local fail-closed R4 regression checks. All Docker calls mocked; no host writes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / 'updater' / 'fieldwork_m6r9_r4_backend_fixture_repair.py'
spec = importlib.util.spec_from_file_location('m6_r4_repair', SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
# Synthetic fixture: never commit private FieldWork app source to public MCP repo.
SOURCE = b'fixture\nuser@example.com\n' + b'\n'.join((b'user%d@example.test' % n) for n in range(4)) + b'\n'


class R4SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / 'stage-v06'
        self.state.mkdir()
        self.base = self.state / 'parity-m5.Krm2sA3i'
        self.base.mkdir()
        self.candidate = self.state / 'parity-m6._sdfbhky'
        self.candidate.mkdir()
        self.path = self.candidate / m.TESTFILE_REL
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(SOURCE)
        self.front = self.candidate / m.FRONT_TEST_REL
        self.front.parent.mkdir(parents=True)
        self.front.write_text('TEST FIXTURE', encoding='utf-8')
        (self.candidate / m.COMPOSE_FILE).write_text('TEST FIXTURE')
        (self.candidate / '.m6-r9-source-receipt.json').write_text(json.dumps({
            'source':str(self.base),
            'candidate':str(self.state / '.parity-m6-preparing._sdfbhky'),
            'status':'M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED',
            'production_modified':False,
        }))
        (self.candidate / m.FRONT_R3_LOG).write_text('Test Files  17 passed (17)\nTests  107 passed (107)\n')
        (self.candidate / m.BACK_R3_LOG).write_text(
            '\n'.join('FAILED tests/test_account_m6.py::'+c for c in m.REQUIRED_CASES[:3])
            + '\n special-use or reserved name @example.test\n3 failed, 92 passed\n')
        (self.candidate / m.CLEANUP_R3_LOG).write_text('CLEANUP_EXIT=0\n')
        for name,value in [('STATE',self.state),('BASE',self.base),('CANDIDATE',self.candidate),
                           ('FRONT_TEST_SHA',hashlib.sha256(self.front.read_bytes()).hexdigest()),
                           ('TESTFILE_BEFORE_SHA',hashlib.sha256(SOURCE).hexdigest()),
                           ('TESTFILE_AFTER_SHA',hashlib.sha256(SOURCE.replace(b'@example.test',b'@example.com')).hexdigest())]:
            p=patch.object(m,name,value)
            p.start(); self.addCleanup(p.stop)

    def test_exact_four_fixture_domains_only(self):
        modified=m.amended_bytes(SOURCE)
        self.assertEqual(modified.count(b'@example.com'),SOURCE.count(b'@example.com')+4)
        self.assertNotIn(b'@example.test',modified)
        self.assertEqual(modified,SOURCE.replace(b'@example.test',b'@example.com'))
        self.assertEqual(m.sha(modified),m.TESTFILE_AFTER_SHA)

    @unittest.skipUnless(importlib.util.find_spec("email_validator"), "validator not installed in generic updater suite")
    def test_production_email_validator_remains_strict(self):
        from email_validator import EmailSyntaxError, validate_email
        with self.assertRaises(EmailSyntaxError):
            validate_email('worker@example.test',check_deliverability=False)
        self.assertEqual(validate_email('worker@example.com',check_deliverability=False).normalized,
                         'worker@example.com')

    def test_source_tamper_blocks(self):
        with self.assertRaisesRegex(RuntimeError,'TEST_SOURCE_HASH_MISMATCH'):
            m.amended_bytes(SOURCE+b'!')

    def test_only_exact_four_domains_allowed(self):
        b=SOURCE.replace(b'@example.test',b'@example.org',1)
        with patch.object(m,'TESTFILE_BEFORE_SHA',hashlib.sha256(b).hexdigest()):
            with self.assertRaisesRegex(RuntimeError,'EXACT_FOUR_EMAIL_FIXTURES_REQUIRED'):
                m.amended_bytes(b)

    def test_pinned_candidate_and_previous_failure_evidence(self):
        self.assertEqual(m.stage_guard(),self.path)
        (self.candidate/m.CLEANUP_R3_LOG).write_text('CLEANUP_EXIT=1')
        with self.assertRaisesRegex(RuntimeError,'R3_TEST_DB_CLEANUP_NOT_PROVEN'):
            m.stage_guard()

    def test_bad_receipt_denied_and_env_guarded(self):
        p=self.candidate/'.m6-r9-source-receipt.json'
        v=json.loads(p.read_text());v['source']='/opt/fieldwork';p.write_text(json.dumps(v))
        with self.assertRaisesRegex(RuntimeError,'M6_SOURCE_RECEIPT_INVALID'):
            m.stage_guard()
        v['source']=str(self.base);p.write_text(json.dumps(v))
        (self.candidate/'.env').write_text('sensitive=bad')
        with self.assertRaisesRegex(RuntimeError,'CANDIDATE_ENV_FILE_PRESENT'):
            m.stage_guard()

    def test_original_backup_preserved_and_repeat_denied(self):
        m.patch_test(self.path)
        backup=self.path.with_name('test_account_m6.py.m6-r4-original.bak')
        self.assertEqual(backup.read_bytes(),SOURCE)
        self.assertEqual(self.path.read_bytes(),m.amended_bytes(SOURCE))
        with self.assertRaisesRegex(RuntimeError,'TEST_SOURCE_HASH_MISMATCH'):
            m.patch_test(self.path)

    def test_no_compose_external_resources_or_public_db(self):
        cfg={'services':{
            'test-db':{'tmpfs':['/var/lib/postgresql/data'],'ports':['5432:5432']},
            'backend-tests':{'environment':{
                'FIELDWORK_TESTING':'1','FIELDWORK_TEST_DATABASE_URL':'postgresql+psycopg://u:p@test-db:5432/test'}}
        }}
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(cfg),'')):
            with self.assertRaisesRegex(RuntimeError,'ISOLATED_COMPOSE_UNSAFE_SERVICE'):
                m.compose_guard()

    def test_no_external_database_allowed(self):
        cfg={'services':{
            'test-db':{'tmpfs':['/var/lib/postgresql/data']},
            'backend-tests':{'environment':{
                'FIELDWORK_TESTING':'1','FIELDWORK_TEST_DATABASE_URL':'postgresql+psycopg://u:p@production-db:5432/test'}}
        }}
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(cfg),'')):
            with self.assertRaisesRegex(RuntimeError,'ISOLATED_TEST_DB_URL_OUTSIDE_PRIVATE_PROJECT'):
                m.compose_guard()

    def test_failure_writes_dedicated_log_not_overwrite(self):
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],7,'','')):
            with self.assertRaisesRegex(RuntimeError,'PROCESS_FAILED:m6-r4-exit-code.log:exit=7'):
                m.run_logged(['pytest'],'m6-r4-exit-code.log',30)
        self.assertTrue((self.candidate/'m6-r4-exit-code.log').is_file())
        with self.assertRaisesRegex(RuntimeError,'LOG_ALREADY_EXISTS'):
            m.run_logged(['pytest'],'m6-r4-exit-code.log',30)

    def test_backend_cleanup_scoped_and_no_volume_deletion(self):
        calls=[]
        def fake_run(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,'','')
        with patch.object(m,'run_logged',return_value='95 passed\n') as run_logged,\
             patch.object(m.subprocess,'run',side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError,'BACKEND_REQUIRED_CASE_NOT_PASSED'):
                m.backend_tests()
        self.assertEqual(calls[0][:6],['docker','compose','-p',m.TEST_PROJECT,'-f',m.COMPOSE_FILE])
        self.assertEqual(calls[0][-2:],['down','--remove-orphans'])
        self.assertNotIn('-v',calls[0])
        self.assertEqual((self.candidate/m.CLEANUP_LOG).read_text(),'CLEANUP_EXIT=0\n')

    def test_runtime_main_does_not_deploy(self):
        with patch.object(m,'stage_guard',return_value=self.path),\
             patch.object(m,'compose_guard'),patch.object(m,'patch_test') as pt,\
             patch.object(m,'backend_tests') as bt,\
             patch.object(m.sys,'argv',['r4','--repair-and-test']):
            m.main()
        pt.assert_called_once_with(self.path)
        bt.assert_called_once()


if __name__=='__main__':
    unittest.main()
