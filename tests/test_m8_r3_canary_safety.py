import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

MODULE_PATH=Path(__file__).with_name('fieldwork_m8_r3_canary_18087.py')
if not MODULE_PATH.is_file():
    MODULE_PATH=Path(__file__).resolve().parents[1]/'updater/fieldwork_m8_r3_first_canary_18087.py'
spec=importlib.util.spec_from_file_location('m8_canary', MODULE_PATH)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def original():
    return {'services':{
        'db':{'environment':{'POSTGRES_PASSWORD':'oldpassword'}},
        'api':{'environment':{
            'DATABASE_URL':'postgresql+psycopg://fieldwork:oldpassword@db:5432/fieldwork',
            'JWT_SECRET':'oldsigning','ADMIN_PASSWORD':'oldadminpass',
            'ADMIN_EMAIL':'admin@fieldwork.local',
            'FIELDWORK_DEV_ADMIN_ALIAS':'0'
        }},
        'nginx':{'image':'fieldwork-web:m6-old'}
    }}


def rendered(tmpdir, override):
    project=m.PROJECT
    return {'name':project,
      'networks':{'default':{'name':project+'_default'}},
      'volumes':{'postgres_data':{'name':project+'_postgres_data'},
                 'file_storage':{'name':project+'_file_storage'}},
      'services':{
        'db':{'image':'postgres:18-alpine','environment':override['services']['db']['environment'],
              'volumes':[{'type':'volume','source':'postgres_data','target':'/var/lib/postgresql'}]},
        'api':{'build':{'context':str(tmpdir/'server')},
              'image':project+'-api','environment':{**original()['services']['api']['environment'],
                               **override['services']['api']['environment']},
              'volumes':[{'type':'volume','source':'file_storage','target':'/data/storage'}]},
        'nginx':{'build':{'context':str(tmpdir)},'image':'fieldwork-web:m8-r3-canary',
                 'ports':[{'host_ip':'192.168.22.13','published':'18087','target':80,'protocol':'tcp'}],
                 'volumes':[{'type':'volume','source':'file_storage','target':'/srv/storage','read_only':True}]}
      }}

class CanaryGate(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        (self.root/'server').mkdir()
        self.cand=patch.object(m,'CAND',self.root);self.cand.start();self.addCleanup(self.cand.stop)
        self.orig=original()
        self.overlay,self.auth=m.fresh_override(self.orig)
        self.cfg=rendered(self.root,self.overlay)

    def denied(self, reason, doc=None):
        with self.assertRaisesRegex(RuntimeError,reason):m.validate_config(doc or self.cfg,self.orig)

    def test_valid_private_canary(self):
        m.validate_config(self.cfg,self.orig)
        self.assertNotEqual(self.cfg['services']['api']['environment']['JWT_SECRET'],'oldsigning')
        self.assertNotEqual(self.cfg['services']['api']['environment']['ADMIN_PASSWORD'],'oldadminpass')
        self.assertNotEqual(self.cfg['services']['db']['environment']['POSTGRES_PASSWORD'],'oldpassword')
        self.assertEqual(self.auth['admin_email'],'admin@fieldwork.local')

    def test_signing_secret_must_rotate(self):
        self.cfg['services']['api']['environment']['JWT_SECRET']='oldsigning'
        self.denied('AUTH_SECRET_REUSED')

    def test_admin_password_must_rotate(self):
        self.cfg['services']['api']['environment']['ADMIN_PASSWORD']='oldadminpass'
        self.denied('ADMIN_PASSWORD_REUSED')

    def test_source_config_without_secrets_must_stop(self):
        self.orig['services']['api']['environment'].pop('JWT_SECRET')
        with self.assertRaisesRegex(RuntimeError,'SIGNING_OR_BOOTSTRAP_SECRET'):
            m.fresh_override(self.orig)

    def test_different_postgres_user_password_rejected(self):
        self.cfg['services']['db']['environment']['POSTGRES_PASSWORD']='different'
        self.denied('API_DB_CREDENTIALS_NOT_PRIVATE_MATCHING')

    def test_shared_volume_rejected(self):
        self.cfg['volumes']['postgres_data']['name']='fieldwork-parity-m6-r9_postgres_data'
        self.denied('EXTERNAL_OR_SHARED_COMPOSE_RESOURCE')

    def test_host_bind_rejected(self):
        self.cfg['services']['api']['volumes'].append({'type':'bind','source':'/opt/fieldwork','target':'/data'})
        self.denied('BIND_MOUNT_NOT_ALLOWED')

    def test_wrong_public_port_rejected(self):
        self.cfg['services']['nginx']['ports'][0]['published']='18090'
        self.denied('NGINX_PORT_NOT_EXACT_18087')

    def test_privileged_container_rejected(self):
        self.cfg['services']['api']['privileged']=True
        self.denied('UNSAFE_HOST_OR_PRIVILEGED_SERVICE')

    def test_reused_baseline_build_image_rejected(self):
        self.cfg['services']['nginx']['image']='fieldwork-web:m6-r9'
        self.denied('BUILD_IMAGE_TAG_NOT_ISOLATED')

    def test_wrong_database_hostname_rejected(self):
        self.cfg['services']['api']['environment']['DATABASE_URL']=self.cfg['services']['api']['environment']['DATABASE_URL'].replace('@db:5432','@fieldwork-db:5432')
        self.denied('API_DB_CREDENTIALS_NOT_PRIVATE_MATCHING')

    def test_dev_admin_alias_rejected(self):
        self.cfg['services']['api']['environment']['FIELDWORK_DEV_ADMIN_ALIAS']='1'
        self.denied('DEV_ADMIN_ALIAS_UNSAFE')

    def test_no_external_database_port(self):
        self.cfg['services']['db']['ports']=[{'published':'5432','target':5432}]
        self.denied('UNEXPECTED_PUBLIC_SERVICE')

    def test_no_unintended_runner(self):
        self.cfg['services']['untrusted']={'privileged':True}
        self.denied('COMPOSE_UNEXPECTED_SERVICES')

if __name__=='__main__':main()
