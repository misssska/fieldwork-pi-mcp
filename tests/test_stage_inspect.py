"""Offline tests for fixed-project read-only staging inspection."""
import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault('stage_manager', types.ModuleType('stage_manager'))
from experimental import stage_inspect as mod


class InspectTests(unittest.TestCase):
    def test_empty_ps_is_not_running(self):
        self.assertEqual(mod.classify_ps(0, b'')['status'], 'STAGE_NO_CONTAINERS')
    def test_failed_ps_is_not_running(self):
        self.assertEqual(mod.classify_ps(1, b'')['status'], 'STAGE_PS_FAILED')
    def test_three_running_needs_health(self):
        raw=json.dumps([{'Service':s,'State':'running'} for s in ('api','db','nginx')]).encode()
        self.assertEqual(mod.classify_ps(0,raw)['status'],'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED')
    def test_ndjson(self):
        raw=b'\n'.join(json.dumps({'Service':s,'State':'running'}).encode() for s in ('api','db','nginx'))
        self.assertEqual(mod.classify_ps(0,raw)['status'],'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED')
    def test_missing_and_stopped(self):
        self.assertEqual(mod.classify_ps(0,b'{"Service":"db","State":"running"}')['status'],'STAGE_SERVICES_MISSING')
        self.assertEqual(mod.classify_ps(0,b'{"Service":"db","State":"exited"}')['status'],'STAGE_CONTAINERS_NOT_RUNNING')
    def test_invalid_and_unexpected_denied(self):
        for raw in (b'bad', b'null', b'\xff', b'[]'*40000, b'{"Service":"prod","State":"running"}', b'{"Service":"db","State":"running"}\n{"Service":"db","State":"running"}'):
            self.assertEqual(mod.classify_ps(0,raw)['status'],'STAGE_PS_INVALID')
    def test_no_raw_secret_output(self):
        raw=b'{"Service":"db","State":"running","Name":"password=secret"}'
        self.assertNotIn('secret',str(mod.classify_ps(0,raw)))
    def test_fixed_project_only_and_active_state(self):
        stage=sys.modules['stage_manager']
        with TemporaryDirectory() as d:
            root=Path(d)
            (root/'active.json').write_text(json.dumps({'proposal_id':'a'*32,'state':'STARTING'}))
            def compose(release,*args):
                self.assertEqual(args,('ps','-a','--format','json'))
                return ['docker','compose','-p','fieldwork-stage','--env-file','.env.stage','-f','docker-compose.stage.yml',*args]
            with patch.multiple(stage, STATE=root, STAGE_PROJECT='fieldwork-stage', PORT=18081,
                                _fail=lambda ok,code: None if ok else (_ for _ in ()).throw(ValueError(code)),
                                _owned_file=lambda path:path.read_bytes(),
                                _policy=lambda:{'bind_ip':'192.168.22.13'},
                                _active=lambda:(root,{'proposal_id':'a'*32}),
                                _compose=compose,create=True):
                with patch.object(mod.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')) as run:
                    result=mod.status({})
                    self.assertEqual(result['status'],'STAGE_NO_CONTAINERS')
                    self.assertEqual(result['active_state'],'STARTING')
                    self.assertFalse(result['production_modified'])
                    self.assertEqual(run.call_args.args[0][:4],['docker','compose','-p','fieldwork-stage'])
    def test_no_active_is_not_started(self):
        stage=sys.modules['stage_manager']
        with TemporaryDirectory() as d:
            with patch.multiple(stage, STATE=Path(d), STAGE_PROJECT='fieldwork-stage',
                                _fail=lambda ok,code: None if ok else (_ for _ in ()).throw(ValueError(code)),
                                _policy=lambda:{'bind_ip':'192.168.22.13'},create=True):
                self.assertEqual(mod.status({})['status'],'STAGE_NOT_STARTED')
