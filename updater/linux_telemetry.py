"""Portable, read-only Linux telemetry primitives (M13 foundation).

No Raspberry Pi-specific paths, no Docker dependency, no root/sudo required.
The parser accepts bounded data from the Linux proc filesystem and yields
numeric, sanitized metrics. The live MCP adapter is deliberately not
installed as part of this module.

Do NOT infer the host's *physical* RAM from a container/cgroup view without
explicitly reporting the measurement scope.
"""
from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
import re

MAX_PROC_BYTES = 64 * 1024
REQUIRED_MEM_FIELDS = ("MemTotal", "MemAvailable")
MEM_ITEM = re.compile(r"([A-Za-z][A-Za-z_()]*):\s*([0-9]+)\s*kB\s*\Z")
CPU_COUNTERS = 8  # user, nice, system, idle, iowait, irq, softirq, steal
MAX_COUNTER = 2**63 - 1
MAX_MEMORY_KIB = 2**52
MAX_LOAD = 10**7
PROC = Path("/proc")


class TelemetryDenied(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise TelemetryDenied(code)


def _bounded_text(data: str) -> str:
    require(type(data) is str and len(data) <= MAX_PROC_BYTES,
            "PROC_CONTENT_INVALID_OR_TOO_LARGE")
    return data


def parse_meminfo(data: str) -> dict:
    """Use MemAvailable (includes reclaimable cache), not MemFree."""
    data = _bounded_text(data)
    values = {}
    for line in data.splitlines():
        match = MEM_ITEM.fullmatch(line.strip())
        if match:
            key, value = match.groups()
            if key in values:
                raise TelemetryDenied("MEMINFO_DUPLICATE_KEY")
            n = int(value)
            require(n <= MAX_MEMORY_KIB, "MEMINFO_COUNTER_OVERFLOW")
            values[key] = n
    require(all(k in values for k in REQUIRED_MEM_FIELDS),
            "MEMINFO_REQUIRED_FIELD_MISSING")
    total, available = values["MemTotal"], values["MemAvailable"]
    require(total > 0 and 0 <= available <= total,
            "MEMINFO_INCONSISTENT")
    used = total - available
    result = {
        "scope": "linux_proc_meminfo",
        "total_kib": total,
        "available_kib": available,
        "used_estimate_kib": used,
        "used_estimate_pct": round(used * 100 / total, 2),
    }
    if "SwapTotal" in values and "SwapFree" in values:
        swap_total, swap_free = values["SwapTotal"], values["SwapFree"]
        require(swap_free <= swap_total, "SWAP_INCONSISTENT")
        result.update({
            "swap_total_kib": swap_total,
            "swap_used_kib": swap_total - swap_free,
        })
    return result


def parse_cpu_total(data: str) -> dict:
    """Aggregate host CPU counters, excluding guest counters (double count)."""
    data = _bounded_text(data)
    matches = [line for line in data.splitlines() if line.startswith("cpu ")]
    require(len(matches) == 1, "CPU_AGGREGATE_MISSING_OR_DUPLICATE")
    parts = matches[0].split()
    require(len(parts) >= 1 + CPU_COUNTERS,
            "CPU_COUNTERS_MISSING")
    try:
        numbers = [int(v) for v in parts[1:1 + CPU_COUNTERS]]
    except ValueError as exc:
        raise TelemetryDenied("CPU_COUNTER_NONINTEGER") from exc
    require(all(0 <= n <= MAX_COUNTER for n in numbers),
            "CPU_COUNTER_OUT_OF_RANGE")
    return {
        "total_ticks": sum(numbers),
        "idle_ticks": numbers[3] + numbers[4],
    }


def cpu_percent_between(before: dict, after: dict) -> float:
    """Two monotonic snapshots. No sleep, no timing assumptions."""
    for x in (before, after):
        require(type(x) is dict and
                set(x) == {"total_ticks", "idle_ticks"} and
                all(type(v) is int and v >= 0 for v in x.values()) and
                x["idle_ticks"] <= x["total_ticks"],
                "CPU_SNAPSHOT_SCHEMA_INVALID")
    total = after["total_ticks"] - before["total_ticks"]
    idle = after["idle_ticks"] - before["idle_ticks"]
    require(total > 0 and 0 <= idle <= total,
            "CPU_COUNTERS_NOT_MONOTONIC")
    return round(100 * (total - idle) / total, 2)


def parse_loadavg(data: str) -> dict:
    data = _bounded_text(data).strip()
    parts = data.split()
    require(len(parts) >= 3, "LOADAVG_MISSING")
    try:
        values = [float(n) for n in parts[:3]]
    except ValueError as exc:
        raise TelemetryDenied("LOADAVG_NONNUMERIC") from exc
    require(all(math.isfinite(n) and 0 <= n <= MAX_LOAD for n in values),
            "LOADAVG_INVALID")
    return dict(zip(("load_1min", "load_5min", "load_15min"), values))


def parse_proc_snapshot(meminfo: str, stat: str, loadavg: str) -> dict:
    """Pure construction: suitable for a future allowlisted MCP endpoint."""
    return {
        "status": "LINUX_PROC_SNAPSHOT",
        "memory": parse_meminfo(meminfo),
        "cpu_counters": parse_cpu_total(stat),
        "load": parse_loadavg(loadavg),
        "writes_performed": False,
        "cpu_instant_percent_available": False,
    }


def _read_proc(name: str, *, root: Path = PROC) -> str:
    """Internal fixed names only. Tests may inject an isolated fake proc."""
    require(name in ("meminfo", "stat", "loadavg"), "PROC_FILE_NOT_ALLOWED")
    require(type(root) is Path and root.is_dir() and not root.is_symlink(),
            "PROC_ROOT_INVALID")
    path = root / name
    require(path.is_file() and not path.is_symlink(),
            "PROC_ENTRY_INVALID")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_PROC_BYTES + 1)
    except OSError as exc:
        raise TelemetryDenied("PROC_READ_FAILED") from exc
    require(0 < len(data) <= MAX_PROC_BYTES, "PROC_CONTENT_TOO_LARGE")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TelemetryDenied("PROC_CONTENT_NONASCII") from exc


def collect_proc_snapshot(*, proc_root: Path = PROC) -> dict:
    """Read 3 fixed proc entries, no subprocess, shell, network, or writes."""
    return parse_proc_snapshot(*(
        _read_proc(name, root=proc_root)
        for name in ("meminfo", "stat", "loadavg")
    ))
