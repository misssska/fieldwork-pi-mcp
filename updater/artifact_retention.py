"""Explicit, SHA256-pinned retirement of verified inert FieldWork artifacts.

Never deletes a pending upload, a mismatched artifact or arbitrary host paths.
A durable tombstone is written BEFORE the payload directory is atomically
renamed. Interrupted cleanup can resume. No Docker, network or execution.
Only the local, private artifact inbox is writable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

if __package__:
    from . import artifact_inbox as inbox
else:
    import artifact_inbox as inbox

APPROVAL = "RETIRE_VERIFIED_CANARY"
FILES = frozenset({"record.json", "lock", "artifact.bin"})


def _tombstone(base: Path, tid: str) -> Path:
    return base / ("retired-" + tid + ".json")


def _retired_dir(base: Path, tid: str) -> Path:
    return base / (".retired-" + tid)


def _tomb_record(path: Path, tid: str, hash_value: str) -> dict:
    raw = inbox._owned_file(path, max_size=1024)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise inbox.InboxDenied("RETIRE_RECEIPT_CORRUPT") from exc
    inbox.require(type(data) is dict and set(data) == {
        "schema", "transfer_id", "sha256", "state"
    }, "RETIRE_RECEIPT_SCHEMA")
    inbox.require(data == {"schema": 1, "transfer_id": tid,
                          "sha256": hash_value, "state": "RETIRED"},
                  "RETIRE_RECEIPT_MISMATCH")
    return data


def _clean(directory: Path, base: Path) -> None:
    inbox.require(directory.is_dir() and not directory.is_symlink(),
                  "RETIRE_DIRECTORY_UNSAFE")
    st = directory.stat()
    inbox.require(st.st_uid == os.geteuid() and
                  stat.S_IMODE(st.st_mode) & 0o077 == 0,
                  "RETIRE_DIRECTORY_PERMISSIONS")
    names = {p.name for p in directory.iterdir()}
    inbox.require(names <= FILES, "RETIRE_UNEXPECTED_FILE")
    for name in sorted(names):
        p = directory / name
        inbox.require(p.is_file() and not p.is_symlink(),
                      "RETIRE_FILE_UNSAFE")
        info = p.stat()
        inbox.require(info.st_uid == os.geteuid() and
                      stat.S_IMODE(info.st_mode) & 0o077 == 0,
                      "RETIRE_FILE_PERMISSIONS")
        p.unlink()
    directory.rmdir()
    inbox._sync_dir(base)


def retire(transfer_id: str, expected_sha256: str, approval: str) -> dict:
    """Retire exactly one verified payload, with idempotent crash recovery."""
    inbox._valid_id(transfer_id)
    inbox.require(type(expected_sha256) is str and
                  inbox.HEX64.fullmatch(expected_sha256) is not None,
                  "EXPECTED_HASH_REQUIRED")
    inbox.require(approval == APPROVAL, "EXPLICIT_RETIRE_APPROVAL_REQUIRED")
    base = inbox._dir()
    tomb = _tombstone(base, transfer_id)
    held = _retired_dir(base, transfer_id)
    root = base / transfer_id

    if tomb.exists() or tomb.is_symlink():
        _tomb_record(tomb, transfer_id, expected_sha256)
        if held.exists() or held.is_symlink():
            _clean(held, base)
        elif root.exists() or root.is_symlink():
            fd = inbox._lock(root)
            try:
                record = inbox._record(root)
                path, _, state = inbox._content_state(root, record)
                inbox.require(state == "VERIFIED" and
                              record["sha256"] == expected_sha256,
                              "RETIRE_ACTIVE_STATE_CHANGED")
                inbox.require({p.name for p in root.iterdir()} == FILES,
                              "RETIRE_UNEXPECTED_FILE")
                os.replace(root, held)
                inbox._sync_dir(base)
            finally:
                os.close(fd)
            _clean(held, base)
        return {"status": "RETIRED", "transfer_id": transfer_id,
                "sha256": expected_sha256, "production_modified": False,
                "mcp_modified": False}

    inbox.require(not held.exists() and not held.is_symlink(),
                  "UNRECORDED_RETIRE_DIRECTORY_DENIED")
    root = inbox._transfer(transfer_id)
    fd = inbox._lock(root)
    try:
        record = inbox._record(root)
        path, _, state = inbox._content_state(root, record)
        inbox.require(state == "VERIFIED" and
                      record["sha256"] == expected_sha256,
                      "ONLY_VERIFIED_EXACT_ARTIFACT_CAN_RETIRE")
        inbox.require({p.name for p in root.iterdir()} == FILES,
                      "RETIRE_UNEXPECTED_FILE")
        proof = {"schema": 1, "transfer_id": transfer_id,
                 "sha256": expected_sha256, "state": "RETIRED"}
        inbox._write_exclusive(tomb, (json.dumps(proof, sort_keys=True) + "\n").encode())
        inbox._sync_dir(base)
        os.replace(root, held)
        inbox._sync_dir(base)
    finally:
        os.close(fd)
    _clean(held, base)
    return {"status": "RETIRED", "transfer_id": transfer_id,
            "sha256": expected_sha256, "production_modified": False,
            "mcp_modified": False}
