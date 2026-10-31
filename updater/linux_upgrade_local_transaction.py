"""M14 local-only, fail-closed MCP source transaction (Linux).

NOT an MCP tool. Runs exclusively inside a separately privileged local
approver/installer context, never as a remote tool handler. The caller supplies
a locally configured destination and an isolated local approval secret, plus
a fixed service health hook; neither comes from the remote request.

Safe against ordinary exceptions and interrupted writes by durable backups
and a recovery operation. Sudden power loss requires invoking recover()
before any further updates. Does not run, import or execute supplied modules.
"""
from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Callable

if __package__:
    from . import linux_upgrade_gate as gate
else:
    import linux_upgrade_gate as gate

MAX_SOURCE = 256 * 1024
MAX_LEDGER = 16384
RECEIPT = "receipt.json"
SOURCE_FILE = "plan.json"


class LocalApplyDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise LocalApplyDenied(code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def directory(path: Path) -> None:
    require(isinstance(path, Path) and path.is_absolute()
            and path.is_dir() and not path.is_symlink(),
            "LOCAL_ROOT_INVALID")
    s = path.stat()
    require(s.st_uid == os.geteuid() and
            stat.S_IMODE(s.st_mode) == 0o700,
            "LOCAL_ROOT_PERMISSIONS_DENIED")


def fixed_read(root: Path, name: str) -> bytes | None:
    require(type(name) is str and
            (gate.MODULE.fullmatch(name) is not None or
             name == RECEIPT), "LOCAL_MODULE_NAME_DENIED")
    directory(root)
    path = root / name
    require(not path.is_symlink(), "LOCAL_MODULE_SYMLINK_DENIED")
    if not path.exists():
        return None
    require(path.is_file(), "LOCAL_MODULE_NOT_REGULAR")
    s = path.stat()
    require(s.st_uid == os.geteuid() and
            not (stat.S_IMODE(s.st_mode) & 0o077) and
            0 < s.st_size <= MAX_SOURCE,
            "LOCAL_MODULE_MODE_OR_SIZE_DENIED")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as f:
            data = f.read(MAX_SOURCE + 1)
    except OSError as exc:
        raise LocalApplyDenied("LOCAL_SOURCE_READ_FAILED") from exc
    require(len(data) == s.st_size, "LOCAL_MODULE_CHANGED_DURING_READ")
    return data


def sync(root: Path) -> None:
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_atomic(root: Path, name: str, data: bytes,
                 *, create: bool = False) -> None:
    directory(root)
    require(type(name) is str and
            (gate.MODULE.fullmatch(name) is not None or
             name in {RECEIPT, SOURCE_FILE}),
            "LOCAL_ATOMIC_FILENAME_DENIED")
    require(type(data) is bytes and
            0 < len(data) <= MAX_SOURCE, "LOCAL_ATOMIC_SIZE_DENIED")
    target = root / name
    require(not target.is_symlink() and
            (not create or not target.exists()),
            "LOCAL_ATOMIC_TARGET_COLLISION")
    fd, temp_name = tempfile.mkstemp(dir=root, prefix=".m14-")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        temp.chmod(0o600)
        if create:
            os.link(temp, target, follow_symlinks=False)
            temp.unlink()
        else:
            os.replace(temp, target)
        sync(root)
    finally:
        if temp.exists():
            temp.unlink()


def _locked_file(state_root: Path) -> int:
    directory(state_root)
    lock = state_root / "upgrade.lock"
    require(not lock.is_symlink(), "LOCAL_LOCK_SYMLINK_DENIED")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and
                stat.S_IMODE(st.st_mode) == 0o600,
                "LOCAL_LOCK_PERMISSIONS_DENIED")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except Exception:
        os.close(fd)
        raise


def _release(fd: int) -> None:
    os.close(fd)


def _active(root: Path, policy: gate.HostPolicy) -> dict:
    return {name: (sha(b) if (b := fixed_read(root, name)) is not None else None)
            for name in policy.allowed_modules}


def _receipt(txn: Path, body: dict, *, create: bool = False) -> None:
    write_atomic(txn, RECEIPT,
                 gate.canon(body) + b"\n", create=create)


def _journal_read(txn: Path) -> dict:
    directory(txn)
    data = fixed_read(txn, RECEIPT)
    require(data is not None and len(data) <= MAX_LEDGER,
            "LOCAL_JOURNAL_MISSING")
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise LocalApplyDenied("LOCAL_JOURNAL_INVALID") from exc
    require(type(obj) is dict and
            set(obj) == {"status", "host_id", "plan_sha256", "files",
                         "nonce", "production_modified"} and
            type(obj["files"]) is list and
            type(obj["nonce"]) is str,
            "LOCAL_JOURNAL_SCHEMA_DENIED")
    return obj


def _restore(root: Path, txn: Path, journal: dict,
             policy: gate.HostPolicy,
             health_check: Callable[[], bool]) -> None:
    require(journal["host_id"] == policy.host_id,
            "LOCAL_RESTORE_HOST_MISMATCH")
    rows = journal["files"]
    require(0 < len(rows) <= gate.MAX_FILES,
            "LOCAL_RESTORE_FILE_COUNT_DENIED")
    for row in rows:
        require(type(row) is dict and
                set(row) == {"name", "action", "old_sha256", "new_sha256"},
                "LOCAL_RESTORE_SCHEMA_DENIED")
        name = row["name"]
        require(type(name) is str and
                name in policy.allowed_modules and
                name not in policy.locked_modules,
                "LOCAL_RESTORE_SCOPE_DENIED")
        current = fixed_read(root, name)
        current_sha = sha(current) if current is not None else None
        if row["action"] == "replace":
            require(current_sha in (row["old_sha256"],
                                    row["new_sha256"]),
                    "LOCAL_RESTORE_FOREIGN_CHANGE_DENIED")
            original = fixed_read(txn, name)
            require(original is not None and
                    sha(original) == row["old_sha256"],
                    "LOCAL_RESTORE_BACKUP_INVALID")
            write_atomic(root, name, original)
        else:
            require(row["action"] == "create" and
                    row["old_sha256"] is None and
                    current_sha in (None, row["new_sha256"]),
                    "LOCAL_RESTORE_UNEXPECTED_CREATE")
            if current is not None:
                (root / name).unlink()
                sync(root)
    require(health_check() is True, "LOCAL_RESTORE_HEALTH_FAILED")
    journal["status"] = "ROLLED_BACK"
    _receipt(txn, journal)


def apply_approved(request: dict, policy: gate.HostPolicy,
                   *, install_root: Path, state_root: Path,
                   source_bytes: dict[str, bytes],
                   approval: dict, local_secret: bytes,
                   now: int, health_check: Callable[[], bool]) -> dict:
    """Local trusted process only, caller must separately verify release trust."""
    directory(install_root)
    directory(state_root)
    require(install_root != state_root,
            "LOCAL_INSTALL_STATE_OVERLAP_DENIED")
    lock_fd = _locked_file(state_root)
    try:
        plan = gate.validate_plan(
            request, policy, _active(install_root, policy), now,
        )
        require(type(source_bytes) is dict and
                set(source_bytes) == {x["name"] for x in plan.files},
                "LOCAL_PAYLOAD_FILE_SET_DENIED")
        for row in plan.files:
            payload = source_bytes[row["name"]]
            require(type(payload) is bytes and
                    0 < len(payload) <= MAX_SOURCE and
                    sha(payload) == row["new_sha256"],
                    "LOCAL_PAYLOAD_SHA256_DENIED")
            try:
                ast.parse(payload, filename=row["name"])
                compile(payload, row["name"], "exec")
            except (SyntaxError, UnicodeError, ValueError) as exc:
                raise LocalApplyDenied("LOCAL_PAYLOAD_PYTHON_DENIED") from exc
        spent = state_root / "spent"
        directory(spent)
        nonce = gate.verify_local_approval(
            plan, approval, local_secret=local_secret,
            now=now,
            spent_nonces=frozenset(x.name for x in spent.iterdir())
        )
        txn = state_root / plan.plan_sha256
        require(not txn.exists() and not txn.is_symlink(),
                "LOCAL_TRANSACTION_REPLAY_DENIED")

        # Save recoverable old bytes and validated plan BEFORE changing MCP.
        txn.mkdir(mode=0o700)
        directory(txn)
        write_atomic(txn, SOURCE_FILE, gate.canon(request), create=True)
        for row in plan.files:
            if row["action"] == "replace":
                original = fixed_read(install_root, row["name"])
                require(original is not None and
                        sha(original) == row["old_sha256"],
                        "LOCAL_SOURCE_CHANGED_BEFORE_BACKUP")
                write_atomic(txn, row["name"], original, create=True)
        journal = {
            "status": "PREPARED", "host_id": policy.host_id,
            "plan_sha256": plan.plan_sha256,
            "files": [dict(x) for x in plan.files],
            "nonce": nonce, "production_modified": False,
        }
        _receipt(txn, journal, create=True)

        marker = spent / nonce
        require(not marker.exists() and not marker.is_symlink(),
                "LOCAL_NONCE_REPLAY_DENIED")
        spent_fd = os.open(
            marker,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.close(spent_fd)
        sync(spent)
        try:
            journal["status"] = "APPLYING"
            _receipt(txn, journal)
            # Re-check under lock before each file. Never overwrite foreign drift.
            for row in plan.files:
                current = fixed_read(install_root, row["name"])
                observed = sha(current) if current is not None else None
                require(observed == row["old_sha256"],
                        "LOCAL_SOURCE_CHANGED_BEFORE_WRITE")
                write_atomic(install_root, row["name"],
                             source_bytes[row["name"]],
                             create=(row["action"] == "create"))
            require(health_check() is True, "LOCAL_HEALTH_CHECK_FAILED")
            journal["status"] = "APPLIED"
            _receipt(txn, journal)
        except Exception:
            _restore(install_root, txn, journal, policy, health_check)
            raise
        return {
            "status": "LOCAL_APPROVED_FILES_APPLIED",
            "host_id": policy.host_id,
            "plan_sha256": plan.plan_sha256,
            "changed_modules": [x["name"] for x in plan.files],
            "production_modified": False,
            "remote_shell_executed": False,
        }
    finally:
        _release(lock_fd)


def recover_unfinished(plan_sha256: str, policy: gate.HostPolicy,
                       *, install_root: Path, state_root: Path,
                       health_check: Callable[[], bool]) -> dict:
    """Local-only crash recovery; never runs remotely or reads secret."""
    require(type(plan_sha256) is str and
            gate.HEX64.fullmatch(plan_sha256) is not None,
            "LOCAL_RECOVERY_DIGEST_INVALID")
    directory(install_root)
    directory(state_root)
    fd = _locked_file(state_root)
    try:
        txn = state_root / plan_sha256
        journal = _journal_read(txn)
        require(journal["plan_sha256"] == plan_sha256 and
                journal["status"] in {"PREPARED", "APPLYING"},
                "LOCAL_RECOVERY_NOT_PENDING")
        _restore(install_root, txn, journal, policy, health_check)
        return {
            "status": "LOCAL_ROLLBACK_RESTORED",
            "host_id": policy.host_id,
            "plan_sha256": plan_sha256,
            "production_modified": False,
        }
    finally:
        _release(fd)
