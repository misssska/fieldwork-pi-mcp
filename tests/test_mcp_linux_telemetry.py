"""M13 read-only Linux MCP telemetry and source overlay, negative-first."""
import ast
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from updater import mcp_linux_telemetry as metrics
from updater import mcp_linux_telemetry_overlay as overlay

# mcp_linux_telemetry is imported in the updater and is expected to be
# co-located with linux_telemetry.py in the actual MCP installation.
from updater import linux_telemetry as core

MEM = ("MemTotal: 1024000 kB\nMemAvailable: 400000 kB\n"
       "SwapTotal: 200000 kB\nSwapFree: 150000 kB\n")
CPU0 = "cpu 100 0 100 700 50 10 20 20 0 0\n"
CPU1 = "cpu 150 0 150 750 50 10 20 20 0 0\n"
LOAD = "0.47 0.65 0.12 1/200 321\n"

OLD_MAIN = ("import mcp_self_diagnostics\n"
            + "TOOLS = [\n" + overlay.OLD_TOOL + "]\n")


class M13OverlayTests(unittest.TestCase):
    def build_fixture(self, data=OLD_MAIN):
        with patch.object(overlay, "EXPECTED_MAIN_SHA256",
                          hashlib.sha256(data.encode()).hexdigest()):
            return overlay.build(data.encode())

    def test_requires_real_installed_m12_main_sha(self):
        with self.assertRaisesRegex(
                overlay.M13OverlayDenied, "M13_INSTALLED_M12_SHA256_MISMATCH"):
            overlay.build(OLD_MAIN.encode())

    def test_only_adds_two_readonly_registrations(self):
        r = self.build_fixture()
        self.assertEqual(r["status"], "M13_OFFLINE_CANDIDATE_ONLY")
        self.assertEqual(set(r["new_tools"]), set(overlay.ADDED))
        self.assertFalse(r["activation_authorized"])
        self.assertFalse(r["mcp_modified"])
        source = r["candidate_bytes"].decode()
        self.assertEqual(source.count("import mcp_linux_telemetry"), 1)
        self.assertEqual(source.count(overlay.OLD_TOOL), 1)
        self.assertEqual(source.count('("fieldwork_mcp_host_metrics",'), 1)
        self.assertEqual(source.count('("fieldwork_mcp_container_stats",'), 1)
        self.assertTrue(source.startswith("import mcp_self_diagnostics\n"))
        ast.parse(source)

    def test_actual_m12_generated_tool_anchor_and_mutating_safety_list(self):
        # Use the literal exact M12 generated registration bytes, rather than
        # a smaller hand-written approximation.
        from updater import mcp_self_service_overlay as m12
        src = ("import artifact_retention_adapter\n"
               "import mcp_self_diagnostics\n"
               "TOOLS = [\n" + m12.TOOLS_NEW + "]\n"
               "MUTATING_NAMES = (" + m12.ANNOTATION_NEW + ")\n")
        with patch.object(overlay, "EXPECTED_MAIN_SHA256",
                          hashlib.sha256(src.encode()).hexdigest()):
            candidate = overlay.build(src.encode())["candidate_bytes"].decode()
        self.assertEqual(candidate.count('("fieldwork_mcp_host_metrics",'), 1)
        self.assertEqual(candidate.count('("fieldwork_mcp_container_stats",'), 1)
        self.assertEqual(candidate.count('("fieldwork_mcp_docker_inventory",'), 1)
        mutating = candidate.split("MUTATING_NAMES = (")[1].split(")")[0]
        self.assertNotIn("fieldwork_mcp_host_metrics", mutating)
        self.assertNotIn("fieldwork_mcp_container_stats", mutating)
        self.assertIn("fieldwork_stage_start", mutating)

    def test_source_anchor_missing_or_duplicate_denied(self):
        for source in (
            OLD_MAIN.replace("import mcp_self_diagnostics", "import other"),
            OLD_MAIN.replace("]\n", overlay.OLD_TOOL + "]\n"),
            OLD_MAIN.replace(overlay.OLD_TOOL, ""),
        ):
            with self.subTest(sha=hashlib.sha256(source.encode()).hexdigest()):
                with self.assertRaisesRegex(overlay.M13OverlayDenied,
                                            "M13_SOURCE_ANCHOR_DRIFT"):
                    self.build_fixture(source)

    def test_tool_collision_denied(self):
        with self.assertRaisesRegex(overlay.M13OverlayDenied,
                                    "M13_TOOLS_ALREADY_PRESENT"):
            self.build_fixture(OLD_MAIN + "t='fieldwork_mcp_host_metrics'\n")

    def test_does_not_introduce_host_shell(self):
        import inspect
        src = inspect.getsource(overlay)
        self.assertNotIn("import subprocess", src)
        self.assertNotIn("os.system(", src)


class M13HostMetricsTests(unittest.TestCase):
    def test_host_collects_two_snapshots_one_bounded_interval(self):
        snaps = [core.parse_proc_snapshot(MEM, CPU0, LOAD),
                 core.parse_proc_snapshot(MEM, CPU1, LOAD)]
        with patch.object(metrics.os, "geteuid", return_value=1000), patch.object(
                metrics.core, "collect_proc_snapshot", side_effect=snaps) as collect, patch.object(
                metrics.time, "sleep") as sleeping, patch.object(
                metrics.time, "monotonic", side_effect=[2, 2.41]):
            r = metrics.host_metrics({})
        self.assertEqual(r["status"], "READ_ONLY_LINUX_HOST_METRICS")
        self.assertEqual(r["cpu_busy_pct"], 66.67)
        self.assertEqual(r["memory"]["used_estimate_kib"], 624000)
        self.assertFalse(r["write_performed"])
        collect.assert_called()
        self.assertEqual(collect.call_count, 2)
        sleeping.assert_called_once_with(metrics.CPU_SAMPLING_SECONDS)

    def test_missing_or_extra_args_denied(self):
        for v in (None, "{}", {"shell": "hostname"}, {"container": "db"}, []):
            with self.subTest(v=v), self.assertRaisesRegex(
                    metrics.MetricsDenied, "ARGS_SCHEMA_DENIED"):
                metrics.host_metrics(v)

    def test_nonroot_required(self):
        with patch.object(metrics.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(metrics.MetricsDenied, "ROOT_DENIED"):
                metrics.host_metrics({})

    def test_faulty_proc_snapshot_returns_safe_error(self):
        with patch.object(metrics.os, "geteuid", return_value=1000), patch.object(
                metrics.core, "collect_proc_snapshot",
                side_effect=core.TelemetryDenied("private information")):
            with self.assertRaisesRegex(metrics.MetricsDenied,
                                        "PROC_TELEMETRY_DENIED"):
                metrics.host_metrics({})


def docker_row(name="fieldwork-api-1", cid="a" * 12,
               cpu="12.34%", memory="14.5MiB / 1GiB"):
    return json.dumps({"ID": cid, "Name": name, "CPUPerc": cpu,
                       "MemUsage": memory,
                       "NetIO": "secret", "PIDs": "12",
                       "Mounts": "/private/key"}).encode() + b"\n"


class M13DockerStatsTests(unittest.TestCase):
    def test_parses_sanitizes_and_sorts_realistic_docker_rows(self):
        data = (docker_row(cid="a" * 12, cpu="15.4%") +
                docker_row(cid="b" * 12, name="private_container", cpu="200.1%",
                           memory="999kB / 2GB"))
        rows = metrics.parse_docker_stats(data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "<OTHER_CONTAINER>")
        self.assertEqual(rows[0]["memory_used_bytes"], 999000)
        self.assertEqual(rows[1]["name"], "fieldwork-api-1")
        self.assertEqual(rows[1]["memory_used_bytes"], round(14.5*1024*1024))
        self.assertNotIn("NetIO", str(rows))
        self.assertNotIn("private/key", str(rows))

    def test_accepts_docker_integer_bytes_and_percent_over_one_core(self):
        rows = metrics.parse_docker_stats(
            docker_row(cpu="123.1%", memory="0B / 512MiB"))
        self.assertEqual(rows[0]["cpu_percent_of_one_core"], 123.1)
        self.assertEqual(rows[0]["memory_used_bytes"], 0)

    def test_rejects_duplicate_id_invalid_json_and_overlong(self):
        for raw in (
            docker_row() + docker_row(),
            b"NOT_JSON\n",
            docker_row(cpu="NaN%"),
            docker_row(cpu="50000000%"),
            docker_row(memory="10MiB / 1MiB"),
            docker_row(name="secret/user@host", cid="1" * 11),
            b"a" * (metrics.MAX_DOCKER_OUTPUT + 1),
            docker_row() * (metrics.MAX_CONTAINERS + 1),
        ):
            with self.subTest(size=len(raw)), self.assertRaises(
                    metrics.MetricsDenied):
                metrics.parse_docker_stats(raw)

    def test_docker_stats_real_argument_is_fixed_readonly(self):
        proc = subprocess.CompletedProcess(["docker"], 0, docker_row(), b"PRIVATE")
        with patch.object(metrics.os, "geteuid", return_value=1000), patch.object(
                metrics.subprocess, "run", return_value=proc) as call:
            r = metrics.docker_stats({})
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["rows"][0]["name"], "fieldwork-api-1")
        argv = call.call_args.args[0]
        self.assertEqual(argv, [
            metrics.DOCKER, "--host", "unix:///var/run/docker.sock",
            "stats", "--no-stream", "--format", "{{json .}}"
        ])
        self.assertFalse(call.call_args.kwargs["shell"] if "shell" in
                         call.call_args.kwargs else False)
        self.assertEqual(call.call_args.kwargs["timeout"], 18)
        self.assertFalse(r["write_performed"])
        self.assertFalse(r["production_modified"])

    def test_query_failure_does_not_return_partial_or_raw_data(self):
        proc = subprocess.CompletedProcess(["docker"], 125, b"SECRET VALUE\n",
                                           b"SECRET")
        with patch.object(metrics.os, "geteuid", return_value=1000), patch.object(
                metrics.subprocess, "run", return_value=proc):
            with self.assertRaisesRegex(metrics.MetricsDenied,
                                        "DOCKER_STATS_QUERY_FAILED_OR_BOUNDS"):
                metrics.docker_stats({})

    def test_no_custom_docker_command(self):
        with self.assertRaisesRegex(metrics.MetricsDenied, "ARGS_SCHEMA_DENIED"):
            metrics.docker_stats({"command": "rm -f all"})

    def test_readonly_api_contains_no_mutating_docker_invocation(self):
        import inspect
        source = inspect.getsource(metrics)
        for bad in ("os.system(", "shell=True", "docker stop",
                    "docker rm", "docker prune", "docker run",
                    ".write_text(", ".write_bytes(", "subprocess.Popen"):
            self.assertNotIn(bad, source)


if __name__ == "__main__":
    unittest.main()
