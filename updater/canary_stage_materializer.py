"""Materialize a verified canary overlay into a private, immutable Git snapshot.

NO installation, production writes, Docker or execution. The authoritative
base is a separately pinned, owner-private Git checkout, never /opt/fieldwork.
The release directory is dedicated to one 32-hex transfer ID; it is created
exclusively, uses 0700/0600 and is never overwritten. If interrupted, its
missing receipt permanently fails closed pending separately reviewed cleanup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from . import artifact_inbox as inbox
from . import canary_git_base as gitbase
from . import canary_archive_qualifier as q
from . import canary_change_planner as planner
from . import canary_stage_inspect as inspect

STAGE_NAME = "canary-stage-workspaces"
MAX_TREE_ENTRIES = 2500
MAX_TREE_BYTES = 80 * 1024 * 1024
MAX_TREE_BLOB = 4 * 1024 * 1024
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
SEGMENT = re.compile(r"[A-Za-z0-9_.@+-]{1,100}\Z")
PROHIBITED_EXACT = frozenset({".git", ".gitmodules", ".env", ".env.local",
                              ".env.production", ".npmrc", "id_rsa"})
PROHIBITED_SUFFIXES = (".pem", ".p12", ".pfx", ".key", ".crt", ".sqlite", ".db")


def _segments(path: str) -> tuple[str, ...]:
    q.require(type(path) is str and len(path) < 300 and
              not any(c in path for c in ("\x00", "\\", "\r", "\n")),
              "GIT_TREE_PATH_INVALID")
    parts = tuple(path.split("/"))
    q.require(1 <= len(parts) <= 12 and all(
        SEGMENT.fullmatch(part) is not None and
        part not in (".", "..") and
        part not in PROHIBITED_EXACT and
        not part.startswith(".") and
        not part.lower().endswith(PROHIBITED_SUFFIXES)
        for part in parts
    ), "GIT_TREE_PATH_DENIED")
    return parts


# File categories not required for the isolated source test snapshot.
# They are listed by Git, validated for unsafe object mode, and then OMITTED.
# Do not copy repository-maintenance workflows into the test filesystem.
OMIT_TOP_LEVEL = frozenset({"docs", "reference"})
OMIT_EXACT = frozenset({".gitignore", ".gitattributes", ".editorconfig",
                       ".env.example", ".dockerignore", "README.md",
                       "LICENSE", "LICENSE.md"})
OMIT_LOCAL_META = frozenset({".gitignore", ".gitattributes", ".editorconfig",
                             ".dockerignore", ".env.example"})
INCLUDE_TOP_LEVEL = frozenset({"frontend", "server", "nginx", "scripts"})
INCLUDE_ROOT = frozenset({"docker-compose.yml", "docker-compose.test.yml",
                          "docker-compose.override.yml", "docker-compose.e2e.yml"})


def _source_policy(path: str) -> str:
    """Return INCLUDE or OMIT only for explicitly known, inert Git metadata.

    Unknown paths and potential secrets fail closed, rather than silently
    disappearing from a release. All Git object modes are checked separately
    even when an allowed metadata file is omitted.
    """
    q.require(type(path) is str and len(path) < 300 and
              "\x00" not in path and "\\" not in path,
              "GIT_TREE_PATH_INVALID")
    if path.startswith(".github/") and len(path.split("/")) >= 3:
        # Metadata is omitted but its name must still be a safe Git path.
        q.require(all(SEGMENT.fullmatch(p) is not None and p not in (".", "..")
                      for p in path.split("/")),
                  "GIT_METADATA_PATH_DENIED")
        return "OMIT"
    if path in OMIT_EXACT or any(
        path.startswith(name + "/") for name in OMIT_TOP_LEVEL
    ):
        return "OMIT"
    parts = path.split("/")
    # Tooling metadata can occur inside frontend/server as well.
    if len(parts) >= 2 and parts[0] in INCLUDE_TOP_LEVEL and \
            parts[-1] in OMIT_LOCAL_META:
        return "OMIT"
    if path in INCLUDE_ROOT:
        return "INCLUDE"
    if path.split("/")[0] in INCLUDE_TOP_LEVEL:
        _segments(path)
        return "INCLUDE"
    # Hidden secrets, unexpected root files, unknown future subtrees.
    raise q.QualificationDenied("GIT_UNREVIEWED_PATH_DENIED")


def _tree(repo: Path, sha: str) -> list[tuple[str, str, int]]:
    """List exact regular blobs without traversing the worktree."""
    q.require(type(sha) is str and HEX40.fullmatch(sha) is not None,
              "BASE_COMMIT_INVALID")
    raw = gitbase._git(repo, "ls-tree", "-rz", "-l", "--full-tree", sha,
                       max_output=512_000)
    records = raw.split(b"\x00")
    q.require(bool(records) and records[-1] == b"",
              "GIT_TREE_LIST_INVALID")
    entries = records[:-1]
    q.require(0 < len(entries) <= MAX_TREE_ENTRIES,
              "GIT_TREE_COUNT_DENIED")
    total = 0
    seen = set()
    result = []
    for record in entries:
        try:
            header, path_bytes = record.split(b"\t", 1)
            mode, kind, object_id, size_text = header.decode("ascii").split()
            path = path_bytes.decode("utf-8", "strict")
            size = int(size_text)
        except (ValueError, UnicodeError) as exc:
            raise q.QualificationDenied("GIT_TREE_RECORD_INVALID") from exc
        q.require(path not in seen, "DUPLICATE_GIT_TREE_PATH")
        seen.add(path)
        # Validate object type BEFORE metadata omission: never hide symlinks
        # or submodules behind an ignored folder.
        q.require(mode in ("100644", "100755") and kind == "blob" and
                  HEX40.fullmatch(object_id) is not None,
                  "GIT_TREE_SPECIAL_FILE_DENIED")
        decision = _source_policy(path)
        if decision == "OMIT":
            continue
        q.require(0 <= size <= MAX_TREE_BLOB, "GIT_TREE_FILE_SIZE_DENIED")
        total += size
        q.require(total <= MAX_TREE_BYTES, "GIT_TREE_TOTAL_SIZE_DENIED")
        result.append((path, object_id, size))
    q.require([p for p, _, _ in result] == sorted(p for p, _, _ in result),
              "GIT_TREE_ORDER_DENIED")
    return result


def _destination(transfer_id: str) -> Path:
    inbox._valid_id(transfer_id)
    parent = inbox._dir().parent
    q.require(parent.is_dir() and not parent.is_symlink(),
              "STAGE_PARENT_UNSAFE")
    base = parent / STAGE_NAME
    q.require(not base.is_symlink(), "STAGE_ROOT_SYMLINK")
    if not base.exists():
        try:
            base.mkdir(mode=0o700)
        except FileExistsError:
            pass
    q.require(base.is_dir() and not base.is_symlink(),
              "STAGE_ROOT_UNSAFE")
    st = base.stat()
    q.require(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) & 0o077 == 0,
              "STAGE_ROOT_PERMISSIONS_DENIED")
    return base / transfer_id


def _write(root: Path, path: str, raw: bytes) -> None:
    parts = _segments(path)
    parent = root
    for name in parts[:-1]:
        parent = parent / name
        if not parent.exists():
            parent.mkdir(mode=0o700)
        q.require(parent.is_dir() and not parent.is_symlink(),
                  "STAGE_DIRECTORY_UNSAFE")
    target = parent / parts[-1]
    q.require(not target.exists() and not target.is_symlink(),
              "STAGE_FILE_COLLISION")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def materialize_transfer(transfer_id: str) -> dict:
    """Create an *unexecuted* private stage from a strictly verified upload."""
    inbox._valid_id(transfer_id)
    transfer = inbox._transfer(transfer_id)
    lock_fd = inbox._lock(transfer)
    try:
        record = inbox._record(transfer)
        raw_path, count, state = inbox._content_state(transfer, record)
        q.require(state == "VERIFIED" and count == record["size"],
                  "TRANSFER_NOT_VERIFIED")
        package = inbox._owned_file(raw_path, max_size=q.MAX_ARCHIVE)
        archive_hash = record["sha256"]
        prepared = gitbase.preflight(package, archive_hash)
        repo = gitbase.fixed_checkout()
        # Source must remain stable from all relevant previous Git checks.
        actual_head = gitbase._git(repo, "rev-parse", "--verify",
                                   "HEAD^{commit}", max_output=128).decode().strip()
        q.require(actual_head == prepared.receipt["base_commit"],
                  "BASE_CHANGED_BEFORE_MATERIALIZE")
        files = _tree(repo, actual_head)
        snapshot = _destination(transfer_id)
        q.require(not snapshot.exists() and not snapshot.is_symlink(),
                  "STAGE_ALREADY_EXISTS_OR_PARTIAL")
        snapshot.mkdir(mode=0o700)  # exclusive; interrupted stages remain blocked
        total = 0
        for name, oid, expected_size in files:
            data = gitbase._git(repo, "cat-file", "blob", oid,
                                max_output=MAX_TREE_BLOB)
            q.require(len(data) == expected_size,
                      "GIT_SNAPSHOT_BLOB_SIZE_DRIFT")
            replacement = prepared.files.get(name)
            _write(snapshot, name, data if replacement is None else replacement)
            total += len(data if replacement is None else replacement)
        base_paths = {p for p, _, _ in files}
        for name, replacement in sorted(prepared.files.items()):
            if name not in base_paths:
                _write(snapshot, name, replacement)
                total += len(replacement)
        q.require(total <= MAX_TREE_BYTES + q.MAX_TOTAL,
                  "STAGE_MATERIALIZED_SIZE_DENIED")
        final_head = gitbase._git(repo, "rev-parse", "--verify",
                                  "HEAD^{commit}", max_output=128).decode().strip()
        q.require(final_head == actual_head, "BASE_CHANGED_DURING_MATERIALIZE")
        signature = inspect.snapshot_signature(snapshot)
        q.require(signature["snapshot_file_count"] == len(files) +
                  sum(name not in base_paths for name in prepared.files),
                  "SNAPSHOT_MEMBER_COUNT_DRIFT")
        q.require(signature["snapshot_total_bytes"] == total,
                  "SNAPSHOT_TOTAL_BYTES_DRIFT")
        receipt = {
            "schema": 1, "status": "STAGE_MATERIALIZED_NOT_TESTED",
            "transfer_id": transfer_id, "archive_sha256": archive_hash,
            "base_commit": actual_head,
            "overlay_plan_sha256": prepared.receipt["overlay_plan_sha256"],
            "changed_paths": prepared.receipt["changed_paths"],
            "snapshot_file_count": len(files) +
                sum(name not in base_paths for name in prepared.files),
            "snapshot_total_bytes": total,
            "snapshot_tree_sha256": signature["snapshot_tree_sha256"],
            "tests_run": False, "canary_started": False,
            "production_modified": False,
        }
        blob = (json.dumps(receipt, sort_keys=True,
                           separators=(",", ":")) + "\n").encode()
        # One-way success marker; never overwrite an existing receipt.
        _write(snapshot, "STAGE_RECEIPT.json", blob)
        inbox._sync_dir(snapshot)
        inbox._sync_dir(snapshot.parent)
        return receipt
    finally:
        os.close(lock_fd)
