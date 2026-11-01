"""Static-negative and mocked lifecycle tests: never execute Docker on the test runner."""
import json
import subprocess
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from updater import activate_r8_stable_dev_gateway as g


class GatewayFirstActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'stage-v06' / 'parity-m5.Krm2sA3i'
        self.base.mkdir(parents=True)
        self.state = Path(self.temp.name) / 'gateway'
        p = patch.object(g, 'BASE', self.base)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(g, 'STATE', self.state)
        p.start()
        self.addCleanup(p.stop)
        pins = {}
        for i in range(3):
            name = f'file{i}.txt'
            data = f'example{i}'.encode()
            pins[name] = sha256(data).hexdigest()
            (self.base / name).write_bytes(data)
        p = patch.object(g, 'SOURCE_PINS', pins)
        p.start()
        self.addCleanup(p.stop)
        for name in ('m5-frontend-test.log', 'm5-backend-test.log'):
            (self.base / name).write_text('fixture', encoding='utf-8')

    def test_exact_file_drift_denied(self):
        g.check_sources()
        (self.base / 'file0.txt').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'R8_SOURCE_DRIFT'):
            g.check_sources()

    def test_existing_gateway_rejected(self):
        self.state.mkdir()
        (self.state / 'default.conf').write_text('existing', encoding='utf-8')
        with patch.object(g, 'docker_info', return_value='sha256:'+'c'*64), \
             patch.object(g, 'health', return_value=True), \
             patch.object(g, 'can_bind'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'missing')):
            with self.assertRaisesRegex(RuntimeError, 'GATEWAY_STATE_ALREADY_EXISTS'):
                g.precheck()

    def test_precheck_only(self):
        with patch.object(g, 'docker_info', return_value='sha256:'+'c'*64), \
             patch.object(g, 'health', return_value=True), \
             patch.object(g, 'can_bind'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'missing')):
            self.assertEqual(g.precheck(), 'sha256:'+'c'*64)
        self.assertFalse(self.state.exists())

    def test_start_is_limited_to_new_gateway(self):
        original = [(p, (self.base/p).read_bytes()) for p in g.SOURCE_PINS]
        with patch.object(g, 'invoke', return_value='a'*64) as invoke, \
             patch.object(g, 'health', return_value=True):
            g.activate('sha256:'+'c'*64)
        cmd = invoke.call_args.args
        self.assertIn('192.168.22.13:18090:8080', cmd)
        self.assertIn('--read-only', cmd)
        self.assertIn('--cap-drop', cmd)
        self.assertIn('no-new-privileges', cmd)
        self.assertNotIn('--privileged', cmd)
        receipt = json.loads((self.state / 'release.json').read_text())
        self.assertEqual(receipt['status'], 'FIRST_ACTIVATION_HEALTH_PASS')
        self.assertFalse(receipt['auth_identity_verified'])
        self.assertFalse(receipt['future_release_promotion_authorized'])
        self.assertEqual(original, [(p, (self.base/p).read_bytes()) for p in g.SOURCE_PINS])

    def test_probe_failure_removes_only_new_id(self):
        with patch.object(g, 'invoke', return_value='b'*64), \
             patch.object(g, 'health', return_value=False), \
             patch.object(g.time, 'sleep'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            with self.assertRaisesRegex(RuntimeError, '18090_GATEWAY_HEALTH_FAILED'):
                g.activate('sha256:'+'c'*64)
        run.assert_called_once_with(['docker','rm','-f','b'*64],
                                    capture_output=True,text=True,timeout=20)
        self.assertFalse((self.state / 'release.json').exists())


if __name__ == '__main__':
    unittest.main()
