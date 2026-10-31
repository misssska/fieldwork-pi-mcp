"""M15-D local-process privilege evidence; never an activation authority.

Read-only, no subprocess, no arbitrary host paths and no Docker API calls.
The snapshot describes ONLY the invoking process, not an MCP process elsewhere.
It cannot prove absence of sudo, ACL grants, inherited file descriptors,
privileged helpers, user-namespace host mappings or Linux security policy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys

PROC_STATUS = Path("/proc/self/status")
DOCKER_SOCKET = Path("/var/run/docker.sock")
MAX_STATUS_BYTES = 16384
REQUIRED = frozenset({"Uid", "Gid", "Groups", "CapEff", "NoNewPrivs"})


class PrivilegePreflightDenied(ValueError):
    pass


def _deny(condition: bool, code: str) -> None:
    if not condition:
        raise PrivilegePreflightDenied(code)


def _parse_status(raw: bytes) -> dict:
    _deny(type(raw) is bytes and 0 < len(raw) <= MAX_STATUS_BYTES,
          "PROC_STATUS_SIZE_DENIED")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise PrivilegePreflightDenied("PROC_STATUS_ENCODING_DENIED") from exc
    observed = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and key in REQUIRED:
            _deny(key not in observed, "PROC_STATUS_DUPLICATE_DENIED")
            observed[key] = value.strip()
    _deny(set(observed) == REQUIRED, "PROC_STATUS_INCOMPLETE_DENIED")

    def decimal_fields(key: str, count: int | None = None) -> tuple[int, ...]:
        parts = observed[key].split()
        _deny((count is None or len(parts) == count) and
              (bool(parts) or key == "Groups") and
              all(re.fullmatch(r"[0-9]{1,10}", x) for x in parts),
              "PROC_STATUS_NUMBER_DENIED")
        return tuple(int(x) for x in parts)

    uids = decimal_fields("Uid", 4)
    gids = decimal_fields("Gid", 4)
    groups = decimal_fields("Groups")
    _deny(len(groups) == len(set(groups)), "PROC_STATUS_GROUP_DUPLICATE_DENIED")
    _deny(re.fullmatch(r"[0-9A-Fa-f]{1,16}", observed["CapEff"]) is not None,
          "PROC_STATUS_CAPABILITY_DENIED")
    _deny(observed["NoNewPrivs"] in {"0", "1"},
          "PROC_STATUS_NNP_DENIED")
    return {"uids": uids, "gids": gids, "groups": groups,
            "cap_eff": int(observed["CapEff"], 16),
            "no_new_privileges": observed["NoNewPrivs"] == "1"}


def evaluate(status_bytes: bytes, *, euid: int, egid: int,
             supplementary_groups: tuple[int, ...],
             docker_socket_stat: os.stat_result | None,
             socket_unobservable: bool = False) -> dict:
    """Pure self-process classification, always non-authorizing."""
    parsed = _parse_status(status_bytes)
    _deny(type(euid) is int and type(egid) is int and
          euid >= 0 and egid >= 0 and
          type(supplementary_groups) is tuple and
          all(type(x) is int and x >= 0 for x in supplementary_groups),
          "PROCESS_ID_INPUT_DENIED")
    _deny(parsed["uids"][1] == euid and parsed["gids"][1] == egid and
          set(parsed["groups"]) == set(supplementary_groups),
          "PROC_PROCESS_IDENTITY_MISMATCH")
    _deny(type(socket_unobservable) is bool and
          not (socket_unobservable and docker_socket_stat is not None),
          "SOCKET_OBSERVATION_INPUT_DENIED")

    flags = []
    if euid == 0:
        flags.append("EFFECTIVE_ROOT")
    if parsed["cap_eff"]:
        flags.append("EFFECTIVE_LINUX_CAPABILITIES")
    if not parsed["no_new_privileges"]:
        flags.append("NO_NEW_PRIVS_DISABLED")

    socket_state = "ABSENT_AT_FIXED_PATH"
    if socket_unobservable:
        socket_state = "UNVERIFIED_ACCESS_OR_SYMLINK"
        flags.append("DOCKER_SOCKET_UNVERIFIED")
    elif docker_socket_stat is not None:
        mode = docker_socket_stat.st_mode
        if not stat.S_ISSOCK(mode):
            socket_state = "NON_SOCKET_AT_FIXED_PATH"
            flags.append("DOCKER_PATH_NOT_A_SOCKET")
        else:
            socket_state = "UNIX_SOCKET_OBSERVED"
            groups = set(supplementary_groups) | {egid}
            can_write = bool(
                (docker_socket_stat.st_uid == euid and mode & stat.S_IWUSR) or
                (docker_socket_stat.st_gid in groups and mode & stat.S_IWGRP) or
                (mode & stat.S_IWOTH)
            )
            if can_write or euid == 0:
                socket_state = "DAC_WRITE_POSSIBLE"
                flags.append("DOCKER_SOCKET_WRITE_POSSIBLE")
            else:
                socket_state = "DAC_WRITE_NOT_OBSERVED"

    return {
        "status": ("SELF_PRIVILEGE_RISK_OBSERVED" if flags
                   else "SELF_PRIVILEGE_EVIDENCE_INCOMPLETE"),
        "scope": "INVOKING_PROCESS_ONLY",
        "euid": euid, "egid": egid,
        "cap_eff_nonzero": bool(parsed["cap_eff"]),
        "no_new_privileges": parsed["no_new_privileges"],
        "docker_socket": socket_state,
        "indicators": sorted(set(flags)),
        "sudo_policy": "NOT_AUDITED",
        "inherited_file_descriptors": "NOT_AUDITED",
        "other_privileged_helpers": "NOT_AUDITED",
        "user_namespace_host_mapping": "NOT_AUDITED",
        "docker_daemon_rootfulness": "NOT_AUDITED",
        "acl_lsm_socket_rights": "NOT_AUDITED",
        "independent_host_review": "REQUIRED",
        "m12_regression": "NOT_RUN",
        "activation_authorized": False,
        "privilege_separation_verified": False,
        "host_modified": False,
    }


def collect() -> dict:
    """Observes the current process only. No external commands or mutations."""
    if sys.platform != "linux":
        raise PrivilegePreflightDenied("LINUX_REQUIRED")
    with PROC_STATUS.open("rb") as stream:
        raw = stream.read(MAX_STATUS_BYTES + 1)
    try:
        sock = DOCKER_SOCKET.lstat()
        opaque = stat.S_ISLNK(sock.st_mode)
    except FileNotFoundError:
        sock = None
        opaque = False
    except OSError:
        sock = None
        opaque = True
    return evaluate(
        raw, euid=os.geteuid(), egid=os.getegid(),
        supplementary_groups=tuple(os.getgroups()),
        docker_socket_stat=None if opaque else sock,
        socket_unobservable=opaque,
    )


def main() -> int:
    try:
        result = collect()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (PrivilegePreflightDenied, OSError) as exc:
        code = (str(exc) if isinstance(exc, PrivilegePreflightDenied)
                else "HOST_READ_FAILED")
        print(json.dumps({"status": "SELF_PRIVILEGE_PREFLIGHT_BLOCKED",
                          "reason": code, "activation_authorized": False,
                          "privilege_separation_verified": False},
                         sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
