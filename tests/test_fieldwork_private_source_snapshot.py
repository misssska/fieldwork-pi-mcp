import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

s = importlib.util.spec_from_file_location('snapshot', str(Path(__file__).resolve().parents[1] / 'updater' / 'fieldwork_private_source_snapshot.py'))
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.root = (self.parent/'repo').resolve()
        self.root.mkdir()
        def git(*args):
            subprocess.run(['git', '-C', str(self.root), *args], check=True, stdout=subprocess.DEVNULL)
        git('init','-q');git('config','user.email','no@example.invalid');git('config','user.name','No')
        def put(rel,data):
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
        put('frontend/package-lock.json','{"packages":{}}')
        put('frontend/package.json','{"name":"test"}')
        put('frontend/src/App.tsx','export const p = 1')
        put('server/app/main.py','print("safe")')
        put('docs/HANDOFF.md','safe doc')
        put('.env','PRODUCTION_PASSWORD=very-secret')
        put('storage/uploads/private-photo.jpg','binary')
        git('add','frontend','server','docs');git('commit','-qm','initial')
        put('frontend/src/Added.tsx','export const u = 2')
        put('frontend/src/App.tsx','export const p = 3')
        self.destination = self.parent/'snapshot.zip'
        self.git=lambda *a: subprocess.run(['git','-C',str(self.root),*a],check=True,capture_output=True).stdout

    def test_preserves_dirty_source_and_excludes_private(self):
        before=self.git('status','--porcelain')
        report=m.export(self.root,self.destination)
        self.assertTrue(report['dirty_worktree'])
        self.assertEqual(self.git('status','--porcelain'),before)
        with zipfile.ZipFile(self.destination) as z:
            n=set(z.namelist())
            self.assertIn('frontend/src/Added.tsx',n)
            self.assertIn('frontend/src/App.tsx',n)
            self.assertNotIn('.env',n)
            self.assertNotIn('storage/uploads/private-photo.jpg',n)
            self.assertEqual(z.read('frontend/src/App.tsx'),b'export const p = 3')
            self.assertEqual(z.read('_FIELDWORK_PRIVATE_SOURCE_MANIFEST.json')[:1],b'{')
        self.assertEqual(report['source_files']['frontend/src/App.tsx'],hashlib.sha256(b'export const p = 3').hexdigest())


    def test_empty_tracked_package_init_is_preserved(self):
        # The real FieldWork Pi has server/app/__init__.py = 0 bytes.
        p = self.root/'server/app/__init__.py'
        p.touch()
        self.git('add', 'server/app/__init__.py')
        status_before = self.git('status', '--porcelain')
        result = m.export(self.root, self.destination)
        self.assertEqual(result['source_files']['server/app/__init__.py'],
                         hashlib.sha256(b'').hexdigest())
        with zipfile.ZipFile(self.destination) as z:
            self.assertIn('server/app/__init__.py', z.namelist())
            self.assertEqual(z.getinfo('server/app/__init__.py').file_size, 0)
            self.assertEqual(z.read('server/app/__init__.py'), b'')
        self.assertEqual(m.verify(self.destination)['status'],
                         'FIELDWORK_PRIVATE_SOURCE_ARCHIVE_VERIFIED')
        self.assertEqual(self.git('status', '--porcelain'), status_before)

    def test_empty_untracked_typescript_file_is_preserved(self):
        p = self.root/'frontend/src/Empty.test.ts'
        p.touch()
        before = self.git('status', '--porcelain')
        report = m.export(self.root, self.destination)
        self.assertEqual(report['source_files']['frontend/src/Empty.test.ts'],
                         hashlib.sha256(b'').hexdigest())
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual(m.verify(self.destination)['file_count'], 7)

    def test_exact_missing_build_and_migration_sources_are_admissible(self):
        required = {
            '.dockerignore',
            'Dockerfile',
            '.github/workflows/backend-tests.yml',
            'nginx/Dockerfile',
            'server/Dockerfile',
            'server/Dockerfile.test',
            'server/alembic/script.py.mako',
            'server/scripts/rotate_admin_password.py',
        }
        self.assertEqual(set(m.ESSENTIAL_EXACT_SOURCE_FILES), required)
        self.assertTrue(all(m.admissible(p) for p in required))
        for rejected in (
                '.env', '.env.example', 'nginx/Dockerfile.backup',
                '.github/workflows/unreviewed.yml',
                'server/scripts/reset_password.py',
                'server/alembic/other.py.mako',
                'reference/fieldwork-22.html',
                'storage/uploads/customer-photo.jpg',
                'scripts/fwcompose',
                'frontend/src/../../.env'):
            with self.subTest(rejected=rejected):
                self.assertFalse(m.admissible(rejected))

    def test_missing_build_and_migration_sources_preserved_in_zip(self):
        required = sorted(m.ESSENTIAL_EXACT_SOURCE_FILES)
        for rel in required:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("verified fixture source " + rel + "\\n")
        self.git('add', *required)
        before = self.git('status', '--porcelain', '--untracked-files=all')
        result = m.export(self.root, self.destination)
        self.assertEqual(m.verify(self.destination)['status'],
                         'FIELDWORK_PRIVATE_SOURCE_ARCHIVE_VERIFIED')
        with zipfile.ZipFile(self.destination) as z:
            names = set(z.namelist())
            self.assertTrue(set(required).issubset(names))
            for rel in required:
                data = z.read(rel)
                self.assertEqual(hashlib.sha256(data).hexdigest(),
                                 result['source_files'][rel])
        self.assertEqual(self.git('status', '--porcelain', '--untracked-files=all'), before)

    def test_deterministic_reproducible_archive_bytes(self):
        m.export(self.root,self.destination)
        second=self.parent/'second.zip';m.export(self.root,second)
        self.assertEqual(self.destination.read_bytes(),second.read_bytes())

    def test_refuses_inside_worktree_output(self):
        with self.assertRaisesRegex(m.SnapshotDenied,'DESTINATION_MUST_BE_OUTSIDE_SOURCE'):
            m.export(self.root,self.root/'source.zip')

    def test_refuses_output_overwrite(self):
        self.destination.write_bytes(b'old')
        with self.assertRaisesRegex(m.SnapshotDenied,'INVALID_DESTINATION'):
            m.export(self.root,self.destination)
        self.assertEqual(self.destination.read_bytes(),b'old')

    def test_refuses_credential_bytes_in_allowed_file(self):
        (self.root/'frontend/src/Added.tsx').write_text('const x="ghp_'+'a'*25+'"')
        with self.assertRaisesRegex(m.SnapshotDenied,'EMBEDDED_CREDENTIAL_DETECTED'):
            m.export(self.root,self.destination)
        self.assertFalse(self.destination.exists())

    def test_refuses_symlinked_candidate(self):
        p=self.root/'frontend/src/Added.tsx';p.unlink();p.symlink_to(self.root/'frontend/src/App.tsx')
        with self.assertRaisesRegex(m.SnapshotDenied,'SYMLINK_SOURCE_DENIED'):
            m.export(self.root,self.destination)

    def test_refuses_file_path_traversal(self):
        self.assertFalse(m.admissible('frontend/src/../../.env'))
        self.assertFalse(m.admissible('server/.env'))
        self.assertFalse(m.admissible('reference/fieldwork-22.html'))

    def test_refuses_missing_lockfile(self):
        (self.root/'frontend/package-lock.json').unlink()
        with self.assertRaises(m.SnapshotDenied):
            m.export(self.root,self.destination)

    def test_no_git_push_or_index_write_contract(self):
        text=(Path(__file__).resolve().parents[1] / 'updater' / 'fieldwork_private_source_snapshot.py').read_text()
        self.assertNotIn("('push'",text)
        with self.assertRaisesRegex(m.SnapshotDenied,'GIT_COMMAND_DENIED'):
            m.command(self.root,('push',))

    def test_independent_archive_verify_positive(self):
        m.export(self.root, self.destination)
        report = m.verify(self.destination)
        self.assertEqual(report['file_count'], 6)
        self.assertFalse(report['ready_to_upload'])

    def test_independent_archive_verify_rejects_added_member(self):
        m.export(self.root, self.destination)
        with zipfile.ZipFile(self.destination, 'a') as z:
            z.writestr('frontend/src/injected.tsx', 'unverified')
        with self.assertRaisesRegex(m.SnapshotDenied, 'ARCHIVE_MANIFEST_CONTRACT_DENIED'):
            m.verify(self.destination)

    def test_independent_archive_verify_rejects_changed_member(self):
        m.export(self.root, self.destination)
        with zipfile.ZipFile(self.destination) as z:
            payload = {name: z.read(name) for name in z.namelist()}
        payload['frontend/src/App.tsx'] = b'tampered'
        with zipfile.ZipFile(self.destination, 'w') as z:
            for name, data in payload.items():
                z.writestr(name, data)
        with self.assertRaisesRegex(m.SnapshotDenied, 'ARCHIVE_MEMBER_HASH_OR_PATH_DENIED'):
            m.verify(self.destination)

    def test_zip_permissions_private(self):
        m.export(self.root,self.destination)
        self.assertEqual(self.destination.stat().st_mode & 0o777,0o600)

if __name__ == '__main__':unittest.main()
