"""M10: read-only local Docker inventory for a historical sandbox cleanup failure.

This does not remove or stop containers, and it does not authorize test
retries. An empty inventory match CANNOT clear the historical failed cleanup
receipt: legacy v0.6.1 container names/labels are not attested.
No output contains raw Docker labels, names, mounts, or environment variables.

Not registered with active Pi MCP; requires separate local operator review.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from typing import Any

RUN_ID_RE = re.compile(r"[a-f0-9]{32}\Z")
ID_RE = re.compile(r"[a-f0-9]{64}\Z")
MAX_CONTAINERS = 256
MAX_OUTPUT_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 8
FIXED_DOCKER_COMMAND = [
    "docker", "--host", "unix:///var/run/docker.sock", "container",
    "ls", "--all", "--no-trunc", "--format", "{{json .}}",
]
# NO Docker mutations in this module. Passing a different command is forbidden.


class HostAuditDenied(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise HostAuditDenied(code)


def _exact_run_marker(value: str, run_id: str) -> bool:
    """A bounded exact token, not a substring of another ID."""
    return bool(re.search(r"(?:^|[^a-f0-9])" + re.escape(run_id)
                          + r"(?:$|[^a-f0-9])", value.lower()))


def classify_inventory(output: bytes, run_id: str, *,
                       historical_cleanup_failed: bool = True) -> dict[str, Any]:
    """Pure parser for a complete Docker ps -a snapshot; no host I/O."""
    require(type(run_id) is str and RUN_ID_RE.fullmatch(run_id) is not None,
            "AUDIT_RUN_ID_INVALID")
    require(historical_cleanup_failed is True,
            "AUDIT_HISTORICAL_CLEANUP_RECEIPT_REQUIRED")
    require(type(output) is bytes and 0 <= len(output) <= MAX_OUTPUT_BYTES,
            "AUDIT_OUTPUT_BOUNDS_DENIED")
    try:
        text = output.decode("utf-8", errors="strict")
        lines = [line for line in text.splitlines() if line.strip()]
        require(len(lines) <= MAX_CONTAINERS, "AUDIT_TOO_MANY_CONTAINERS")
        containers = []
        for line in lines:
            item = json.loads(line)
            require(type(item) is dict, "AUDIT_DOCKER_OUTPUT_SCHEMA_DENIED")
            require(type(item.get("ID")) is str and
                    ID_RE.fullmatch(item["ID"].lower()) is not None,
                    "AUDIT_CONTAINER_ID_INVALID")
            # Docker's output names and labels are untrusted display data.
            # They are used ONLY to look for a run marker, never as a command.
            names = item.get("Names", "")
            labels = item.get("Labels", "")
            state = item.get("State", "unknown")
            require(type(names) is str and type(labels) is str and
                    type(state) is str and
                    len(names) <= 1024 and len(labels) <= 8192 and
                    len(state) <= 64,
                    "AUDIT_DOCKER_FIELDS_INVALID")
            containers.append((item["ID"].lower(), names, labels, state))
        require(len({x[0] for x in containers}) == len(containers),
                "AUDIT_DUPLICATE_CONTAINER_ID")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HostAuditDenied("AUDIT_OUTPUT_INVALID") from exc

    candidates = []
    for cid, names, labels, state in containers:
        match_type = ("name" if _exact_run_marker(names, run_id)
                      else "label" if _exact_run_marker(labels, run_id)
                      else None)
        if match_type:
            candidates.append({
                "container_id": cid,
                "match_type": match_type,
                "state": state if state in
                {"running", "exited", "created", "paused", "restarting", "dead"}
                else "unknown",
                # No names, labels, ports, mounts, or secrets are exposed.
            })

    return {
        "status": ("HISTORICAL_ORPHAN_CANDIDATE_FOUND_REVIEW_REQUIRED"
                   if candidates else
                   "HISTORICAL_CLEANUP_UNVERIFIED_NO_EXACT_MATCH"),
        "run_id": run_id,
        "inventory_container_count": len(containers),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "inventory_sha256": hashlib.sha256(output).hexdigest(),
        "inventory_source": "local_docker_container_ls_all",
        "historical_cleanup_receipt_resolved": False,
        "sandbox_test_retry_authorized": False,
        "container_removal_authorized": False,
        "host_modified": False,
        "production_modified": False,
        "tunnel_modified": False,
    }


def inspect_host(run_id: str, *, historical_cleanup_failed: bool = True) -> dict:
    """Local operator-only read-only command; no MCP or host shell exposure."""
    require(os.geteuid() != 0, "AUDIT_ROOT_DENIED")
    require(type(run_id) is str and RUN_ID_RE.fullmatch(run_id) is not None,
            "AUDIT_RUN_ID_INVALID")
    require(historical_cleanup_failed is True,
            "AUDIT_HISTORICAL_CLEANUP_RECEIPT_REQUIRED")
    # Ignore remote Docker endpoints in environment and force local daemon.
    environment = {"PATH": "/usr/local/bin:/usr/bin:/bin",
                   "HOME": os.path.expanduser("~")}
    try:
        proc = subprocess.run(
            FIXED_DOCKER_COMMAND[:],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS,
            env=environment, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostAuditDenied("AUDIT_DOCKER_QUERY_FAILED") from exc
    require(proc.returncode == 0, "AUDIT_DOCKER_QUERY_FAILED")
    return classify_inventory(proc.stdout, run_id,
                              historical_cleanup_failed=True)
