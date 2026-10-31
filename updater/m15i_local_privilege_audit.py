"""M15-I: independently launched LOCAL Linux MCP privilege evidence, never a cutover.

Run only via a separately trusted, local administrator. No MCP endpoint.
Discover bounded live processes and derive kernel PID/starttime/effective UID
from /proc; use M15-F for pinned identity and default Docker socket DAC.
Read fixed systemd unit metadata and sudo policy with fixed read-only commands.
No Docker CLI/API, no arbitrary shell, no chown/chmod/systemctl mutation,
no operator secret, no software install. Sudo/systemd may emit audit logs.

Discovery is NOT source attestation; process argv may be forged, sudo policy
is not a complete enumeration of privilege escalations, and a target's
Docker access is not revoked on any result.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys

if __package__:
    from . import linux_m15f_host_boundary_audit as m15f
    from . import linux_host_privilege_preflight as preflight
else:
    import linux_m15f_host_boundary_audit as m15f
    import linux_host_privilege_preflight as preflight

MAX_DISCOVERY = 16384
MAX_CANDIDATES = 32
MAX_CMDLINE = 8192
KNOWN_UNITS = (
    "fieldwork-pi-tunnel.service",
    "fieldwork-pi-mcp.service",
    "fieldwork-mcp.service",
)
INSTALLED_INACTIVE = Path("/opt/linux-mcp-operator")
MCP_SCRIPT = "fieldwork_mcp.py"


class M15IAuditDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise M15IAuditDenied(reason)


def is_mcp_script_argv(raw: bytes) -> bool:
    """Treat discovery as candidate selection ONLY, never identity proof."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_CMDLINE:
        return False
    args = raw.split(b"\0")
    if args[-1] == b"":
        args.pop()
    if not args or len(args) > 128:
        return False
    # Require a standalone path argument, not a substring in -c/script text.
    for i, arg in enumerate(args):
        if arg == b"-c" and i + 1 < len(args):
            return False
        if arg == b"-m" and i + 1 < len(args):
            return False
        if arg.decode("utf-8", errors="replace").rsplit("/", 1)[-1] == MCP_SCRIPT:
            return True
    return False


def _fixed_proc_file(pid: int, name: str, limit: int) -> bytes:
    require(type(pid) is int and 1 < pid <= m15f.MAX_PID
            and name in ("cmdline", "stat", "status")
            and limit in (MAX_CMDLINE, m15f.MAX_STAT, m15f.MAX_STATUS),
            "M15I_PROC_PATH_DENIED")
    path = Path("/proc") / str(pid) / name
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(fd, "rb") as handle:
            require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode),
                    "M15I_PROC_NOT_REGULAR")
            blob = handle.read(limit + 1)
    except OSError as exc:
        raise M15IAuditDenied("M15I_PROC_READ_DENIED") from exc
    require(0 < len(blob) <= limit, "M15I_PROC_SIZE_DENIED")
    return blob


def discover_candidate_pids() -> list[int]:
    """No caller-provided PID or command; bounded proc-only discovery."""
    require(Path("/proc").is_dir(), "M15I_PROCFS_REQUIRED")
    candidates = []
    inspected = 0
    with os.scandir("/proc") as records:
        for item in records:
            if not item.name.isascii() or not item.name.isdecimal():
                continue
            inspected += 1
            require(inspected <= MAX_DISCOVERY,
                    "M15I_TOO_MANY_PROCESSES_TO_AUDIT")
            pid = int(item.name)
            if not 1 < pid <= m15f.MAX_PID:
                continue
            try:
                cmdline = _fixed_proc_file(pid, "cmdline", MAX_CMDLINE)
            except (OSError, M15IAuditDenied):
                continue  # process exited during snapshot
            if is_mcp_script_argv(cmdline):
                candidates.append(pid)
                require(len(candidates) <= MAX_CANDIDATES,
                        "M15I_TOO_MANY_MCP_CANDIDATES")
    return sorted(set(candidates))


def read_unit_summary(name: str) -> dict:
    """Query only known unit names. Never show ExecStart, Environment or secrets."""
    require(name in KNOWN_UNITS, "M15I_UNIT_NOT_ALLOWLISTED")
    command = [
        "/usr/bin/systemctl", "show", "--no-pager",
        "--property=LoadState,ActiveState,MainPID,User,Group",
        name,
    ]
    if not Path(command[0]).is_file():
        return {"unit": name, "state": "SYSTEMCTL_NOT_AVAILABLE",
                "pid": 0, "user": "UNVERIFIED"}
    try:
        p = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=5, check=False,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"unit": name, "state": "UNIT_UNOBSERVABLE",
                "pid": 0, "user": "UNVERIFIED"}
    if p.returncode or len(p.stdout) > 4096:
        return {"unit": name, "state": "UNIT_UNOBSERVABLE",
                "pid": 0, "user": "UNVERIFIED"}
    d = {}
    try:
        for line in p.stdout.decode("ascii").splitlines():
            k, sep, v = line.partition("=")
            require(sep and k in {"LoadState", "ActiveState", "MainPID",
                                  "User", "Group"} and k not in d,
                    "M15I_UNIT_FIELDS_DENIED")
            d[k] = v
        require(set(d) == {"LoadState", "ActiveState", "MainPID",
                           "User", "Group"} and
                re.fullmatch(r"[0-9]{1,10}", d["MainPID"]) is not None,
                "M15I_UNIT_SCHEMA_DENIED")
        pid = int(d["MainPID"])
        require(pid <= m15f.MAX_PID, "M15I_UNIT_PID_INVALID")
    except (UnicodeError, M15IAuditDenied):
        return {"unit": name, "state": "UNIT_UNOBSERVABLE",
                "pid": 0, "user": "UNVERIFIED"}
    # Avoid echoing arbitrary User/Group content; these are local systemd data.
    return {"unit": name,
            "state": "ACTIVE" if d["ActiveState"] == "active" else "INACTIVE_OR_UNKNOWN",
            "pid": pid,
            "user": d["User"] if re.fullmatch(r"[a-z_][a-z_0-9-]{0,63}", d["User"]) else "UNVERIFIED"}


def sudo_policy_probe(uid: int) -> str:
    """Only a policy listing. No privilege escalation test, no raw output."""
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        return "UID_NO_LOCAL_PASSWD_ENTRY"
    if not re.fullmatch(r"[a-z_][a-z_0-9-]{0,63}", username):
        return "UID_NAME_UNVERIFIED"
    if not Path("/usr/bin/sudo").is_file():
        return "SUDO_BINARY_NOT_PRESENT"
    try:
        p = subprocess.run(
            ["/usr/bin/sudo", "-n", "-l", "-U", username],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=5, check=False,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return "SUDO_POLICY_UNVERIFIED"
    if p.returncode == 0:
        # Some sudo policies grant only limited verbs; either way do not cut over.
        return "SUDO_POLICY_LISTED_REVIEW_REQUIRED"
    return "SUDO_POLICY_UNVERIFIED"


def installed_m15e_snapshot() -> dict:
    """Never read secret keys, merely fixed installed source file/dir metadata."""
    base = INSTALLED_INACTIVE
    file = base / "linux_approval_redeemer.py"
    try:
        d = base.lstat()
        f = file.lstat()
    except FileNotFoundError:
        return {"status": "M15E_INACTIVE_NOT_PRESENT"}
    except OSError:
        return {"status": "M15E_INACTIVE_UNOBSERVABLE"}
    if not (stat.S_ISDIR(d.st_mode) and d.st_uid == 0
            and stat.S_IMODE(d.st_mode) == 0o755
            and stat.S_ISREG(f.st_mode) and f.st_uid == 0
            and stat.S_IMODE(f.st_mode) == 0o444):
        return {"status": "M15E_INACTIVE_OWNER_OR_MODE_DRIFT"}
    return {"status": "M15E_INACTIVE_FILE_OWNER_MODE_MATCH",
            "file_owner_uid": 0, "file_mode_octal": "444",
            "contents_and_publisher": "NOT_INDEPENDENTLY_VERIFIED"}


def assess_candidate(pid: int, *, units: list[dict]) -> dict:
    """Pin kernel PID-starttime before/after to detect basic PID reuse."""
    try:
        st = _fixed_proc_file(pid, "stat", m15f.MAX_STAT)
        start = m15f.starttime_from_stat(st, pid)
        status = _fixed_proc_file(pid, "status", m15f.MAX_STATUS)
        uids = preflight._parse_status(status)["uids"]
        report = m15f.collect_local(
            pid=pid, expected_uid=uids[1],
            expected_starttime=start)
    except (OSError, m15f.HostBoundaryDenied,
            preflight.PrivilegePreflightDenied, M15IAuditDenied):
        return {"pid": pid, "status": "M15I_TARGET_CHANGED_OR_UNOBSERVABLE",
                "privilege_separation_verified": False}
    groups = report["target"]["supplementary_gids"]
    try:
        docker_gid = grp.getgrnam("docker").gr_gid
    except KeyError:
        docker_gid = None
    dockergroup = (docker_gid is not None and
                   (docker_gid in groups or docker_gid ==
                    report["target"]["observed_effective_gid"]))
    binding = [
        x["unit"] for x in units if x["state"] == "ACTIVE"
        and x["pid"] == pid
    ]
    elevated = (report["default_docker_socket"] == "DAC_WRITE_POSSIBLE" or
                dockergroup or report["observed_capabilities_nonzero"] or
                report["target"]["observed_effective_uid"] == 0)
    return {
        "pid": pid,
        "kernel_starttime_ticks": start,
        "effective_uid": report["target"]["observed_effective_uid"],
        "effective_gid": report["target"]["observed_effective_gid"],
        "supplementary_gids": groups,
        "docker_group_membership_observed": dockergroup,
        "default_docker_socket": report["default_docker_socket"],
        "effective_capabilities_nonzero": report["observed_capabilities_nonzero"],
        "no_new_privileges": report["observed_no_new_privileges"],
        "sudo_policy": sudo_policy_probe(
            report["target"]["observed_effective_uid"]),
        "systemd_mainpid_match": binding,
        "root_equivalent_indicator_present": bool(elevated),
        "service_identity_independently_proven": False,
        "privilege_separation_verified": False,
        "safe_to_install_operator_secret": False,
        "safe_to_revoke_mcp_docker_access": False,
    }


def audit() -> dict:
    """Root-owned operator-only observer, not a remote MCP or installer."""
    require(sys.platform == "linux" and os.geteuid() == 0,
            "M15I_LOCAL_ROOT_AUDIT_REQUIRED")
    units = [read_unit_summary(name) for name in KNOWN_UNITS]
    candidates = discover_candidate_pids()
    reports = [assess_candidate(pid, units=units) for pid in candidates]
    # Fail-closed when no unambiguous MCP process was discovered.
    flag = any(x.get("root_equivalent_indicator_present")
               for x in reports)
    return {
        "status": "M15I_HOST_PRIVILEGE_EVIDENCE_INCOMPLETE",
        "scope": "LOCAL_READ_ONLY_ROOT_PROCESS_AUDIT",
        "candidate_count": len(reports),
        "mcp_process_candidates_from_untrusted_cmdline": reports,
        "fixed_systemd_units": units,
        "inactive_m15e": installed_m15e_snapshot(),
        "potential_root_equivalent_runtime": bool(flag),
        "sudo_policy_absence_verified": False,
        "acl_lsm_rootless_inherited_fd_absence_verified": False,
        "independent_mcp_binary_identity_verified": False,
        "production_services_mutated": False,
        "intentional_host_writes": False,
        "sudo_or_systemd_may_emit_system_audit_logs": True,
        "safe_to_revoke_legacy_docker_access": False,
        "safe_to_install_operator_secret": False,
        "safe_to_activate_service": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M15I LOCAL root read-only MCP privilege snapshot, never authorize")
    parser.add_argument("--audit", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        report = audit()
    except (M15IAuditDenied, OSError, ValueError) as exc:
        report = {
            "status": "M15I_HOST_AUDIT_DENIED",
            "reason": str(exc) if isinstance(exc, M15IAuditDenied)
                      else "READONLY_OBSERVATION_FAILURE",
            "safe_to_activate_service": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
