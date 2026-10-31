"""M15-F: independently invoked, read-only target-PID Linux privilege evidence.

This is a local audit library/CLI candidate, NEVER a remotely callable MCP tool.
It does NOT prove OS privilege separation or approve Docker/socket changes.
The target PID and expected identity MUST originate from local trusted service
discovery, never from a remote MCP-supplied self-description.

No subprocess, Docker API, sudo invocation, credential reads or writes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat

if __package__:
    from . import linux_host_privilege_preflight as self_audit
else:
    import linux_host_privilege_preflight as self_audit

MAX_STAT = 4096
MAX_STATUS = 16384
MAX_PID = 4194304
DEFAULT_DOCKER_SOCKET = Path("/var/run/docker.sock")


class HostBoundaryDenied(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise HostBoundaryDenied(code)


def _read_proc(path: Path, limit: int) -> bytes:
    """Read only one exact procfs member; procfs st_size may be zero."""
    require(isinstance(path, Path) and limit in (MAX_STAT, MAX_STATUS),
            "HOST_PROC_PATH_DENIED")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC |
                     getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode),
                    "HOST_PROC_NOT_FILE")
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise HostBoundaryDenied("HOST_PROC_UNREADABLE") from exc
    require(0 < len(raw) <= limit, "HOST_PROC_SIZE_DENIED")
    return raw


def starttime_from_stat(raw: bytes, expected_pid: int) -> int:
    """Linux /proc/PID/stat field 22. comm may contain spaces and ')'.

    Only the last close-parenthesis delimiting comm is used, and all
    other fields are treated as numeric/opaque without disclosure.
    """
    require(type(raw) is bytes and 0 < len(raw) <= MAX_STAT,
            "HOST_PID_STAT_SIZE_DENIED")
    try:
        line = raw.decode("ascii").strip()
    except UnicodeError as exc:
        raise HostBoundaryDenied("HOST_PID_STAT_ENCODING_DENIED") from exc
    prefix = str(expected_pid) + " ("
    require(line.startswith(prefix), "HOST_PID_STAT_PID_MISMATCH")
    close = line.rfind(")")
    require(close > len(prefix) and line[close + 1:close + 3] == "  ",
            "HOST_PID_STAT_FORMAT_DENIED")
    fields = line[close + 2:].split()
    # Field 3 is state, field 22 is starttime => index 19.
    require(len(fields) >= 20 and fields[0] not in ("Z", "X", "x"),
            "HOST_PID_INACTIVE_OR_TRUNCATED")
    start = fields[19]
    require(re.fullmatch(r"[0-9]{1,20}", start) is not None,
            "HOST_PID_STARTTIME_INVALID")
    return int(start)


def _socket_evidence(sock: os.stat_result | None,
                     *, euid: int, egid: int,
                     groups: tuple[int, ...],
                     unobservable: bool) -> tuple[str, list[str]]:
    flags: list[str] = []
    if unobservable:
        return "UNVERIFIED", ["DOCKER_DEFAULT_SOCKET_UNVERIFIED"]
    if sock is None:
        return "ABSENT_AT_DEFAULT_PATH_ONLY", []
    if not stat.S_ISSOCK(sock.st_mode):
        return "NON_SOCKET_OR_SYMLINK", ["DOCKER_DEFAULT_PATH_NOT_SOCKET"]
    effective_groups = set(groups) | {egid}
    maybe_write = bool(
        euid == 0 or
        (euid == sock.st_uid and sock.st_mode & stat.S_IWUSR) or
        (sock.st_gid in effective_groups and sock.st_mode & stat.S_IWGRP) or
        (sock.st_mode & stat.S_IWOTH)
    )
    if maybe_write:
        return "DAC_WRITE_POSSIBLE", ["DOCKER_DEFAULT_SOCKET_DAC_WRITE"]
    return "DAC_WRITE_NOT_OBSERVED_ONLY", []


def assess_observation(*, pid: int, expected_uid: int,
                       expected_starttime: int,
                       stat_before: bytes, status: bytes,
                       stat_after: bytes,
                       docker_socket: os.stat_result | None,
                       docker_socket_unobservable: bool = False) -> dict:
    """Pure, bounded consistency evaluation; ALWAYS non-authorizing."""
    require(type(pid) is int and 1 < pid <= MAX_PID and
            type(expected_uid) is int and expected_uid >= 0 and
            type(expected_starttime) is int and expected_starttime > 0,
            "HOST_TRUSTED_TARGET_INVALID")
    first = starttime_from_stat(stat_before, pid)
    final = starttime_from_stat(stat_after, pid)
    require(first == expected_starttime == final,
            "HOST_TARGET_PID_REUSED_OR_CHANGED")
    try:
        p = self_audit._parse_status(status)
    except self_audit.PrivilegePreflightDenied as exc:
        raise HostBoundaryDenied("HOST_STATUS_INVALID") from exc
    uids, gids = p["uids"], p["gids"]
    require(uids[1] == expected_uid, "HOST_TARGET_UID_MISMATCH")
    require(type(docker_socket_unobservable) is bool and
            not (docker_socket_unobservable and docker_socket is not None),
            "HOST_SOCKET_INPUT_DENIED")
    state, indicators = _socket_evidence(
        docker_socket, euid=uids[1], egid=gids[1], groups=p["groups"],
        unobservable=docker_socket_unobservable)
    if 0 in uids or 0 in gids or 0 in p["groups"]:
        indicators.append("TARGET_ROOT_ID_PRESENT")
    if p["cap_eff"]:
        indicators.append("TARGET_EFFECTIVE_CAPABILITIES")
    if not p["no_new_privileges"]:
        indicators.append("TARGET_NO_NEW_PRIVS_DISABLED")
    return {
        "status": "HOST_BOUNDARY_AUDIT_INCOMPLETE",
        "target": {"pid": pid, "starttime_ticks": first,
                   "expected_effective_uid": expected_uid,
                   "observed_effective_uid": uids[1],
                   "observed_effective_gid": gids[1],
                   "supplementary_gids": list(p["groups"])},
        "observed_capabilities_nonzero": bool(p["cap_eff"]),
        "observed_no_new_privileges": p["no_new_privileges"],
        "default_docker_socket": state,
        "risk_indicators": sorted(set(indicators)),
        "limits": {
            "service_unit_identity": "NOT_VERIFIED",
            "sudoers_and_setuid": "NOT_AUDITED",
            "inherited_open_fds": "NOT_AUDITED",
            "rootless_podman_or_other_daemon": "NOT_AUDITED",
            "docker_daemon_privileges": "NOT_AUDITED",
            "acl_lsm_and_namespaces": "NOT_AUDITED",
            "publisher_identity": "NOT_VERIFIED",
            "source_chain": "NOT_VERIFIED",
            "operator_physically_present": "NOT_VERIFIED",
        },
        "host_writes": False,
        "remote_mcp_tool": False,
        "isolation_verified": False,
        "safe_to_revoke_legacy_docker_access": False,
        "safe_to_install_operator_secret": False,
        "production_deployment_authorized": False,
    }


def collect_local(*, pid: int, expected_uid: int,
                  expected_starttime: int) -> dict:
    """Inspect a separately identified PID; *NOT* independent attestation.

    Caller must independently establish target PID/source provenance.
    The result cannot be used as privilege-separation approval.
    """
    require(os.name == "posix" and Path("/proc").is_dir(),
            "HOST_LINUX_PROC_REQUIRED")
    require(type(pid) is int and 1 < pid <= MAX_PID,
            "HOST_PID_INVALID")
    root = Path("/proc") / str(pid)
    first = _read_proc(root / "stat", MAX_STAT)
    status = _read_proc(root / "status", MAX_STATUS)
    after = _read_proc(root / "stat", MAX_STAT)
    try:
        sock = DEFAULT_DOCKER_SOCKET.lstat()
        unreadable = stat.S_ISLNK(sock.st_mode)
    except FileNotFoundError:
        sock = None
        unreadable = False
    except OSError:
        sock = None
        unreadable = True
    return assess_observation(
        pid=pid, expected_uid=expected_uid,
        expected_starttime=expected_starttime,
        stat_before=first, status=status, stat_after=after,
        docker_socket=None if unreadable else sock,
        docker_socket_unobservable=unreadable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="M15F LOCAL-ONLY PID evidence. Never authorizes changes.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--expected-uid", type=int, required=True)
    parser.add_argument("--expected-starttime", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = collect_local(
            pid=args.pid, expected_uid=args.expected_uid,
            expected_starttime=args.expected_starttime)
    except HostBoundaryDenied as exc:
        result = {"status": "HOST_BOUNDARY_AUDIT_DENIED",
                  "reason": str(exc), "isolation_verified": False,
                  "production_deployment_authorized": False}
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
