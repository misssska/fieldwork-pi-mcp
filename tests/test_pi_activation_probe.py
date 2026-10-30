"""Offline tests for local, read-only MCP source preflight."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from updater import pi_activation_probe as p

SOURCE = b"import stage_manager\nVALUE = 1\n"


class PiActivationProbeTests(unittest.TestCase):
    def setUp(self):
        if p.os.geteuid() == 0:
            self.skipTest("Root must not run MCP activation probe tests")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.path = self.home / p.MCP_REL
        self.path.mkdir(parents=True)
        self.main = self.path / p.MAIN
        self.main.write_bytes(SOURCE)
        self.pin = hashlib.sha256(SOURCE).hexdigest()

    def test_exact_source_identified_without_writes(self):
        before = self.main.read_bytes()
        result = p.inspect(self.home, self.pin)
        self.assertEqual(result['status'], 'SOURCE_PREFLIGHT_MATCH')
        self.assertEqual(result['source_sha256'], self.pin)
        self.assertTrue(result['source_qualification_possible'])
        self.assertEqual(before, self.main.read_bytes())
        for name in ('activation_authorized', 'mcp_modified',
                     'production_modified', 'tunnel_restarted'):
            self.assertFalse(result[name])

    def test_changed_source_does_not_accept_stale_pin(self):
        self.main.write_bytes(SOURCE + b"DIFFERENT = True\n")
        result = p.inspect(self.home, self.pin)
        self.assertEqual(result['status'], 'SOURCE_PREFLIGHT_REVIEW_REQUIRED')
        self.assertFalse(result['source_matches_reviewed_pin'])
        self.assertFalse(result['source_qualification_possible'])

    def test_existing_extension_blocks_activation(self):
        (self.path / 'artifact_inbox.py').write_text('pass\n')
        result = p.inspect(self.home, self.pin)
        self.assertEqual(result['module_states']['artifact_inbox.py'], 'PRESENT')
        self.assertFalse(result['source_qualification_possible'])

    def test_existing_symlink_extension_blocks_activation(self):
        (self.path / 'artifact_inbox.py').symlink_to(self.main)
        result = p.inspect(self.home, self.pin)
        self.assertEqual(result['module_states']['artifact_inbox.py'], 'SYMLINK_UNSAFE')
        self.assertFalse(result['source_qualification_possible'])

    def test_source_symlink_denied(self):
        self.main.unlink()
        other = self.home / "other.py"
        other.write_bytes(SOURCE)
        self.main.symlink_to(other)
        with self.assertRaisesRegex(p.PreflightDenied, 'MCP_MAIN_MISSING_OR_SYMLINK'):
            p.inspect(self.home, self.pin)

    def test_directory_symlink_denied(self):
        local = self.home / '.local'
        # Replace only after cleaning the directory.
        with tempfile.TemporaryDirectory() as other:
            import shutil
            shutil.rmtree(local)
            local.symlink_to(Path(other), target_is_directory=True)
            with self.assertRaisesRegex(p.PreflightDenied, 'DIRECTORY_MISSING_OR_SYMLINK'):
                p.inspect(self.home, self.pin)

    def test_invalid_python_source_denied(self):
        self.main.write_bytes(b'def broken(:\n')
        with self.assertRaisesRegex(p.PreflightDenied, 'MCP_MAIN_PYTHON_INVALID'):
            p.inspect(self.home, self.pin)

    def test_untrusted_pin_denied(self):
        with self.assertRaisesRegex(p.PreflightDenied, 'SOURCE_PIN_REQUIRED'):
            p.inspect(self.home, 'not-a-sha256')

    def test_oversized_main_denied(self):
        with self.main.open('wb') as handle:
            handle.truncate(p.MAX_SOURCE + 1)
        with self.assertRaisesRegex(p.PreflightDenied, 'MCP_MAIN_SIZE_DENIED'):
            p.inspect(self.home, self.pin)

    def test_no_service_commands_except_read_state(self):
        from subprocess import CompletedProcess
        with patch.object(p.subprocess, 'run',
                          return_value=CompletedProcess([], 0, stdout='active\n')) as mocked:
            self.assertEqual(p.tunnel_active(), 'ACTIVE')
            args = mocked.call_args.args[0]
            self.assertEqual(args, ['systemctl', 'is-active', 'fieldwork-pi-tunnel.service'])
        with patch.object(p.subprocess, 'run', side_effect=OSError):
            self.assertEqual(p.tunnel_active(), 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
