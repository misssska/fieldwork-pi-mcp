import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

stage = sys.modules.setdefault('stage_manager', types.ModuleType('stage_manager'))
stage.RELEASE_ID = re.compile(r'[a-f0-9]{32}')
stage._fail = lambda ok, code: None if ok else (_ for _ in ()).throw(ValueError(code))
stage._policy = lambda: {'enabled':True}
stage._owned_file = lambda path: path.read_bytes()
async_base = sys.modules.setdefault('stage_async', types.ModuleType('stage_async'))
async_base.RUNNING = frozenset({'QUEUED','RUNNING'})
async_base._read = lambda path: json.loads(path.read_text()) if path.exists() else None
async_base._live = lambda record: False
from experimental import stage_start_async as mod

ID = 'a'*32

class StartAsyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        stage.STATE = self.root
        release = self.root/'releases'/ID
        release.mkdir(parents=True)
        (release/'full-test.json').write_text(json.dumps({'status':'FULL_TEST_PASS'}))
        stage._validated_release = lambda proposal: (release, {})

    def test_args_fail_closed(self):
        for args in ({}, {'proposal_id':'bad'}, {'proposal_id':ID,'command':'rm'}, []):
            with self.assertRaises(ValueError): mod._validated_id(args)

    def test_no_receipt(self):
        self.assertEqual(mod.status({'proposal_id':ID})['status'],'STAGE_START_NOT_REQUESTED')

    def test_previous_interrupted_start_requires_recovery(self):
        (self.root/'active.json').write_text(json.dumps({'proposal_id':ID,'state':'STARTING'}))
        self.assertEqual(mod._active_state(),(ID,'STARTING'))

    def test_running_state(self):
        (self.root/'active.json').write_text(json.dumps({'proposal_id':ID,'state':'RUNNING'}))
        self.assertEqual(mod._active_state(),(ID,'RUNNING'))

    def test_corrupt_active_denied(self):
        (self.root/'active.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'STAGE_ACTIVE_STATE_INVALID'): mod._active_state()

    def test_lost_worker_not_success(self):
        (self.root/'async-start.json').write_text(json.dumps({'status':'RUNNING','proposal_id':ID,'job_id':'b'*32,'created_at_utc':0}))
        self.assertEqual(mod.status({'proposal_id':ID})['status'],'STAGE_START_WORKER_LOST')

    def test_receipt_wrong_proposal_denied(self):
        (self.root/'async-start.json').write_text(json.dumps({'status':'START_COMMAND_PASS','proposal_id':'b'*32,'job_id':'c'*32}))
        with self.assertRaisesRegex(ValueError,'STAGE_START_RECEIPT_INVALID'): mod.status({'proposal_id':ID})

    def test_command_pass_does_not_claim_health(self):
        (self.root/'async-start.json').write_text(json.dumps({'status':'START_COMMAND_PASS','proposal_id':ID,'job_id':'b'*32}))
        self.assertEqual(mod.status({'proposal_id':ID})['status'],'START_COMMAND_PASS')

    def test_recovery_does_not_spawn_worker(self):
        (self.root/'active.json').write_text(json.dumps({'proposal_id':ID,'state':'STARTING'}))
        with patch.object(async_base,'_locked',side_effect=lambda **kw: os.open(os.devnull,os.O_RDONLY), create=True):
            with patch.object(mod.subprocess,'Popen') as spawn:
                result=mod.request({'proposal_id':ID})
                self.assertEqual(result['status'],'STAGE_START_RECOVERY_REQUIRED')
                spawn.assert_not_called()

    def test_previous_receipt_blocks_repeat(self):
        (self.root/'async-start.json').write_text(json.dumps({'status':'START_COMMAND_ERROR','proposal_id':ID,'job_id':'b'*32}))
        with patch.object(async_base,'_locked',side_effect=lambda **kw: os.open(os.devnull,os.O_RDONLY), create=True):
            with patch.object(mod.subprocess,'Popen') as spawn:
                result=mod.request({'proposal_id':ID})
                self.assertEqual(result['status'],'STAGE_START_PREVIOUS_ATTEMPT')
                spawn.assert_not_called()

    def test_other_proposal_receipt_denied(self):
        (self.root/'async-start.json').write_text(json.dumps({'status':'QUEUED','proposal_id':'b'*32,'job_id':'c'*32}))
        with patch.object(async_base,'_locked',side_effect=lambda **kw: os.open(os.devnull,os.O_RDONLY), create=True):
            with self.assertRaisesRegex(ValueError,'STAGE_START_OTHER_PROPOSAL_RECEIPT'):
                mod.request({'proposal_id':ID})

    def test_stage_test_pending_blocks_start(self):
        (self.root/'releases'/ID/'async-test.json').write_text(json.dumps({'status':'QUEUED'}))
        with patch.object(async_base,'_locked',side_effect=lambda **kw: os.open(os.devnull,os.O_RDONLY), create=True):
            with patch.object(mod.subprocess,'Popen') as spawn:
                result=mod.request({'proposal_id':ID})
                self.assertEqual(result['status'],'STAGE_TEST_NOT_FINISHED')
                spawn.assert_not_called()

    def test_full_test_required(self):
        (self.root/'releases'/ID/'full-test.json').write_text('{"status":"FULL_TEST_FAIL"}')
        with self.assertRaisesRegex(ValueError,'STAGE_FULL_TEST_REQUIRED'): mod.request({'proposal_id':ID})

if __name__=='__main__': unittest.main()
