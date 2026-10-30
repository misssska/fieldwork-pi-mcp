import json
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault('stage_manager', types.ModuleType('stage_manager'))
from experimental.stage_inspect import classify_ps

class StageInspectTests(unittest.TestCase):
    def test_no_containers(self):
        self.assertEqual(classify_ps(0,b'')['status'], 'STAGE_NO_CONTAINERS')
    def test_ps_failure(self):
        self.assertEqual(classify_ps(1,b'')['status'], 'STAGE_PS_FAILED')
    def test_valid_running_but_not_health(self):
        data=[{'Service':s,'State':'running'} for s in ('api','db','nginx')]
        self.assertEqual(classify_ps(0,json.dumps(data).encode())['status'], 'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED')
    def test_ndjson(self):
        raw=b'\n'.join(json.dumps({'Service':s,'State':'running'}).encode() for s in ('api','db','nginx'))
        self.assertEqual(classify_ps(0,raw)['status'], 'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED')
    def test_missing(self):
        self.assertEqual(classify_ps(0,b'{"Service":"db","State":"running"}')['status'], 'STAGE_SERVICES_MISSING')
    def test_stopped(self):
        self.assertEqual(classify_ps(0,b'{"Service":"db","State":"exited"}')['status'], 'STAGE_CONTAINERS_NOT_RUNNING')
    def test_unknown(self):
        self.assertEqual(classify_ps(0,b'{"Service":"prod","State":"running"}')['status'], 'STAGE_PS_INVALID')
    def test_duplicate(self):
        self.assertEqual(classify_ps(0,b'{"Service":"db","State":"running"}\n{"Service":"db","State":"running"}')['status'], 'STAGE_PS_INVALID')
    def test_invalid(self):
        for raw in (b'bad', b'null', b'[]garbage', b'[]'*40000, b'\xff'):
            self.assertEqual(classify_ps(0,raw)['status'], 'STAGE_PS_INVALID')
    def test_redact(self):
        raw=b'{"Service":"db","State":"running","Name":"password=secret"}'
        self.assertNotIn('secret',str(classify_ps(0,raw)))

class StageInspectIntegrationTests(unittest.TestCase):
    def test_fixed_scope_ps_only_and_empty_output(self):
        from experimental import stage_inspect as module
        from pathlib import Path
        from types import SimpleNamespace
        import tempfile
        stage = sys.modules['stage_manager']
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'active.json').write_text(json.dumps({'state':'STARTING','proposal_id':'a'*32}))
            def compose(release, *args):
                self.assertEqual(args, ('ps', '-a', '--format', 'json'))
                return ['docker','compose','-p','fieldwork-stage','--env-file','.env.stage','-f','docker-compose.stage.yml',*args]
            with patch.multiple(stage, STATE=root, STAGE_PROJECT='fieldwork-stage', PORT=18081,
                                _policy=lambda: {'bind_ip':'192.168.22.13'},
                                _active=lambda: (root,{'proposal_id':'a'*32}),
                                _compose=compose, create=True):
                with patch.object(stage,'_owned_file',lambda path: path.read_bytes(), create=True):
                    with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')) as run:
                        result=module.status({})
                        self.assertEqual(result['status'],'STAGE_NO_CONTAINERS')
                        self.assertEqual(result['active_state'],'STARTING')
                        self.assertFalse(result['production_modified'])
                        self.assertEqual(run.call_args.args[0][0:4], ['docker','compose','-p','fieldwork-stage'])
                        self.assertNotIn('secret',str(result))

    def test_no_active_means_not_started(self):
        from experimental import stage_inspect as module
        from pathlib import Path
        import tempfile
        stage=sys.modules['stage_manager']
        with tempfile.TemporaryDirectory() as d:
            with patch.multiple(stage, STATE=Path(d), STAGE_PROJECT='fieldwork-stage',
                                _policy=lambda: {'bind_ip':'192.168.22.13'}, create=True):
                self.assertEqual(module.status({})['status'],'STAGE_NOT_STARTED')

if __name__=='__main__': unittest.main()
