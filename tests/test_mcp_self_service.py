"""M12 fail-closed, no-network unit tests for the self-service MCP gateway."""
import ast
import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from updater import mcp_self_diagnostics as diag
from updater import mcp_self_service_overlay as o


def synthetic_original():
    source = (
        "import artifact_retention_adapter\n"
        + "TOOLS = [\n" + o.TOOLS_OLD + "]\n"
        + "audit = " + repr(o.ANNOTATION_OLD) + "\n"
    )
    return source.encode()


class ToolRegistrationTests(unittest.TestCase):
    def test_exact_pinned_source_is_required(self):
        source = synthetic_original()
        with self.assertRaisesRegex(o.SelfServiceOverlayDenied, "MCP_SHA256_DRIFT"):
            o.transform_mcp(source)

    def test_synthetic_registry_ast_patch_adds_exact_three_tools(self):
        source = synthetic_original()
        with patch.object(o, "EXPECTED_MCP_SHA256",
                          hashlib.sha256(source).hexdigest()):
            candidate = o.transform_mcp(source)
        ast.parse(candidate)
        generated = candidate.decode()
        for n in o.NAMES:
            self.assertEqual(generated.count('("' + n + '",'), 1)
            self.assertIn(n, generated)
        self.assertEqual(generated.count("import mcp_self_diagnostics"), 1)
        self.assertEqual(generated.count(o.TOOLS_OLD), 1)
        self.assertIn(o.ANNOTATION_NEW, generated)

    def test_anchor_drift_is_deny_not_best_effort(self):
        source = synthetic_original().replace(
            b"import artifact_retention_adapter",
            b"import some_unknown_module")
        with patch.object(o, "EXPECTED_MCP_SHA256",
                          hashlib.sha256(source).hexdigest()):
            with self.assertRaisesRegex(
                    o.SelfServiceOverlayDenied, "MCP_ANCHOR_NOT_UNIQUE_OR_DRIFTED"):
                o.transform_mcp(source)

    def test_double_anchor_is_denied(self):
        source = synthetic_original() + o.TOOLS_OLD.encode()
        with patch.object(o, "EXPECTED_MCP_SHA256",
                          hashlib.sha256(source).hexdigest()):
            with self.assertRaises(o.SelfServiceOverlayDenied):
                o.transform_mcp(source)

    def test_bundle_requires_both_independent_sha_pins(self):
        source = synthetic_original()
        with self.assertRaises(o.SelfServiceOverlayDenied):
            o.build_mcp_and_cleanup(source, source)


class ReadOnlySourceTests(unittest.TestCase):
    def test_disallow_unknown_module(self):
        with self.assertRaisesRegex(diag.DiagnosticDenied,
                                    "SOURCE_NOT_ALLOWED"):
            diag._fixed_source("../../.env")

    def test_source_function_requires_exact_two_arguments(self):
        for args in ({}, {"module": "sandbox_command.py"},
                     {"module": "sandbox_command.py",
                      "function": "_run", "extra": True},
                     {"module": "sandbox_command.py",
                      "function": "../../.env"}):
            with self.subTest(args=args), self.assertRaises(
                    diag.DiagnosticDenied):
                diag.source_review(args)

    def test_ast_redacts_strings_passwords_and_literals(self):
        code = b'''def sample():\n    token = "SECRET_VALUE_987"\n    count = 900123\n    return token, count, "docker"\n'''
        with patch.object(diag, "_fixed_source", return_value=code):
            r = diag.source_review(
                {"module": "sandbox_command.py", "function": "sample"})
        self.assertEqual(r["status"], "READ_ONLY_SOURCE_AST")
        self.assertNotIn("SECRET_VALUE_987", json.dumps(r))
        self.assertNotIn("900123", json.dumps(r))
        self.assertIn("docker", r["redacted_ast"])
        self.assertFalse(r["source_executed"])
        self.assertFalse(r["mcp_modified"])

    def test_does_not_execute_function_source(self):
        code = b'''def thing():\n    raise RuntimeError("danger")\n'''
        with patch.object(diag, "_fixed_source", return_value=code):
            r = diag.source_review(
                {"module": "sandbox_command.py", "function": "thing"})
        self.assertEqual(r["status"], "READ_ONLY_SOURCE_AST")

    def test_not_found_denied(self):
        with patch.object(diag, "_fixed_source", return_value=b"pass\n"):
            with self.assertRaisesRegex(diag.DiagnosticDenied,
                                        "FUNCTION_NOT_UNIQUE_OR_MISSING"):
                diag.source_review(
                    {"module": "runtime_runner.py", "function": "_run"})


def docker_line(cid="f" * 64, name="fieldwork-test-one",
                state="exited", created="2026-10-31 13:00:00 +0100"):
    return json.dumps({"ID": cid, "Names": name, "State": state,
                       "CreatedAt": created,
                       "Labels": "password=DO_NOT_EXPOSE"}).encode() + b"\n"


class DockerReadOnlyTests(unittest.TestCase):
    def call(self, *, output=None, code=0, args=None):
        proc = subprocess.CompletedProcess(
            ["docker"], code, output if output is not None else
            docker_line(), b"SECRET_ERROR_SHOULD_BE_HIDDEN")
        with patch.object(diag.os, "geteuid", return_value=1000):
            with patch.object(diag.subprocess, "run", return_value=proc) as run:
                result = diag.docker_inventory(args if args is not None else {})
        self.assertEqual(run.call_count, 1)
        called = run.call_args.args[0]
        self.assertEqual(called, [diag.DOCKER,
                         "--host", "unix:///var/run/docker.sock",
                         "container", "ls", "--all", "--no-trunc",
                         "--format", "{{json .}}"])
        self.assertNotIn("rm", called)
        self.assertNotIn("stop", called)
        self.assertNotIn("DOCKER_HOST", run.call_args.kwargs["env"])
        self.assertFalse(result["container_removal_authorized"])
        return result

    def test_known_container_and_no_secret_labels(self):
        r = self.call()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["rows"][0]["name"], "fieldwork-test-one")
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(r))

    def test_other_container_name_redacted(self):
        r = self.call(output=docker_line(name="private_internal_service"))
        self.assertEqual(r["rows"][0]["name"], "<OTHER_CONTAINER>")

    def test_command_error_denied_and_suppressed(self):
        with self.assertRaisesRegex(diag.DiagnosticDenied,
                                    "DOCKER_QUERY_FAILED_OR_BOUNDS"):
            self.call(code=125)

    def test_bad_json_denied(self):
        with self.assertRaises(diag.DiagnosticDenied):
            self.call(output=b"{bad-json")

    def test_docker_query_disallows_user_arguments(self):
        with self.assertRaisesRegex(diag.DiagnosticDenied,
                                    "ARGS_SCHEMA_DENIED"):
            diag.docker_inventory({"command": "rm -f"})

    def test_root_denied(self):
        with patch.object(diag.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(diag.DiagnosticDenied, "ROOT_DENIED"):
                diag.docker_inventory({})

    def test_no_file_or_system_write_api_in_handlers(self):
        src = Path(diag.__file__).read_text()
        for forbidden in ("os.system(", "shutil.rmtree(", ".unlink(",
                          ".write_bytes(", ".write_text(", "shell=True",
                          "docker container rm"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
