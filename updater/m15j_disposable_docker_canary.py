"""M15-J2 fixed Docker *canary* lifecycle: isolated runner CI ONLY.

Purpose: exercise real create/start/wait/inspect/delete using exact, digest-
pinned image, constrained process and network:none. This is an INCOMPLETE
sandbox helper: it cannot execute arbitrary user code, create databases or
Compose projects. Absolutely not wired into remote MCP or local systemd.

The Docker-owning account is root-equivalent on the current Pi. This module's
argv allowlist does not prove a compromised helper cannot speak directly to
Docker. Actual cutover requires separate UID, confined IPC, source trust and
36/36 compatibility gates.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

DOCKER = "/usr/bin/docker"
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]{1,160}@sha256:[a-f0-9]{64}\Z")
RUN_LABEL = "org.fieldwork.m15j.canary"
NAME_PREFIX = "fieldwork-m15j-canary-"
FMT = (
    '{{.Id}}|{{.Name}}|'
    '{{index .Config.Labels "org.fieldwork.m15j.canary"}}|'
    '{{.State.Status}}'
)
ALLOWED_STATES = ("created", "running", "exited")
MAX_TIMEOUT = 30


class CanaryDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise CanaryDenied(reason)


def name_for(run_id: str) -> str:
    require(type(run_id) is str and HEX32.fullmatch(run_id) is not None,
            "M15J_CANARY_RUN_ID_DENIED")
    return NAME_PREFIX + run_id


def build_create_argv(*, run_id: str, trusted_image: str) -> tuple[str, ...]:
    """No caller command/volume/network/user/port/device/entrypoint options."""
    name = name_for(run_id)
    require(type(trusted_image) is str and
            IMAGE.fullmatch(trusted_image) is not None,
            "M15J_CANARY_PINNED_IMAGE_REQUIRED")
    return (
        DOCKER, "container", "create",
        "--name", name,
        "--label", RUN_LABEL + "=" + run_id,
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "32",
        "--memory", "64m",
        "--cpus", "0.50",
        "--user", "65534:65534",
        "--workdir", "/",
        "--entrypoint", "/bin/true",
        trusted_image,
    )


def _run(argv: tuple[str, ...], *, expected: tuple[str, ...],
         timeout: int = MAX_TIMEOUT) -> str:
    """Only known fixed argv, not arbitrary Docker CLI or host shell."""
    require(type(argv) is tuple and argv == expected and
            argv[0] == DOCKER and
            type(timeout) is int and 1 <= timeout <= MAX_TIMEOUT,
            "M15J_DOCKER_CALL_NOT_IN_FIXED_POLICY")
    try:
        result = subprocess.run(
            list(argv), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd="/", env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
            timeout=timeout, check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise CanaryDenied("M15J_DOCKER_EXECUTION_UNVERIFIED") from None
    require(result.returncode == 0 and
            len(result.stdout) <= 512,
            "M15J_DOCKER_COMMAND_FAILED")
    try:
        return result.stdout.decode("ascii").strip()
    except UnicodeError:
        raise CanaryDenied("M15J_DOCKER_RESULT_INVALID") from None


def _inspect(run_id: str, container_id: str) -> str:
    name = name_for(run_id)
    require(type(container_id) is str and
            HEX64.fullmatch(container_id) is not None,
            "M15J_CANARY_FULL_CONTAINER_ID_REQUIRED")
    argv = (DOCKER, "container", "inspect", "--format", FMT, container_id)
    raw = _run(argv, expected=argv)
    parts = raw.split("|")
    require(len(parts) == 4 and
            parts[0] == container_id and parts[1] == "/" + name and
            parts[2] == run_id and parts[3] in ALLOWED_STATES,
            "M15J_CANARY_CONTAINER_IDENTITY_OR_OWNERSHIP_DRIFT")
    return parts[3]


def run_canary(*, run_id: str, trusted_image: str,
               source_locally_trusted: bool,
               ci_disposable_host: bool) -> dict:
    """Do not expose to the MCP or the real Pi.

    The only possible payload is /bin/true from a trusted, exact OCI digest.
    No mount, network, capability, privileged flag, Docker volume or port.
    Fail closed if cleanup cannot be positively proven.
    """
    require(source_locally_trusted is True and
            ci_disposable_host is True and os.geteuid() != 0,
            "M15J_CI_ONLY_LOCAL_NONROOT")
    create = build_create_argv(run_id=run_id, trusted_image=trusted_image)
    container_id = None
    outcome = None
    cleanup = "NOT_STARTED"
    try:
        container_id = _run(create, expected=create)
        require(HEX64.fullmatch(container_id) is not None,
                "M15J_CANARY_CREATE_NO_FULL_ID")
        state = _inspect(run_id, container_id)
        require(state == "created", "M15J_CANARY_POST_CREATE_STATE_DRIFT")
        start = (DOCKER, "container", "start", container_id)
        require(_run(start, expected=start) == container_id,
                "M15J_CANARY_START_RESULT_DRIFT")
        status = _inspect(run_id, container_id)
        require(status in {"exited", "running"},
                "M15J_CANARY_START_STATE_DRIFT")
        wait = (DOCKER, "container", "wait", container_id)
        require(_run(wait, expected=wait, timeout=MAX_TIMEOUT) == "0",
                "M15J_CANARY_PROCESS_EXIT_NONZERO")
        require(_inspect(run_id, container_id) == "exited",
                "M15J_CANARY_NOT_EXITED")
        outcome = "M15J_CI_ONLY_ISOLATED_DOCKER_LIFECYCLE_PASS"
    finally:
        if container_id is not None and HEX64.fullmatch(container_id):
            # Never delete a container without re-checking ownership by full ID.
            # On identity drift we fail closed, leaving resources untouched for
            # independent manual recovery rather than destroying a foreign ID.
            _inspect(run_id, container_id)
            delete = (DOCKER, "container", "rm", "--force", container_id)
            require(_run(delete, expected=delete) == container_id,
                    "M15J_CANARY_CLEANUP_RESULT_DRIFT")
            cleanup = "EXACT_OWNED_CONTAINER_REMOVED"
    require(outcome is not None and cleanup == "EXACT_OWNED_CONTAINER_REMOVED",
            "M15J_CANARY_INCOMPLETE")
    return {
        "status": outcome, "container_name": name_for(run_id),
        "container_id_sha256": hashlib.sha256(container_id.encode()).hexdigest(),
        "run_id": run_id, "container_removed": True,
        "network_created": False, "volume_created": False,
        "database_created": False, "host_mount_used": False,
        "shell_command_from_mcp": False,
        "production_modified": False, "pi_host_executed": False,
        "mcp_legacy_parity_verified": False,
        "cutover_authorized": False,
    }


if __name__ == "__main__":
    # No CLI run path; this is a trusted CI-only test harness.
    print(json.dumps({"status": "M15J_CANDIDATE_MODULE_NOT_ACTIVATED",
                      "docker_invoked": False, "cutover_authorized": False}))
