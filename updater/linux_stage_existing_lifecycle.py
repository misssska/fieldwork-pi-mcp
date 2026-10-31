"""M14E staging *existing-container* lifecycle: constrained local-only prototype.

NOT an MCP handler, and NOT a replacement for stage_manager.compose up/down:
it can only start/stop exactly three existing and verified compose-labelled
stage containers. No create, delete, network, volume, image, exec, build,
compose, run or project-selecting argument is possible.

Required security boundary for deployment:
  - isolated, operator-authenticated local approver; remote MCP cannot sign
  - helper Docker membership is root-equivalent on ordinary rootful Docker
  - external code review, Pi OS privilege audit, split-UID acceptance, rollback
This module is intentionally NOT registered or installed on the Pi.
"""
from __future__ import annotations
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import subprocess
import time

PROJECT = "fieldwork-stage"
HOST = "fieldwork-pi"
SERVICES = ("api", "db", "nginx")
CONTAINER_NUMBER = "1"
DOCKER = "/usr/bin/docker"
DETAIL_FMT = ('{{.Id}}|{{.Name}}|'
              '{{index .Config.Labels "com.docker.compose.project"}}|'
              '{{index .Config.Labels "com.docker.compose.service"}}|'
              '{{index .Config.Labels "com.docker.compose.container-number"}}|'
              '{{.State.Status}}')
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
DOMAIN = b"LINUX_MCP_STAGE_EXISTING_V1"
MAX_OUTPUT = 2048
MAX_LIFETIME = 180
MAX_NOW = 4102444800
STATE_MODES = {"start": ("exited", "running"),
               "stop": ("running", "exited")}


class StageDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise StageDenied(code)


def canon(obj: object) -> bytes:
    try:
        blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError) as exc:
        raise StageDenied("STAGE_JSON_DENIED") from exc
    require(len(blob) <= 4096, "STAGE_JSON_TOO_LARGE")
    return blob


def _docker(argv: list[str], *, timeout: int = 15) -> str:
    """Fixed caller-owned argv; never accept an external raw command."""
    require(type(argv) is list and
            all(type(x) is str for x in argv) and
            2 <= len(argv) <= 7 and
            argv[0] == DOCKER and argv[1] == "container",
            "STAGE_DOCKER_ARGV_DENIED")
    verb = argv[2] if len(argv) > 2 else None
    if verb == "inspect":
        require(len(argv) == 6 and argv[3:5] == ["--format", DETAIL_FMT]
                and type(argv[5]) is str and
                (argv[5] in fixed_names() or HEX64.fullmatch(argv[5])),
                "STAGE_INSPECT_ARGV_DENIED")
    elif verb in ("start", "stop"):
        require(len(argv) == 4 and HEX64.fullmatch(argv[3]) is not None,
                "STAGE_MUTATION_ARGV_DENIED")
    else:
        raise StageDenied("STAGE_DOCKER_VERB_DENIED")
    require(type(timeout) is int and 1 <= timeout <= 30,
            "STAGE_DOCKER_TIMEOUT_DENIED")
    try:
        proc = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd="/",
            env={"PATH": "/usr/bin:/bin"},
            timeout=timeout, check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StageDenied("STAGE_DOCKER_QUERY_FAILED") from exc
    require(proc.returncode == 0 and
            len(proc.stdout) <= MAX_OUTPUT,
            "STAGE_DOCKER_EXIT_OR_OUTPUT_DENIED")
    try:
        return proc.stdout.decode("ascii").strip()
    except UnicodeError as exc:
        raise StageDenied("STAGE_DOCKER_ASCII_DENIED") from exc


def fixed_names() -> set[str]:
    return {f"{PROJECT}-{service}-1" for service in SERVICES}


def _parse_inspect(raw: str, service: str) -> dict:
    require(type(raw) is str and len(raw) <= MAX_OUTPUT and
            type(service) is str and service in SERVICES,
            "STAGE_INSPECT_SCHEMA_DENIED")
    parts = raw.split("|")
    require(len(parts) == 6, "STAGE_INSPECT_FIELDS_DENIED")
    cid, name, project, label_service, number, state = parts
    require(HEX64.fullmatch(cid) is not None and
            name == f"/{PROJECT}-{service}-1" and
            project == PROJECT and label_service == service and
            number == CONTAINER_NUMBER and
            state in ("running", "exited"),
            "STAGE_INSPECT_IDENTITY_DENIED")
    return {"service": service, "id": cid, "state": state}


def snapshot() -> list[dict]:
    """Inspect only exact names and Compose labels; never raw inspect/env."""
    rows = []
    for service in SERVICES:
        name = f"{PROJECT}-{service}-1"
        rows.append(_parse_inspect(_docker(
            [DOCKER, "container", "inspect", "--format", DETAIL_FMT, name]
        ), service))
    require(len({x["id"] for x in rows}) == len(SERVICES),
            "STAGE_DUPLICATE_CONTAINER_DENIED")
    return rows


def plan_action(action: str, *, now: int) -> dict:
    """Local, read-only plan bound to three exact IDs and initial states."""
    require(type(action) is str and action in STATE_MODES,
            "STAGE_ACTION_DENIED")
    require(type(now) is int and 0 <= now <= MAX_NOW,
            "STAGE_CLOCK_DENIED")
    observed = snapshot()
    expected, _ = STATE_MODES[action]
    require(all(x["state"] == expected for x in observed),
            "STAGE_NOT_ALL_CONTAINERS_IN_EXPECTED_STATE")
    return {
        "protocol": 1, "host_id": HOST, "project": PROJECT,
        "action": action, "issued_at": now,
        "expires_at": now + MAX_LIFETIME,
        "containers": observed,
    }


def validate_plan(plan: object, *, now: int, observe: bool = True) -> str:
    """Reconcile entire plan before any change, not just its textual fields."""
    require(type(plan) is dict and
            set(plan) == {"protocol", "host_id", "project", "action",
                          "issued_at", "expires_at", "containers"},
            "STAGE_PLAN_FIELDS_DENIED")
    action = plan["action"]
    require(type(plan["protocol"]) is int and plan["protocol"] == 1 and
            plan["host_id"] == HOST and plan["project"] == PROJECT and
            type(action) is str and action in STATE_MODES,
            "STAGE_PLAN_POLICY_DENIED")
    issued, expires = plan["issued_at"], plan["expires_at"]
    require(type(now) is int and 0 <= now <= MAX_NOW and
            type(issued) is int and type(expires) is int and
            0 <= issued <= now < expires <= min(issued + MAX_LIFETIME, MAX_NOW),
            "STAGE_PLAN_EXPIRED")
    rows = plan["containers"]
    require(type(rows) is list and len(rows) == len(SERVICES),
            "STAGE_PLAN_CONTAINER_COUNT_DENIED")
    for i, service in enumerate(SERVICES):
        row = rows[i]
        require(type(row) is dict and
                set(row) == {"service", "id", "state"} and
                row["service"] == service and
                type(row["id"]) is str and
                HEX64.fullmatch(row["id"]) is not None and
                row["state"] == STATE_MODES[action][0],
                "STAGE_PLAN_CONTAINER_DENIED")
    require(len({x["id"] for x in rows}) == len(SERVICES),
            "STAGE_PLAN_ID_COLLISION_DENIED")
    if observe:
        require(snapshot() == rows, "STAGE_CONTAINER_CHANGED_AFTER_REVIEW")
    return hashlib.sha256(DOMAIN + b"\0" + canon(plan)).hexdigest()


def issue_local_ticket(plan: dict, *, secret: bytes,
                       local_operator_present: bool, now: int,
                       nonce: str) -> dict:
    """For separate local approver only. Do NOT expose over MCP."""
    require(local_operator_present is True, "STAGE_LOCAL_OPERATOR_REQUIRED")
    require(type(secret) is bytes and len(secret) >= 32,
            "STAGE_SIGNING_KEY_DENIED")
    require(type(nonce) is str and HEX32.fullmatch(nonce) is not None,
            "STAGE_NONCE_DENIED")
    digest = validate_plan(plan, now=now, observe=True)
    fields = {"protocol": 1, "host_id": HOST, "plan_sha256": digest,
              "expires_at": min(plan["expires_at"], now + 120),
              "nonce": nonce}
    mac = hmac.new(secret, DOMAIN + b"\0APPROVAL\0" + canon(fields),
                   hashlib.sha256).hexdigest()
    return {**fields, "mac": mac}


def verify_ticket(plan: dict, ticket: object, *, secret: bytes,
                  now: int) -> str:
    require(type(secret) is bytes and len(secret) >= 32,
            "STAGE_VERIFY_KEY_DENIED")
    require(type(ticket) is dict and
            set(ticket) == {"protocol", "host_id", "plan_sha256",
                            "expires_at", "nonce", "mac"},
            "STAGE_TICKET_FIELDS_DENIED")
    digest = validate_plan(plan, now=now, observe=True)
    require(type(ticket["protocol"]) is int and ticket["protocol"] == 1 and
            ticket["host_id"] == HOST and ticket["plan_sha256"] == digest and
            type(ticket["expires_at"]) is int and
            now < ticket["expires_at"] <= plan["expires_at"] and
            ticket["expires_at"] <= now + 120 and
            type(ticket["nonce"]) is str and
            HEX32.fullmatch(ticket["nonce"]) is not None and
            type(ticket["mac"]) is str and
            HEX64.fullmatch(ticket["mac"]) is not None,
            "STAGE_TICKET_POLICY_DENIED")
    unsigned = {k: v for k, v in ticket.items() if k != "mac"}
    expected = hmac.new(secret, DOMAIN + b"\0APPROVAL\0" + canon(unsigned),
                        hashlib.sha256).hexdigest()
    require(hmac.compare_digest(ticket["mac"], expected),
            "STAGE_TICKET_MAC_DENIED")
    return ticket["nonce"]


def _secure_state(root: Path) -> None:
    require(isinstance(root, Path) and root.is_absolute() and
            root.is_dir() and not root.is_symlink(),
            "STAGE_STATE_ROOT_DENIED")
    st = root.stat()
    require(st.st_uid == os.geteuid() and
            stat.S_IMODE(st.st_mode) == 0o700,
            "STAGE_STATE_PERMISSIONS_DENIED")


def _new_file(root: Path, name: str, content: bytes) -> None:
    _secure_state(root)
    require(type(name) is str and HEX64.fullmatch(name) is not None and
            type(content) is bytes and 0 < len(content) <= 4096,
            "STAGE_RECEIPT_SCHEMA_DENIED")
    path = root / name
    require(not path.is_symlink() and not path.exists(),
            "STAGE_RECEIPT_REPLAY_DENIED")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    dirfd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _replace_receipt(root: Path, name: str, body: dict) -> None:
    """Durable atomic status write. Never unlink the consumed nonce."""
    _secure_state(root)
    require(type(name) is str and HEX64.fullmatch(name) is not None,
            "STAGE_RECEIPT_NAME_DENIED")
    path = root / name
    require(path.is_file() and not path.is_symlink(),
            "STAGE_RECEIPT_PATH_DENIED")
    fd, tmp_name = tempfile.mkstemp(prefix=".m14e-", dir=root)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(canon(body))
            file.flush()
            os.fsync(file.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, path)
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def _deny_unfinished(root: Path) -> None:
    """No further operation while prior crash/partial rollback is unresolved."""
    _secure_state(root)
    for path in root.iterdir():
        if not HEX64.fullmatch(path.name):
            continue
        require(path.is_file() and not path.is_symlink(),
                "STAGE_JOURNAL_PATH_DENIED")
        st = path.stat()
        require(st.st_uid == os.geteuid() and
                stat.S_IMODE(st.st_mode) == 0o600 and
                0 < st.st_size <= 4096,
                "STAGE_JOURNAL_MODE_DENIED")
        try:
            state = json.loads(path.read_bytes())
        except (ValueError, OSError) as exc:
            raise StageDenied("STAGE_JOURNAL_CORRUPT") from exc
        require(type(state) is dict and
                state.get("state") in {"COMMITTED", "ROLLED_BACK"},
                "STAGE_PENDING_MANUAL_RECOVERY")


def execute_approved(plan: dict, ticket: dict, *,
                     secret: bytes, state: Path, now: int) -> dict:
    """Local Docker helper only; no remote entrypoint or arbitrary operations.

    One-shot journal and nonce consumed before first Docker mutation.
    Rolls back changed container states best-effort on ordinary failures.
    Power-loss crash-recovery & persistent executor/service UI are NOT done.
    """
    require(os.geteuid() != 0, "STAGE_ROOT_EXECUTION_DENIED")
    _secure_state(state)
    fd = os.open(state / "lock", os.O_CREAT | os.O_RDWR |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and
                st.st_uid == os.geteuid() and
                stat.S_IMODE(st.st_mode) == 0o600,
                "STAGE_LOCK_PERMISSIONS_DENIED")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _deny_unfinished(state)
        nonce = verify_ticket(plan, ticket, secret=secret, now=now)
        digest = validate_plan(plan, now=now, observe=True)
        # Digest + nonce are linked; no privilege-bearing file path from caller.
        marker = hashlib.sha256(DOMAIN + nonce.encode()).hexdigest()
        _new_file(state, marker, canon({"plan": digest,
                                       "state": "PREPARED",
                                       "action": plan["action"]}))
        original, target = STATE_MODES[plan["action"]]
        attempted = []
        _replace_receipt(state, marker, {
            "plan": digest, "action": plan["action"], "state": "APPLYING"})
        try:
            for row in plan["containers"]:
                # The immutable full ID plus exact Compose labels and
                # pre-state must still match immediately before the action.
                got = _parse_inspect(_docker(
                    [DOCKER, "container", "inspect", "--format",
                     DETAIL_FMT, row["id"]]), row["service"])
                require(got == row, "STAGE_PRE_MUTATION_ID_OR_STATE_DRIFT")
                # Track BEFORE running Docker; a timeout can occur AFTER the
                # Docker daemon has already applied the requested change.
                attempted.append(row)
                _docker([DOCKER, "container", plan["action"], row["id"]],
                        timeout=30)
                observed = _parse_inspect(_docker(
                    [DOCKER, "container", "inspect", "--format",
                     DETAIL_FMT, row["id"]]), row["service"])
                require(observed["id"] == row["id"] and
                        observed["state"] == target,
                        "STAGE_POST_MUTATION_STATE_DENIED")
            require(snapshot() == [
                {**row, "state": target} for row in plan["containers"]
            ], "STAGE_FINAL_SNAPSHOT_DENIED")
        except Exception:
            # Best effort bounded rollback, with a durable UNCERTAIN state
            # on any failure. New approvals are blocked until reconciled.
            for row in reversed(attempted):
                try:
                    current = _parse_inspect(_docker(
                        [DOCKER, "container", "inspect", "--format",
                         DETAIL_FMT, row["id"]]), row["service"])
                    if current["id"] == row["id"] and current["state"] == target:
                        reverse = "start" if plan["action"] == "stop" else "stop"
                        _docker([DOCKER, "container", reverse, row["id"]],
                                timeout=30)
                except Exception:
                    pass
            try:
                restored = snapshot() == plan["containers"]
            except Exception:
                restored = False
            _replace_receipt(state, marker, {
                "plan": digest, "action": plan["action"],
                "state": "ROLLED_BACK" if restored else "ROLLBACK_UNCERTAIN"})
            raise StageDenied("STAGE_EXECUTION_FAILED_CHECK_LOCAL_STATE")
        _replace_receipt(state, marker, {
            "plan": digest, "action": plan["action"], "state": "COMMITTED"})
        return {
            "status": "STAGE_APPROVED_EXISTING_CONTAINERS_CHANGED",
            "project": PROJECT, "action": plan["action"],
            "changed_count": len(attempted), "plan_sha256": digest,
            "volume_deleted": False, "production_modified": False,
        }
    finally:
        os.close(fd)
