"""M11 negative-first tests for SHA-pinned offline cleanup code generation.

Synthetic installed-source fixtures ONLY. No host Docker/MCP installation.
"""
from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from updater import sandbox_cleanup_overlay as overlay


SOURCE = '''# RUNTIME_CLEANUP_FAILED is existing status in the original module
def run_command(r, test, cleanup, attempted=True):
    try:
        result = "original-path-remains"
    finally:
        if attempted:
            try:
                code, _ = r._run([r.DOCKER_BIN, 'rm', '-f', test], timeout=12)
                if code:
                    inspect, _ = r._run(
                        [r.DOCKER_BIN, 'container', 'inspect', test], timeout=8)
                    code = 0 if inspect else 1
                cleanup.append({'object': 'test_container', 'ok': code == 0})
            except ValueError:
                cleanup.append({'object': 'test_container', 'ok': False})
    return cleanup
'''


def candidate(source=SOURCE):
    data = source.encode("utf-8")
    # Explicit fixture-only pin override: production build has a fixed
    # real installed source SHA, not a caller-supplied override.
    with patch.object(overlay, "PINNED_ACTIVE_SANDBOX_SHA256",
                      hashlib.sha256(data).hexdigest()):
        return overlay.build(data)


class StubDocker:
    DOCKER_BIN = "/usr/bin/docker"

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def _run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        step = self.scripted.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_fn(script):
    result = candidate()["candidate_source"]
    scope = {}
    exec(compile(result, "fixture_candidate.py", "exec"), scope)
    docker = StubDocker(script)
    rec = scope["run_command"](docker, "safe-test-container", [])
    return rec, docker


class SourcePinAndASTGateTests(unittest.TestCase):
    def test_build_rejects_unpinned_fixture_and_leaves_source_unchanged(self):
        data = SOURCE.encode()
        with self.assertRaisesRegex(
                overlay.CleanupOverlayDenied, "PINNED_INSTALLED_SOURCE_MISMATCH"):
            overlay.build(data)
        self.assertIn(b"container', 'inspect'", data)

    def test_synthetic_target_replacement_does_not_modify_other_source(self):
        result = candidate()
        self.assertEqual(result["status"], "M11_CANDIDATE_ONLY")
        self.assertFalse(result["activation_authorized"])
        self.assertFalse(result["mcp_modified"])
        self.assertFalse(result["production_modified"])
        self.assertFalse(result["tunnel_modified"])
        patchtext = result["candidate_source"].decode()
        self.assertIn("original-path-remains", patchtext)
        self.assertIn("RUNTIME_CLEANUP_FAILED", patchtext)
        self.assertIn("r.DOCKER_BIN, 'container', 'ls'", patchtext)
        self.assertNotIn("r.DOCKER_BIN, 'container', 'inspect'", patchtext)
        self.assertIn("return cleanup", patchtext)

    def test_unexpected_source_bytes_are_rejected(self):
        for value in (None, "", "abc", {}, b"", b"x" * 131073):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(overlay.CleanupOverlayDenied):
                    overlay.build(value)

    def test_multiple_run_command_functions_rejected(self):
        with self.assertRaisesRegex(
                overlay.CleanupOverlayDenied, "RUN_COMMAND_NOT_UNIQUE"):
            candidate(SOURCE + "\n" + SOURCE)

    def test_missing_original_cleanup_branch_rejected(self):
        changed = SOURCE.replace(
            "r._run([r.DOCKER_BIN, 'rm', '-f', test], timeout=12)",
            "r._run([r.DOCKER_BIN, 'rm', 'other', test], timeout=12)")
        with self.assertRaisesRegex(
                overlay.CleanupOverlayDenied, "LEGACY_CLEANUP_ANCHOR_NOT_UNIQUE"):
            candidate(changed)

    def test_added_unreviewed_cleanup_action_rejected(self):
        changed = SOURCE.replace(
            "        if attempted:\n",
            "        if attempted:\n            print('extra side effect')\n")
        with self.assertRaisesRegex(
                overlay.CleanupOverlayDenied, "LEGACY_CLEANUP_SHAPE_DRIFT"):
            candidate(changed)

    def test_extra_status_append_is_rejected(self):
        changed = SOURCE.replace(
            "                cleanup.append({'object': 'test_container', 'ok': code == 0})",
            "                cleanup.append({'object': 'test_container', 'ok': code == 0})\n"
            "                cleanup.append({'object': 'other', 'ok': True})")
        with self.assertRaisesRegex(
                overlay.CleanupOverlayDenied, "LEGACY_CLEANUP_APPEND_DRIFT"):
            candidate(changed)

    def test_missing_valueerror_catch_rejected(self):
        changed = SOURCE.replace("except ValueError:", "except OSError:")
        with self.assertRaisesRegex(
                overlay.CleanupOverlayDenied, "LEGACY_CLEANUP_HANDLER_DRIFT"):
            candidate(changed)


class GeneratedRuntimeSemanticsTests(unittest.TestCase):
    def assert_check_argv(self, docker):
        self.assertEqual(len(docker.calls), 3)
        self.assertEqual(
            docker.calls[0],
            (["/usr/bin/docker", "rm", "-f", "safe-test-container"],
             {"timeout": 12}))
        for argv, kwargs in docker.calls[1:]:
            self.assertEqual(argv, [
                "/usr/bin/docker", "container", "ls", "--all",
                "--filter", "name=^/safe-test-container$",
                "--format", "{{.ID}}"
            ])
            self.assertEqual(kwargs, {"timeout": 8, "output_limit": 1024})

    def test_successful_remove_two_verified_absences(self):
        receipt, docker = test_fn([(0, ""), (0, ""), (0, "")])
        self.assertEqual(receipt, [{"object": "test_container", "ok": True}])
        self.assert_check_argv(docker)

    def test_remove_failure_but_absence_verified_autoremove_race(self):
        receipt, docker = test_fn([(1, "nonzero"), (0, ""), (0, "")])
        self.assertTrue(receipt[0]["ok"])
        self.assert_check_argv(docker)

    def test_remove_timeout_but_absence_verified(self):
        receipt, docker = test_fn([
            ValueError("DOCKER_TIMEOUT"), (0, ""), (0, "")
        ])
        self.assertTrue(receipt[0]["ok"])
        self.assert_check_argv(docker)

    def test_remove_success_but_container_present_fails_closed(self):
        receipt, docker = test_fn([(0, ""), (0, "abc123\n")])
        self.assertFalse(receipt[0]["ok"])
        self.assertEqual(len(docker.calls), 2)

    def test_remove_failed_and_container_present_fails_closed(self):
        receipt, docker = test_fn([(1, "error"), (0, "deadbeef\n")])
        self.assertFalse(receipt[0]["ok"])
        self.assertEqual(len(docker.calls), 2)

    def test_readback_nonzero_not_evidence_of_absence(self):
        receipt, docker = test_fn([(0, ""), (5, "")])
        self.assertFalse(receipt[0]["ok"])
        self.assertEqual(len(docker.calls), 2)

    def test_first_absent_second_query_failure_fails_closed(self):
        receipt, docker = test_fn([
            (0, ""), (0, ""), (1, "Docker daemon unavailable")
        ])
        self.assertFalse(receipt[0]["ok"])
        self.assert_check_argv(docker)

    def test_first_absent_second_query_timeout_fails_closed(self):
        receipt, docker = test_fn([
            (0, ""), (0, ""), ValueError("DOCKER_TIMEOUT")
        ])
        self.assertFalse(receipt[0]["ok"])
        self.assert_check_argv(docker)

    def test_first_probe_timeout_fails_closed(self):
        receipt, docker = test_fn([
            (0, ""), ValueError("DOCKER_TIMEOUT")
        ])
        self.assertFalse(receipt[0]["ok"])
        self.assertEqual(len(docker.calls), 2)

    def test_any_nonempty_redacted_content_does_not_claim_absence(self):
        receipt, docker = test_fn([(0, ""), (0, "[REDACTED]\n")])
        self.assertFalse(receipt[0]["ok"])
        self.assertEqual(len(docker.calls), 2)

    def test_does_not_attempt_cleanup_when_no_test_started(self):
        # Explicitly call a separate fixture with attempted=False.
        scope = {}
        exec(compile(candidate()["candidate_source"],
                     "fixture_candidate.py", "exec"), scope)
        other = StubDocker([])
        result = scope["run_command"](
            other, "safe-test-container", [], attempted=False)
        self.assertEqual(result, [])
        self.assertEqual(other.calls, [])


if __name__ == "__main__":
    unittest.main()
