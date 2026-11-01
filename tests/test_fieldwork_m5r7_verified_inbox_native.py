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

SCRIPT = Path(__file__).resolve().parents[1] / 'updater' / 'fieldwork_m5r7_launch_verified_inbox.py'
SPEC = importlib.util.spec_from_file_location('fieldwork_m5r7_local', SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def synthetic_archive(path):
    names = [
        'verify.py', 'launch_canary.sh', 'integrate.py',
        'm5r5_test_gate.py', 'test_m5r7_regressions.py',
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


class LocalM5R7SyntheticContract(unittest.TestCase):
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

    def test_synthetic_inbox_sha_and_19_member_manifest(self):
        self.assertEqual(M.locate_archive(self.home), self.archive)
        with zipfile.ZipFile(self.archive) as z:
            self.assertEqual(len(M.check_manifest(z)), 19)

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


if __name__=='__main__':
    unittest.main()
