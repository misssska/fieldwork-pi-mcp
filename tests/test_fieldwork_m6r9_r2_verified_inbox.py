"""Host-free tests for verified Pi M6+R9 inbox admission.
No Docker commands or Pi source writes are executed in this suite.
"""
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

SRC=Path(__file__).resolve().parents[1]/'updater/fieldwork_m6r9_r2_prepare_verified_inbox.py'
spec=importlib.util.spec_from_file_location('m6_launcher', SRC)
m6=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m6)


def artifact(path, *, tamper=False, traversal=False):
    base={
      'PhotoGallery.tsx':b'gallery',
      'PhotoGalleryM5.test.tsx':b'gallery test',
      'ReferenceTeam.tsx':b'team',
      'TeamDirectory.ts':b'directory',
      'account_api.py':b'account',
      'dev_login_alias.py':b'alias',
      'photo_comments_api.py':b'comments',
      'test_account_m6.py':b'account test',
    }
    manifest={'kind':'fieldwork-m6-r9-isolated-overlay-v1',
      'sha256':{k:sha256(v).hexdigest() for k,v in base.items()}}
    with ZipFile(path,'w',compression=ZIP_DEFLATED) as z:
        z.writestr('FieldWork_M6_R9/integrate.py',b'integrator')
        z.writestr('FieldWork_M6_R9/tests/test_integrate.py',b'test')
        z.writestr('FieldWork_M6_R9/MANIFEST.json',json.dumps(manifest))
        for k,v in base.items():
            z.writestr('FieldWork_M6_R9/bundle/'+('../' if traversal and k=='ReferenceTeam.tsx' else '')+k,
                       b'tampered' if tamper and k=='account_api.py' else v)
    return path

class VerifyLauncher(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.archive=artifact(self.root/'m6-r9.zip')

    def test_correct_manifest_validates_without_host_action(self):
        self.assertTrue(m6.check_bundle(self.archive))

    def test_hash_mismatch_fails_closed(self):
        artifact(self.archive,tamper=True)
        with self.assertRaisesRegex(RuntimeError,'MANIFEST_SHA_DRIFT'):
            m6.check_bundle(self.archive)

    def test_path_traversal_fails_closed(self):
        artifact(self.archive,traversal=True)
        with self.assertRaisesRegex(RuntimeError,'ZIP_ENTRY_UNSAFE'):
            m6.check_bundle(self.archive)

    def test_deterministic_exact_archive_discovery(self):
        home=self.root/'home'; folder=home/'.local/state';folder.mkdir(parents=True)
        exact=folder/'transfer.bin';exact.write_bytes(self.archive.read_bytes())
        with patch.object(m6.Path,'home',return_value=home), \
             patch.object(m6,'ARCHIVE_SHA',sha256(exact.read_bytes()).hexdigest()), \
             patch.object(m6,'ARCHIVE_SIZE',exact.stat().st_size):
            self.assertEqual(m6.locate(),exact)
            another=home/'.local/share';another.mkdir(parents=True)
            (another/'second.bin').write_bytes(exact.read_bytes())
            with self.assertRaisesRegex(RuntimeError,'DUPLICATE_EXACT_ARCHIVES'):
                m6.locate()

    def test_extract_replay_detects_tamper(self):
        stage=self.root/'state';stage.mkdir()
        with patch.object(m6,'STATE',stage),patch.object(m6,'BUNDLE_PATH',stage/'bundle'):
            root=m6.extract_bundle(self.archive)
            self.assertTrue((root/'integrate.py').is_file())
            self.assertEqual(root,m6.extract_bundle(self.archive))
            (root/'bundle/PhotoGallery.tsx').write_text('tampered')
            with self.assertRaisesRegex(RuntimeError,'EXISTING_BUNDLE_TAMPERED'):
                m6.extract_bundle(self.archive)

    def test_compose_refuses_external_db(self):
        template={'services':{
            'test-db':{'tmpfs':['/var/lib/postgresql/data']},
            'backend-tests':{'environment':{'FIELDWORK_TESTING':'1',
                'FIELDWORK_TEST_DATABASE_URL':'postgresql+psycopg://t:t@production:5432/x'}},
            },'networks':{},'volumes':{}}
        with patch.object(m6.subprocess,'check_output',return_value=json.dumps(template)):
            with self.assertRaisesRegex(RuntimeError,'TEST_DB_HOST_INVALID'):
                m6.check_test_compose(self.root)
        template['services']['backend-tests']['environment']['FIELDWORK_TEST_DATABASE_URL']='postgresql+psycopg://t:t@test-db:5432/test'
        with patch.object(m6.subprocess,'check_output',return_value=json.dumps(template)):
            m6.check_test_compose(self.root)

if __name__ == '__main__':unittest.main()
