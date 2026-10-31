"""M13 Linux host + optional Docker telemetry MCP handlers.

No host shell or mutable Docker action; fixed procfs paths and fixed docker
stats argv only. Zero arbitrary paths / commands / output of process argv.
This file is intended to be co-located with linux_telemetry.py on Linux.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time

import linux_telemetry as core


DOCKER = "/usr/bin/docker"
MAX_DOCKER_OUTPUT = 200_000
MAX_CONTAINERS = 96
MAX_NAME = 100
CPU_SAMPLING_SECONDS = 0.4
CPU_METRIC = re.compile(r"(?P<n>[0-9]+(?:\.[0-9]{1,3})?)%\Z")
MEMORY_METRIC = re.compile(
    r"(?P<n>[0-9]+(?:\.[0-9]{1,3})?)\s*(?P<u>B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\Z"
)
HEX_ID = re.compile(r"[0-9a-fA-F]{12,64}\Z")
SAFE_CONTAINER_NAME = re.compile(r"fieldwork[-_][a-zA-Z0-9_.-]{1,90}\Z")
UNITS = {
    "B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2,
    "GB": 1000**3, "TB": 1000**4,
    "KiB": 1024, "MiB": 1024**2,
    "GiB": 1024**3, "TiB": 1024**4,
}


class MetricsDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise MetricsDenied(code)


def _args(value: object) -> None:
    require(type(value) is dict and not value, "ARGS_SCHEMA_DENIED")


def _pct(raw: object, max_value: float) -> float:
    require(type(raw) is str and len(raw) <= 24, "CPU_PERCENT_INVALID")
    m = CPU_METRIC.fullmatch(raw)
    require(m is not None, "CPU_PERCENT_INVALID")
    value = float(m.group("n"))
    require(math.isfinite(value) and 0 <= value <= max_value,
            "CPU_PERCENT_OUT_OF_BOUNDS")
    return round(value, 3)


def _bytes(raw: object) -> int:
    require(type(raw) is str and len(raw) <= 35, "MEMORY_UNIT_INVALID")
    m = MEMORY_METRIC.fullmatch(raw)
    require(m is not None, "MEMORY_UNIT_INVALID")
    value = float(m.group("n")) * UNITS[m.group("u")]
    require(math.isfinite(value) and 0 <= value <= 2**62,
            "MEMORY_VALUE_OUT_OF_BOUNDS")
    return round(value)


def _memory_pair(raw: object) -> tuple[int, int]:
    require(type(raw) is str and len(raw) <= 90, "MEMORY_USAGE_INVALID")
    parts = raw.split(" / ")
    require(len(parts) == 2, "MEMORY_USAGE_INVALID")
    used, limit = _bytes(parts[0]), _bytes(parts[1])
    require(0 <= used <= limit, "MEMORY_USAGE_INCONSISTENT")
    return used, limit


def host_metrics(args: object) -> dict:
    """One CPU interval and host proc memory, no subprocess or writes."""
    _args(args)
    require(os.geteuid() != 0, "ROOT_DENIED")
    try:
        before = core.collect_proc_snapshot()
        start = time.monotonic()
        time.sleep(CPU_SAMPLING_SECONDS)
        after = core.collect_proc_snapshot()
        duration = time.monotonic() - start
        cpu_pct = core.cpu_percent_between(
            before["cpu_counters"], after["cpu_counters"]
        )
    except core.TelemetryDenied as exc:
        raise MetricsDenied("PROC_TELEMETRY_DENIED") from exc
    require(0.1 <= duration <= 10, "SAMPLING_INTERVAL_INVALID")
    return {
        "status": "READ_ONLY_LINUX_HOST_METRICS",
        "platform": "linux",
        "scope": "procfs_visible_to_agent_not_guaranteed_physical_host",
        "cpu_busy_pct": cpu_pct,
        "cpu_interval_seconds": round(duration, 3),
        "memory": after["memory"],
        "load": after["load"],
        "write_performed": False,
        "production_modified": False,
    }


def parse_docker_stats(data: bytes) -> list[dict]:
    require(type(data) is bytes and len(data) <= MAX_DOCKER_OUTPUT,
            "DOCKER_OUTPUT_SIZE_DENIED")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise MetricsDenied("DOCKER_OUTPUT_UTF8_DENIED") from exc
    require(len(lines) <= MAX_CONTAINERS, "DOCKER_ROWS_OVER_LIMIT")
    result = []
    ids = set()
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise MetricsDenied("DOCKER_JSON_INVALID") from exc
        require(type(row) is dict, "DOCKER_ROW_TYPE_DENIED")
        cid, name = row.get("ID"), row.get("Name")
        require(type(cid) is str and HEX_ID.fullmatch(cid) is not None and
                type(name) is str and len(name) <= MAX_NAME,
                "DOCKER_ID_OR_NAME_INVALID")
        require(cid.lower() not in ids, "DOCKER_ID_DUPLICATE")
        ids.add(cid.lower())
        cpu = _pct(row.get("CPUPerc"), 100000)
        used, limit = _memory_pair(row.get("MemUsage"))
        # Don't expose image names, mounts, labels, env or raw stdout.
        result.append({
            "container_id": cid.lower(),
            "name": name if SAFE_CONTAINER_NAME.fullmatch(name)
                      else "<OTHER_CONTAINER>",
            "cpu_percent_of_one_core": cpu,
            "memory_used_bytes": used,
            "memory_limit_bytes": limit,
        })
    result.sort(key=lambda x: (x["cpu_percent_of_one_core"],
                               x["memory_used_bytes"]), reverse=True)
    return result


def docker_stats(args: object) -> dict:
    """Docker stats is read-only; no user-selected IDs or mutating verbs."""
    _args(args)
    require(os.geteuid() != 0, "ROOT_DENIED")
    cmd = [DOCKER, "--host", "unix:///var/run/docker.sock",
           "stats", "--no-stream", "--format", "{{json .}}"]
    try:
        proc = subprocess.run(
            cmd, cwd="/", env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=18, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MetricsDenied("DOCKER_STATS_QUERY_FAILED") from exc
    require(proc.returncode == 0 and len(proc.stdout) <= MAX_DOCKER_OUTPUT,
            "DOCKER_STATS_QUERY_FAILED_OR_BOUNDS")
    rows = parse_docker_stats(proc.stdout)
    return {
        "status": "READ_ONLY_DOCKER_RESOURCE_STATS",
        "scope": "docker_running_containers",
        "cpu_unit": "percent_of_one_cpu_core_can_exceed_100",
        "count": len(rows),
        "rows": rows,
        "write_performed": False,
        "production_modified": False,
    }
