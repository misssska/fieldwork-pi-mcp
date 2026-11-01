"""Read-only, content-addressed private FieldWork canary stage inspection.

A stage may be used by a later sandbox test runner ONLY after this whole-tree
check passes. An interrupted materialization has no final receipt and is denied.
The caller may only use a transfer ID, never a path or shell command.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from . import artifact_inbox as inbox
from . import canary_archive_qualifier as q

STAGE_NAME = "canary-stage-workspaces"
RECEIPT = "STAGE_RECEIPT.json"
MAX_FILES = 2600
MAX_BYTES = 110 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024
EXPECTED = frozenset({
    "schema", "status", "transfer_id", "archive_sha256",
    "base_commit", "overlay_plan_sha256", "changed_paths",
    "snapshot_file_count", "snapshot_total_bytes",
    "snapshot_tree_sha256", "tests_run", "canary_started",
    "production_modified"
})


def _own_dir(folder: Path, *, private: bool = False) -> None:
    q.require(folder.is_dir() and not folder.is_symlink(),
              "STAGE_DIRECTORY_UNSAFE")
    st = folder.stat()
    q.require(st.st_uid == os.geteuid() and
              (stat.S_IMODE(st.st_mode) & (0o077 if private else 0o022)) == 0,
              "STAGE_DIRECTORY_PERMISSIONS_DENIED")


def _own_file(path: Path, maximum: int) -> bytes:
    q.require(path.is_file() and not path.is_symlink(),
              "STAGE_FILE_UNSAFE")
    info = path.stat()
    q.require(info.st_uid == os.geteuid() and
              stat.S_IMODE(info.st_mode) & 0o077 == 0 and
              0 <= info.st_size <= maximum, "STAGE_FILE_PERMISSIONS_OR_SIZE")
    return path.read_bytes()


def snapshot_signature(root: Path) -> dict:
    """Hash all source file paths, sizes and SHA256, excluding the receipt."""
    _own_dir(root, private=True)
    records: list[tuple[str, int, str]] = []
    total = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        _own_dir(current_path, private=True)
        for name in dirs:
            _own_dir(current_path / name, private=True)
        for name in files:
            p = current_path / name
            rel = p.relative_to(root).as_posix()
            if rel == RECEIPT:
                continue
            info = p.lstat()
            q.require(stat.S_ISREG(info.st_mode) and
                      info.st_uid == os.geteuid() and
                      stat.S_IMODE(info.st_mode) & 0o077 == 0,
                      "STAGE_SOURCE_UNSAFE")
            q.require(info.st_size <= MAX_FILE, "STAGE_SOURCE_TOO_LARGE")
            total += info.st_size
            q.require(total <= MAX_BYTES, "STAGE_SOURCE_TOTAL_TOO_LARGE")
            q.require(len(records) < MAX_FILES, "STAGE_TOO_MANY_FILES")
            hashed = hashlib.sha256()
            with p.open("rb") as stream:
                for chunk in iter(lambda: stream.read(64 * 1024), b""):
                    hashed.update(chunk)
            q.require(p.stat().st_size == info.st_size, "STAGE_FILE_CHANGED_DURING_READ")
            records.append((rel, info.st_size, hashed.hexdigest()))
    records.sort()
    blob = json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode()
    return {
        "snapshot_tree_sha256": hashlib.sha256(blob).hexdigest(),
        "snapshot_file_count": len(records),
        "snapshot_total_bytes": total,
    }


def inspect_stage(transfer_id: str) -> dict:
    inbox._valid_id(transfer_id)
    q.require(os.geteuid() != 0, "ROOT_DENIED")
    base = Path.home()
    _own_dir(base)
    for piece in inbox.STATE.parent.parts:
        base = base / piece
        _own_dir(base)
    base = base / STAGE_NAME
    _own_dir(base, private=True)
    target = base / transfer_id
    _own_dir(target, private=True)
    receipt_bytes = _own_file(target / RECEIPT, 16 * 1024)
    try:
        receipt = json.loads(receipt_bytes)
    except (ValueError, UnicodeError) as exc:
        raise q.QualificationDenied("STAGE_RECEIPT_INVALID") from exc
    q.require(type(receipt) is dict and set(receipt) == EXPECTED and
              type(receipt.get("schema")) is int and receipt["schema"] == 1 and
              receipt["status"] == "STAGE_MATERIALIZED_NOT_TESTED" and
              receipt["transfer_id"] == transfer_id and
              receipt["tests_run"] is False and
              receipt["canary_started"] is False and
              receipt["production_modified"] is False,
              "STAGE_RECEIPT_SCHEMA_DENIED")
    observed = snapshot_signature(target)
    for name in ("snapshot_tree_sha256", "snapshot_file_count", "snapshot_total_bytes"):
        q.require(receipt[name] == observed[name], "STAGE_CONTENT_DRIFT:" + name)
    return {
        "status": "STAGE_VERIFIED_NOT_TESTED",
        "transfer_id": transfer_id,
        "base_commit": receipt["base_commit"],
        **observed,
        "tests_run": False,
        "canary_started": False,
        "production_modified": False,
    }
