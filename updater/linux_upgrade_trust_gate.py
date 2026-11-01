"""M14C independent local OS privilege-boundary preflight.

Read-only security assessment. Never changes users, services, permissions,
Docker, files, or the MCP. On conventional rootful Docker, a process with
write access to the Docker socket is effectively host-root capable, even
when its MCP API advertises only read-only Docker functions. Thus a signing
key in another Unix user's home is not an isolation boundary until the
remotely controlled process loses that capability.

A reported PASS is a narrow LOCAL preflight, not formal proof of isolation,
not authorization to deploy, and not security certification.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat


class TrustDenied(ValueError):
    pass


def require(ok: bool, code: str):
    if not ok:
        raise TrustDenied(code)


@dataclass(frozen=True)
class ProcessProbe:
    euid: int
    egid: int
    groups: tuple[int, ...]
    docker_socket_present: bool
    docker_socket_accessible: bool
    docker_socket_is_socket: bool
    sudoers_independently_verified: bool = False


def probe_mcp_process(*, docker_socket: Path = Path("/var/run/docker.sock")) -> ProcessProbe:
    """Only read process identity and Docker socket metadata.

    Unknown or inaccessible socket metadata is not reported as an isolation
    PASS: the caller has to establish independently that the remote MCP
    cannot reach an equivalent Docker daemon or host-privileged API.
    """
    require(isinstance(docker_socket, Path) and
            docker_socket.is_absolute() and
            str(docker_socket) == "/var/run/docker.sock",
            "TRUST_SOCKET_PATH_DENIED")
    try:
        identity = (os.geteuid(), os.getegid(), tuple(sorted(os.getgroups())))
        info = docker_socket.stat()
        socket_present = True
        is_socket = stat.S_ISSOCK(info.st_mode)
        accessible = os.access(docker_socket, os.W_OK)
    except FileNotFoundError:
        socket_present = False
        is_socket = False
        accessible = False
    except OSError as exc:
        raise TrustDenied("TRUST_SOCKET_METADATA_UNAVAILABLE") from exc
    return ProcessProbe(*identity, socket_present, accessible, is_socket)


def evaluate_remote_mcp(probe: ProcessProbe) -> dict:
    require(isinstance(probe, ProcessProbe) and
            type(probe.euid) is int and probe.euid >= 0 and
            type(probe.egid) is int and probe.egid >= 0 and
            type(probe.groups) is tuple and
            all(type(n) is int and n >= 0 for n in probe.groups) and
            type(probe.docker_socket_present) is bool and
            type(probe.docker_socket_accessible) is bool and
            type(probe.docker_socket_is_socket) is bool and
            type(probe.sudoers_independently_verified) is bool,
            "TRUST_PROBE_SCHEMA_DENIED")
    blockers = []
    if probe.euid == 0 or probe.egid == 0 or 0 in probe.groups:
        blockers.append("REMOTE_MCP_ROOT_CAPABILITY")
    if probe.docker_socket_accessible:
        blockers.append("REMOTE_MCP_DOCKER_SOCKET_WRITE_ACCESS")
    if probe.docker_socket_present and not probe.docker_socket_is_socket:
        blockers.append("DOCKER_SOCKET_UNEXPECTED_TYPE")
    # Checking /var/run/docker.sock is not enough to certify isolation:
    # rootless Docker, podman, a configured DOCKER_HOST, sudo or another
    # privileged helper may exist; they need separate local-admin review.
    blockers.append("OTHER_PRIVILEGED_PATHS_NOT_INDEPENDENTLY_AUDITED")
    return {
        "status": "PRIVILEGE_ISOLATION_BLOCKED" if blockers else
                  "PRIVILEGE_ISOLATION_NARROW_PREFLIGHT_PASS",
        "blockers": blockers,
        "remote_mcp_euid": probe.euid,
        "docker_socket_present": probe.docker_socket_present,
        "docker_socket_write_access": probe.docker_socket_accessible,
        "ready_for_local_approval_secret": False,
        "write_performed": False,
    }


def compare_operator_boundary(*, remote_mcp_euid: int, operator_euid: int,
                              operator_secret_readable_by_mcp: bool) -> dict:
    """Local operator-side independent check; caller attests secret access.

    The caller MUST NOT take operator_secret_readable_by_mcp from remote
    MCP data. In real deployments this assessment is performed by a
    separate trusted local bootstrap with permission/namespace tests.
    """
    require(type(remote_mcp_euid) is int and remote_mcp_euid >= 0 and
            type(operator_euid) is int and operator_euid > 0 and
            type(operator_secret_readable_by_mcp) is bool,
            "TRUST_BOUNDARY_INPUT_DENIED")
    blockers = []
    if remote_mcp_euid == operator_euid:
        blockers.append("OPERATOR_AND_REMOTE_MCP_SHARE_UID")
    if operator_secret_readable_by_mcp:
        blockers.append("REMOTE_MCP_CAN_READ_OPERATOR_SECRET")
    return {
        "status": "ROLE_BOUNDARY_BLOCKED" if blockers else
                  "ROLE_BOUNDARY_PRELIMINARY_PASS",
        "blockers": blockers,
        "local_approval_enabled": False,
    }
