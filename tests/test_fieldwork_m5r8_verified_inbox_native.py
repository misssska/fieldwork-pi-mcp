"""Synthetic only. The private application ZIP is deliberately not in this repository."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'updater' / 'fieldwork_m5r8_launch_verified_inbox.py'
SPEC = importlib.util.spec_from_file_location('fieldwork_m5r8_local', SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def synthetic_archive(path):
    names = [
        'verify.py', 'launch_canary.sh', 'integrate.py',
        'm5r5_test_gate.py', 'test_m5r7_regressions.py', 'test_m5r8_regressions.py',
    ] + ['synthetic_%02d.py' % i for i in range(14)]
    content = {name: ('synthetic-not-real-app-' + name + '\n').encode() for name in names}
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in content.items()}
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in content.items():
            z.writestr('FieldWork_Paritas_M5/' + name, data)
        z.writestr('FieldWork_Paritas_M5/manifest.json', json.dumps(manifest))
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def config():
    return {
      'services': {
        'db': {'volumes':[{'type':'volume','source':'fieldwork-db','target':'/var/lib/postgresql/data'}]},
        'api': {'volumes':[], 'environment':{'DATABASE_URL':'postgresql+psycopg://stage:test@db:5432/fieldwork_stage'}},
        'nginx': {'ports':[{'published':'18085','target':80,'protocol':'tcp','host_ip':'192.168.22.13'}]},
      }, 'volumes': {'fieldwork-db': {}}, 'networks': {'default': {}},
    }


class LocalM5R8SyntheticContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / M.STATE_REL / M.M4_DIR
        self.base.mkdir(parents=True)
        self.inbox = self.home / '.local/state/inert-inbox'
        self.inbox.mkdir(parents=True)
        self.archive = self.inbox / 'sealed.bin'
        sha, size = synthetic_archive(self.archive)
        patch_sha = mock.patch.object(M, 'ARCHIVE_SHA', sha)
        patch_size = mock.patch.object(M, 'ARCHIVE_SIZE', size)
        patch_sha.start(); patch_size.start()
        self.addCleanup(patch_size.stop); self.addCleanup(patch_sha.stop)

    def _check(self, cfg):
        with mock.patch.object(M, 'checked_subprocess', return_value=json.dumps(cfg)):
            M.check_compose(self.base)

    def test_synthetic_inbox_sha_and_20_member_manifest(self):
        self.assertEqual(M.locate_archive(self.home), self.archive)
        with zipfile.ZipFile(self.archive) as z:
            self.assertEqual(len(M.check_manifest(z)), 20)

    def test_prepare_and_replay_without_docker(self):
        with mock.patch.object(M, 'checked_subprocess', side_effect=AssertionError('no Docker')):
            p = M.verified_bundle_path(self.home, self.archive)
            self.assertTrue(p.joinpath('verify.py').is_file())
            self.assertEqual(p, M.verified_bundle_path(self.home, self.archive))

    def test_tampered_prepared_file_denied(self):
        p = M.verified_bundle_path(self.home, self.archive)
        p.joinpath('verify.py').write_text('tamper')
        with self.assertRaises(SystemExit): M.verified_bundle_path(self.home, self.archive)

    def test_duplicate_sha_copy_denied(self):
        from shutil import copyfile
        d = self.home / '.local/share';d.mkdir(parents=True)
        copyfile(self.archive,d/'copy.zip')
        with self.assertRaises(SystemExit): M.locate_archive(self.home)

    def test_unrelated_bytes_denied(self):
        self.archive.write_bytes(b'INVALID')
        with self.assertRaises(SystemExit): M.locate_archive(self.home)

    def test_bad_member_content_denied(self):
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr('FieldWork_Paritas_M5/verify.py','tamper')
        with zipfile.ZipFile(self.archive) as z:
            with self.assertRaises(SystemExit): M.check_manifest(z)

    def test_good_stage_compose_passes(self):
        self._check(config())

    def test_stage_compose_no_bind_mounts(self):
        c=config();c['services']['api']['volumes']=[{'type':'bind','source':'/opt/fieldwork','target':'/app'}]
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_no_external_volume(self):
        c=config();c['volumes']['fieldwork-db']={'external':True}
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_no_external_network(self):
        c=config();c['networks']['default']={'external':True}
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_no_host_mode(self):
        c=config();c['services']['api']['network_mode']='host'
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_no_prod_db_url(self):
        c=config();c['services']['api']['environment']['DATABASE_URL']='postgresql+psycopg://x:y@192.168.22.13:5432/prod'
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_no_wildcard_bind_port(self):
        c=config();c['services']['nginx']['ports'][0]['host_ip']='0.0.0.0'
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_no_extra_service(self):
        c=config();c['services']['proxy2']={}
        with self.assertRaises(SystemExit): self._check(c)

    def test_stage_compose_requires_url(self):
        c=config();c['services']['api']['environment'].pop('DATABASE_URL')
        with self.assertRaises(SystemExit): self._check(c)


    def test_previous_log_rejects_unpinned_sha(self):
        p=self.home/M.STATE_REL/M.PREVIOUS_CANDIDATE/'m5-backend-test.log'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('pytest output 92 passed')
        with self.assertRaises(SystemExit):
            M.verify_previous_log(self.home,self.home)

    def test_previous_log_accepts_only_exact_92_and_five_m5(self):
        p=self.home/M.STATE_REL/M.PREVIOUS_CANDIDATE/'m5-backend-test.log'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('fake exact log',encoding='utf-8')
        class FakeModule:
            class ReceiptDenied(ValueError): pass
            @staticmethod
            def verify_backend(log):
                return {'total_passed':92,'photo_comment_tests':5}
        class FakeLoader:
            def exec_module(self, module): pass
        class FakeSpec:
            loader=FakeLoader()
        # Patch SHA/source module loading only in synthetic tests, without
        # writing to production or importing any private FieldWork code.
        with mock.patch.object(M,'PREVIOUS_LOG_SHA',M.filehash(p)), \
             mock.patch('importlib.util.spec_from_file_location',return_value=FakeSpec()), \
             mock.patch('importlib.util.module_from_spec',return_value=FakeModule()):
            M.verify_previous_log(self.home,self.home)

    def test_previous_log_denies_wrong_count_even_if_parser_says_success(self):
        p=self.home/M.STATE_REL/M.PREVIOUS_CANDIDATE/'m5-backend-test.log'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('fake pinned log')
        class FakeModule:
            class ReceiptDenied(ValueError): pass
            @staticmethod
            def verify_backend(log):
                return {'total_passed':90,'photo_comment_tests':5}
        class FakeLoader:
            def exec_module(self, module): pass
        class FakeSpec:
            loader=FakeLoader()
        with mock.patch.object(M,'PREVIOUS_LOG_SHA',M.filehash(p)), \
             mock.patch('importlib.util.spec_from_file_location',return_value=FakeSpec()), \
             mock.patch('importlib.util.module_from_spec',return_value=FakeModule()):
            with self.assertRaises(SystemExit):
                M.verify_previous_log(self.home,self.home)

if __name__=='__main__':
    unittest.main()
