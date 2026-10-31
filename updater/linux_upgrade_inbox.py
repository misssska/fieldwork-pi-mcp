"""M14: restricted immutable update request inbox for generic Linux MCP.

The MCP-facing side MAY call submit/status; it CANNOT approve or execute.
Only SHA256-identified metadata is stored. Artifact bytes/source code,
shell commands, secrets and arbitrary absolute paths are not accepted.
The approval secret is never read by this component.

Caller supplies an already-existing locally configured private directory
(not a user/request path). Directory owner & mode enforced.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

if __package__:
    from . import linux_upgrade_gate as gate
else:
    import linux_upgrade_gate as gate

MAX_DATA = 16384
SHA = re.compile(r"[0-9a-f]{64}\Z")


class InboxDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise InboxDenied(code)


def _secure_directory(root: Path) -> None:
    require(isinstance(root, Path) and root.is_absolute()
            and root.is_dir() and not root.is_symlink(),
            "UPGRADE_INBOX_ROOT_INVALID")
    state = root.stat()
    require(state.st_uid == os.geteuid()
            and stat.S_IMODE(state.st_mode) == 0o700,
            "UPGRADE_INBOX_PERMISSIONS_DENIED")


def _sync(root: Path) -> None:
    fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _store_exact(root: Path, name: str, data: bytes) -> bool:
    require(type(name) is str and SHA.fullmatch(name) is not None,
            "UPGRADE_FILENAME_DENIED")
    require(type(data) is bytes and 0 < len(data) <= MAX_DATA,
            "UPGRADE_CONTENT_BOUNDS_DENIED")
    _secure_directory(root)
    target = root / (name + ".json")
    require(not target.is_symlink(), "UPGRADE_TARGET_SYMLINK_DENIED")
    if target.exists():
        # Replay of an identical candidate is safe: no mutable overwrite.
        require(_read_exact(root, name) == data,
                "UPGRADE_REPLAY_CONTENT_MISMATCH")
        return False
    fd, tmp_name = tempfile.mkstemp(prefix=".m14-", dir=root)
    temp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(0o600)
        try:
            os.link(temp, target, follow_symlinks=False)
        except FileExistsError:
            require(_read_exact(root, name) == data,
                    "UPGRADE_RACE_CONTENT_MISMATCH")
            return False
        _sync(root)
        return True
    finally:
        if temp.exists():
            temp.unlink()


def _read_exact(root: Path, name: str) -> bytes:
    require(type(name) is str and SHA.fullmatch(name) is not None,
            "UPGRADE_FILENAME_DENIED")
    _secure_directory(root)
    path = root / (name + ".json")
    require(path.is_file() and not path.is_symlink(),
            "UPGRADE_MISSING_OR_SYMLINK")
    s = path.stat()
    require(s.st_uid == os.geteuid() and
            stat.S_IMODE(s.st_mode) == 0o600 and
            0 < s.st_size <= MAX_DATA,
            "UPGRADE_RECEIPT_PERMISSION_OR_SIZE_DENIED")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_DATA + 1)
    except OSError as exc:
        raise InboxDenied("UPGRADE_RECEIPT_READ_FAILED") from exc
    require(0 < len(data) <= MAX_DATA and len(data) == s.st_size,
            "UPGRADE_RECEIPT_CHANGED_OR_OVERSIZED")
    return data


@dataclass(frozen=True)
class ProposalInbox:
    root: Path
    policy: gate.HostPolicy

    def submit(self, request: dict, *, active_hashes: dict,
               now: int) -> dict:
        """Only immutable metadata, not source; no activation possible."""
        _secure_directory(self.root)
        plan = gate.validate_plan(request, self.policy, active_hashes, now)
        blob = gate.canon(request)
        require(len(blob) <= MAX_DATA, "UPGRADE_PROPOSAL_TOO_LARGE")
        added = _store_exact(self.root, plan.plan_sha256, blob)
        info = gate.approval_display(plan)
        info["status"] = ("UPGRADE_REQUEST_STAGED" if added
                          else "UPGRADE_REQUEST_ALREADY_STAGED")
        info["activation_authorized"] = False
        info["source_bytes_written"] = False
        return info

    def status(self, plan_sha256: str, *, active_hashes: dict,
               now: int) -> dict:
        blob = _read_exact(self.root, plan_sha256)
        try:
            request = json.loads(blob.decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise InboxDenied("UPGRADE_STORED_MANIFEST_INVALID") from exc
        require(gate.canon(request) == blob,
                "UPGRADE_NONCANONICAL_STORED_REQUEST")
        plan = gate.validate_plan(request, self.policy, active_hashes, now)
        require(plan.plan_sha256 == plan_sha256,
                "UPGRADE_STORED_DIGEST_MISMATCH")
        answer = gate.approval_display(plan)
        answer["status"] = "UPGRADE_REQUEST_AWAITING_LOCAL_APPROVAL"
        answer["activation_authorized"] = False
        return answer
