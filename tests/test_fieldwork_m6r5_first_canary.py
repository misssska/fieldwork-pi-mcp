"""Isolated synthetic safety tests for the M6 canary first launch; NO Docker required."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SRC=Path(__file__).with_name('launch_m6_canary.py')
spec=importlib.util.spec_from_file_location('m6r5',SRC)
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def config():
    return {
      'name':g.PROJECT,
      'networks':{'default':{'name':g.PROJECT+'_default'}},
      'volumes':{'db-data':{'name':g.PROJECT+'_db-data'}},
      'services':{
        'db':{'environment':{'POSTGRES_DB':'fieldwork'},'volumes':[{'type':'volume','source':'db-data','target':'/var/lib/postgresql/data'}],'networks':{'default':None}},
        'api':{'environment':{'DATABASE_URL':'postgresql+psycopg://fw:fake@db:5432/fieldwork'},'build':{'context':'/tmp/fake-candidate/server'},'networks':{'default':None}},
        'nginx':{'ports':[{'host_ip':g.HOST,'published':str(g.PORT),'target':80}],'build':{'context':'/tmp/fake-candidate/frontend'},'networks':{'default':None}}
      }
    }


class Safety(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.cand=self.base/'fake-candidate'
        for folder in ('server','frontend'):
            (self.cand/folder).mkdir(parents=True,exist_ok=True)
        p=patch.object(g,'CAND',self.cand)
        p.start();self.addCleanup(p.stop)
        self.good=config()
        self.good['services']['api']['build']['context']=str(self.cand/'server')
        self.good['services']['nginx']['build']['context']=str(self.cand/'frontend')

    def test_private_compose_good(self):
        g.check_compose_config(self.good)

    def test_production_database_denied(self):
        self.good['services']['api']['environment']['DATABASE_URL']='postgresql://user:test@production-db:5432/fieldwork'
        with self.assertRaisesRegex(RuntimeError,'DATABASE_NOT_PRIVATE'):g.check_compose_config(self.good)

    def test_external_volume_denied(self):
        self.good['volumes']['db-data']['external']=True
        with self.assertRaisesRegex(RuntimeError,'COMPOSE_EXTERNAL_RESOURCE'):g.check_compose_config(self.good)

    def test_global_named_volume_denied(self):
        self.good['volumes']['db-data']['name']='fieldwork-production-data'
        with self.assertRaisesRegex(RuntimeError,'COMPOSE_RESOURCE_NAME_NOT_SCOPED'):g.check_compose_config(self.good)

    def test_external_network_denied(self):
        self.good['networks']['default']['external']=True
        with self.assertRaisesRegex(RuntimeError,'COMPOSE_EXTERNAL_RESOURCE'):g.check_compose_config(self.good)

    def test_unwanted_host_port_denied(self):
        self.good['services']['nginx']['ports'][0]['published']='18090'
        with self.assertRaisesRegex(RuntimeError,'NGINX_BIND_NOT_EXACT_LAN_18086'):g.check_compose_config(self.good)

    def test_unwanted_public_db_port_denied(self):
        self.good['services']['db']['ports']=[{'published':'5432'}]
        with self.assertRaisesRegex(RuntimeError,'COMPOSE_UNEXPECTED_PUBLIC_PORT'):g.check_compose_config(self.good)

    def test_bind_mount_denied(self):
        self.good['services']['api']['volumes']=[{'type':'bind','source':'/opt/fieldwork','target':'/app'}]
        with self.assertRaisesRegex(RuntimeError,'COMPOSE_BIND_MOUNT_DENIED'):g.check_compose_config(self.good)

    def test_build_context_outside_denied(self):
        self.good['services']['api']['build']['context']=str(self.base)
        with self.assertRaisesRegex(RuntimeError,'BUILD_CONTEXT_OUTSIDE_M6'):g.check_compose_config(self.good)

    def test_dev_admin_alias_disabled(self):
        self.good['services']['api']['environment']['FIELDWORK_DEV_ADMIN_ALIAS']='1'
        with self.assertRaisesRegex(RuntimeError,'UNVERIFIED_ADMIN_ALIAS_MUST_REMAIN_OFF'):g.check_compose_config(self.good)

    def test_project_identity_denied(self):
        self.good['name']='fieldwork'
        with self.assertRaisesRegex(RuntimeError,'COMPOSE_PROJECT_DRIFT'):g.check_compose_config(self.good)

    def test_only_first_launch_when_project_exists(self):
        mock=subprocess.CompletedProcess(args=[],returncode=0,stdout='container1\n',stderr='')
        with patch.object(g,'run',return_value=mock):
            with self.assertRaisesRegex(RuntimeError,'M6_PROJECT_NOT_EMPTY'):g.ensure_absent()

    def test_first_launch_denies_existing_release_file(self):
        (self.cand/'m6-r5-canary-release.json').write_text('{}')
        mock=subprocess.CompletedProcess(args=[],returncode=0,stdout='',stderr='')
        with patch.object(g,'run',return_value=mock):
            with self.assertRaisesRegex(RuntimeError,'M6_R5_LAUNCH_ALREADY_ATTEMPTED'):g.ensure_absent()

    def test_script_has_no_18090_target(self):
        s=SRC.read_text(encoding='utf-8')
        self.assertNotIn('docker stop',s)
        self.assertNotIn('docker rm',s)
        self.assertNotIn('subprocess.Popen',s)
        self.assertIn("PORT = 18086",s)


if __name__=='__main__':
    unittest.main()
