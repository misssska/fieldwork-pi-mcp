import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from unittest.mock import patch

try:
    from updater import fieldwork_private_archive_audit as app
except ModuleNotFoundError:
    import fieldwork_private_archive_audit as app


def fixtures(*, secret=False, path_override=None, omit=None, bad_bytes=False, symlink=False):
    paths = set(app.REQUIRED)
    paths.update(f'frontend/src/generated/fixture{i:03d}.ts' for i in range(app.EXPECTED_FILES - len(paths)))
    if omit:
        paths.remove(omit)
        paths.add('frontend/src/replacement.ts')
    if path_override:
        paths.remove('frontend/src/generated/fixture000.ts')
        paths.add(path_override)
    assert len(paths) == app.EXPECTED_FILES
    data = {p: f'// synthetic source fixture {p}\n'.encode() for p in paths}
    data['server/app/__init__.py'] = b''
    if secret:
        data['frontend/src/generated/fixture002.ts'] = b'const token = "ghp_ABCDEFGHIJKLMNOPQRSTUV123456789"\n'
    manifest = {
        'format': 'FIELDWORK_PRIVATE_SOURCE_CANDIDATE_V1',
        'source_head': app.EXPECTED_SOURCE_HEAD,
        'source_modified': False,
        'remote_push_performed': False,
        'contains_private_data_audit': 'REVIEW_REQUIRED_BEFORE_UPLOAD',
        'source_files': {k: hashlib.sha256(v).hexdigest() for k,v in data.items()},
        'source_bytes': sum(map(len, data.values())),
    }
    if bad_bytes:
        manifest['source_files']['frontend/package.json'] = '0'*64
    return data, manifest


def write_archive(target, payload, manifest, symlink_name=None, extra=None):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for path, content in sorted(payload.items()):
            info=zipfile.ZipInfo(path)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=((stat.S_IFLNK if path==symlink_name else stat.S_IFREG)|0o644)<<16
            z.writestr(info,content)
        z.writestr(app.MANIFEST,json.dumps(manifest).encode())
        if extra:
            z.writestr(extra,b'extra')


class AuditUnit(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.zip=Path(self.dir.name)/'archive.zip'

    def run_audit(self, **args):
        data,report=fixtures(**args)
        write_archive(self.zip,data,report)
        with patch.object(app,'EXPECTED_ARCHIVE_SHA256',hashlib.sha256(self.zip.read_bytes()).hexdigest()):
            return app.audit(self.zip)

    def test_accepts_complete_synthetic_file_inventory(self):
        r=self.run_audit()
        self.assertEqual(r['status'],'SOURCE_STRUCTURE_AND_SHA_PASS')
        self.assertEqual(r['files'],107)
        self.assertEqual(r['findings_count'],0)
        self.assertFalse(r['ready_to_upload'])
        self.assertTrue(r['private_data_review_required'])

    def test_detects_credential_without_printing_value(self):
        r=self.run_audit(secret=True)
        self.assertGreater(r['findings_count'],0)
        self.assertNotIn('ABCDEFGHIJKLMNOPQRSTUV',json.dumps(r))
        self.assertTrue(any(x['rule']=='github_token' for x in r['findings']))

    def test_denies_tampered_archive_hash(self):
        data,manifest=fixtures()
        write_archive(self.zip,data,manifest)
        with self.assertRaisesRegex(app.AuditDenied,'ZIP_SHA256_MISMATCH'):
            app.audit(self.zip)

    def test_denies_incorrect_member_hash(self):
        data,manifest=fixtures(bad_bytes=True)
        write_archive(self.zip,data,manifest)
        with patch.object(app,'EXPECTED_ARCHIVE_SHA256',hashlib.sha256(self.zip.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(app.AuditDenied,'ZIP_SOURCE_MEMBER_HASH_MISMATCH'):
                app.audit(self.zip)

    def test_denies_forbidden_path(self):
        with self.assertRaisesRegex(app.AuditDenied,'ZIP_UNSAFE_PATH_DENIED'):
            self.run_audit(path_override='frontend/src/../.env')

    def test_denies_upload_file(self):
        with self.assertRaisesRegex(app.AuditDenied,'ZIP_UNSAFE_PATH_DENIED'):
            self.run_audit(path_override='uploads/customer.png')

    def test_denies_missing_dockerfile(self):
        with self.assertRaisesRegex(app.AuditDenied,'REQUIRED_FILES_MISSING'):
            self.run_audit(omit='server/Dockerfile')

    def test_denies_symlink_member(self):
        data,manifest=fixtures()
        write_archive(self.zip,data,manifest,symlink_name='server/Dockerfile')
        with patch.object(app,'EXPECTED_ARCHIVE_SHA256',hashlib.sha256(self.zip.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(app.AuditDenied,'ZIP_SYMLINK_OR_SPECIAL_DENIED'):
                app.audit(self.zip)

    def test_denies_unexpected_extra_member(self):
        data,manifest=fixtures()
        write_archive(self.zip,data,manifest,extra='secrets/.env')
        with patch.object(app,'EXPECTED_ARCHIVE_SHA256',hashlib.sha256(self.zip.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(app.AuditDenied,'ZIP_MEMBER_COUNT_DENIED'):
                app.audit(self.zip)

    def test_denies_wrong_source_head(self):
        data,manifest=fixtures()
        manifest['source_head']='a'*40
        write_archive(self.zip,data,manifest)
        with patch.object(app,'EXPECTED_ARCHIVE_SHA256',hashlib.sha256(self.zip.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(app.AuditDenied,'ZIP_MANIFEST_CONTEXT_INVALID'):
                app.audit(self.zip)

    def test_denies_wrong_zero_byte_init(self):
        data,manifest=fixtures()
        data['server/app/__init__.py']=b'changed'
        manifest['source_files']['server/app/__init__.py']=hashlib.sha256(b'changed').hexdigest()
        manifest['source_bytes']=sum(map(len,data.values()))
        write_archive(self.zip,data,manifest)
        with patch.object(app,'EXPECTED_ARCHIVE_SHA256',hashlib.sha256(self.zip.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(app.AuditDenied,'ZERO_BYTE_INIT_DRIFT'):
                app.audit(self.zip)

    def test_denies_secret_text_not_archive_approval(self):
        r=self.run_audit(secret=True)
        self.assertFalse(r['ready_to_upload'])
        self.assertTrue(r['private_data_review_required'])

    def test_safe_name_never_admits_env_or_backup(self):
        for p in ('.env','server/.env','frontend/src/../.env','reference/fieldwork-22.html',
                  'server/upload/secret.txt','storage/file.txt','frontend/src/../../Dockerfile',
                  '.github/workflows/unsafe.yml','../Dockerfile'):
            with self.subTest(path=p):
                self.assertFalse(app.safe_name(p))

    def test_denies_nonabsolute_path(self):
        with self.assertRaisesRegex(app.AuditDenied,'ZIP_PATH_NOT_REGULAR_OR_ABSOLUTE'):
            app.audit(Path('relative.zip'))

    def test_denies_false_secretless_approval(self):
        r=self.run_audit()
        self.assertFalse(r['ready_to_upload'])
        self.assertTrue(r['private_data_review_required'])

if __name__=='__main__':
    unittest.main()
