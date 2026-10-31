"""Portable Linux telemetry contract tests. No network/Docker/device access."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from updater import linux_telemetry as m


MEMINFO = ("MemTotal:       1024000 kB\n"
           "MemFree:          10000 kB\n"
           "MemAvailable:    400000 kB\n"
           "Buffers:          1000 kB\n"
           "Cached:         250000 kB\n"
           "SwapTotal:      200000 kB\n"
           "SwapFree:       150000 kB\n")
STAT_1 = "cpu  100 0 100 700 50 10 20 20 0 0\ncpu0 55 0 30 200 15 0 0 0\n"
STAT_2 = "cpu  150 0 150 750 50 10 20 20 0 0\ncpu0 65 0 40 220 15 0 0 0\n"
LOAD = "0.47 0.65 0.12 1/225 1122\n"


class LinuxTelemetryContract(unittest.TestCase):
    def test_memavailable_not_memfree(self):
        r = m.parse_meminfo(MEMINFO)
        self.assertEqual(r["total_kib"], 1024000)
        self.assertEqual(r["available_kib"], 400000)
        self.assertEqual(r["used_estimate_kib"], 624000)
        self.assertEqual(r["used_estimate_pct"], 60.94)
        self.assertEqual(r["swap_used_kib"], 50000)

    def test_cache_does_not_count_as_necessarily_unavailable(self):
        r = m.parse_meminfo(MEMINFO.replace("MemFree:          10000", "MemFree:              0"))
        self.assertEqual(r["used_estimate_kib"], 624000)

    def test_minimal_kernel_meminfo_no_swap(self):
        result = m.parse_meminfo("MemTotal: 128 kB\nMemAvailable: 8 kB\n")
        self.assertNotIn("swap_total_kib", result)
        self.assertEqual(result["used_estimate_pct"], 93.75)

    def test_missing_mismatched_or_duplicate_memory_denied(self):
        bad = [
            "", "MemTotal: 100 kB\n",
            "MemTotal: 100 kB\nMemAvailable: 101 kB\n",
            "MemTotal: 0 kB\nMemAvailable: 0 kB\n",
            MEMINFO + "MemTotal: 1024000 kB\n",
            MEMINFO.replace("SwapFree:       150000", "SwapFree:       300000"),
        ]
        for text in bad:
            with self.subTest(value=text[:50]), self.assertRaises(m.TelemetryDenied):
                m.parse_meminfo(text)

    def test_cpu_two_monotonic_samples_compute_busy_fraction(self):
        before = m.parse_cpu_total(STAT_1)
        after = m.parse_cpu_total(STAT_2)
        self.assertEqual(m.cpu_percent_between(before, after), 66.67)

    def test_extra_guest_not_double_counted(self):
        result = m.parse_cpu_total(STAT_1)
        self.assertEqual(result["total_ticks"], 1000)
        self.assertEqual(result["idle_ticks"], 750)

    def test_cpu_short_or_bad_counters_denied(self):
        for bad in ("", "cpu 1 2 3\n", "cpu 1 z 2 3 4 5 6 7\n",
                    "cpu 1 -2 3 4 5 6 7 8\n",
                    STAT_1 + "cpu 1 2 3 4 5 6 7 8\n"):
            with self.subTest(bad=bad), self.assertRaises(m.TelemetryDenied):
                m.parse_cpu_total(bad)

    def test_cpu_snapshot_mismatches_denied(self):
        before = m.parse_cpu_total(STAT_1)
        for bad in (
            before,
            {"total_ticks": 1200, "idle_ticks": 100},
            {"total_ticks": 1100, "idle_ticks": 1000},
            {"total_ticks": True, "idle_ticks": 751},
            {"total_ticks": 1100},
            {"total_ticks": 1000, "idle_ticks": 751},
        ):
            with self.subTest(bad=bad), self.assertRaises(m.TelemetryDenied):
                m.cpu_percent_between(before, bad)

    def test_loadavg_and_invalid_nonfinite(self):
        self.assertEqual(
            m.parse_loadavg(LOAD),
            {"load_1min": 0.47, "load_5min": 0.65, "load_15min": 0.12},
        )
        for bad in ("", "-0.1 0 0", "nan 0 0", "inf 1 2", "abc 1 2"):
            with self.subTest(bad=bad), self.assertRaises(m.TelemetryDenied):
                m.parse_loadavg(bad)

    def test_only_allowed_readonly_proc_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "meminfo").write_text(MEMINFO, encoding="ascii")
            (root / "stat").write_text(STAT_1, encoding="ascii")
            (root / "loadavg").write_text(LOAD, encoding="ascii")
            for unexpected in ("../../etc/shadow", "environ", "self/cmdline"):
                with self.subTest(unexpected=unexpected), self.assertRaises(
                        m.TelemetryDenied):
                    m._read_proc(unexpected, root=root)
            result = m.collect_proc_snapshot(proc_root=root)
            self.assertEqual(result["status"], "LINUX_PROC_SNAPSHOT")
            self.assertFalse(result["writes_performed"])
            self.assertFalse(result["cpu_instant_percent_available"])

    def test_symlink_proc_entry_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            external = root / "secret"
            external.write_text(MEMINFO)
            (root / "meminfo").symlink_to(external)
            with self.assertRaisesRegex(m.TelemetryDenied,
                                        "PROC_ENTRY_INVALID"):
                m._read_proc("meminfo", root=root)

    def test_bounded_proc_entry_denied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "stat").write_bytes(b"x" * (m.MAX_PROC_BYTES + 1))
            with self.assertRaisesRegex(m.TelemetryDenied, "PROC_CONTENT_TOO_LARGE"):
                m._read_proc("stat", root=root)

    def test_parse_single_snapshot_is_host_neutral(self):
        r = m.parse_proc_snapshot(MEMINFO, STAT_1, LOAD)
        self.assertEqual(r["memory"]["scope"], "linux_proc_meminfo")
        self.assertNotIn("hostname", str(r))
        self.assertNotIn("cmdline", str(r))
        self.assertFalse(r["cpu_instant_percent_available"])

    def test_module_does_not_use_subprocess_or_modify_service(self):
        import inspect
        code = inspect.getsource(m)
        for term in ("import subprocess", "subprocess.run(", "os.system(", "sudo ", "systemctl", "docker run",
                     "docker rm", "shell=True", "shutil.rmtree(", ".unlink(", ".write_bytes("):
            self.assertNotIn(term, code)


if __name__ == "__main__":
    unittest.main()
