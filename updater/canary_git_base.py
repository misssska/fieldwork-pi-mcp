"""Read a verified *separate* Git checkout as the only canary base authority.

The current FieldWork production checkout is dirty and MUST NOT be used.
This module cannot receive a filesystem path from an MCP request. Its fixed
checkout is private to the MCP owner, outside /opt/fieldwork, and is never
modified by this module.

Git source reads are scoped to exact revision and source path, with hooks,
global config and optional file locks disabled. No checkout/reset/pull/clone.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess

from . import canary_archive_qualifier as q
from . import canary_change_planner as planner

BASE_REL = Path(".local/state/fieldwork-pi-mcp/canary-git-base")
MAX_GIT_STDOUT = 2 * 1024 * 1024 + 8192
HEX40 = re.compile(r"[a-f0-9]{40}\Z")


def _guarded_dir(path: Path) -> None:
    q.require(not path.is_symlink() and path.is_dir(),
              "GIT_BASE_DIRECTORY_UNSAFE")
    st = path.stat()
    q.require(st.st_uid == os.geteuid() and
              not (st.st_mode & 0o022), "GIT_BASE_OWNER_OR_MODE_DENIED")


def fixed_checkout() -> Path:
    q.require(os.geteuid() != 0, "ROOT_DENIED")
    home = Path.home()
    _guarded_dir(home)
    path = home
    for part in BASE_REL.parts:
        path = path / part
        _guarded_dir(path)
    q.require((path / ".git").is_dir() and not (path / ".git").is_symlink(),
              "GIT_BASE_NOT_REPO")
    _guarded_dir(path / ".git")
    return path


def _git(repo: Path, *args: str, max_output: int = MAX_GIT_STDOUT) -> bytes:
    q.require(isinstance(repo, Path) and not repo.is_symlink(),
              "GIT_REPOSITORY_UNSAFE")
    safe_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }
    argv = ["git", "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=/dev/null",
            "-c", "diff.external=",
            "-C", str(repo), "--no-optional-locks", *args]
    try:
        proc = subprocess.Popen(
            argv, env=safe_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        assert proc.stdout is not None
        output = proc.stdout.read(max_output + 1)
        if len(output) > max_output:
            proc.kill()
        code = proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise q.QualificationDenied("PINNED_GIT_COMMAND_FAILED") from exc
    q.require(len(output) <= max_output and code == 0,
              "PINNED_GIT_COMMAND_DENIED")
    return output


def base_file(repo: Path, sha: str, path: str) -> bytes | None:
    """Get a committed regular-file blob; missing files become explicit None."""
    q.require(q.allowed_path(path), "BASE_PATH_NOT_ALLOWED")
    q.require(type(sha) is str and HEX40.fullmatch(sha) is not None,
              "BASE_SHA_NOT_PINNED")
    raw = _git(repo, "ls-tree", "-z", "--full-tree", sha, "--", path,
               max_output=512)
    if not raw:
        return None
    # Mode must be regular (100644 / 100755). Deny submodules and symlinks.
    q.require(raw.count(b"\0") == 1 and raw.endswith(b"\0"),
              "GIT_TREE_ENTRY_AMBIGUOUS")
    try:
        header, filename = raw[:-1].split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split(" ")
    except (UnicodeError, ValueError) as exc:
        raise q.QualificationDenied("GIT_TREE_ENTRY_INVALID") from exc
    q.require(filename == path.encode("utf-8") and mode == "100644" and
              kind == "blob" and HEX40.fullmatch(object_id) is not None,
              "GIT_SOURCE_FILE_TYPE_DENIED")
    size_raw = _git(repo, "cat-file", "-s", object_id, max_output=32)
    try:
        size = int(size_raw.strip())
    except ValueError as exc:
        raise q.QualificationDenied("GIT_BLOB_SIZE_INVALID") from exc
    q.require(0 < size <= q.MAX_FILE, "GIT_BLOB_TOO_LARGE")
    data = _git(repo, "cat-file", "blob", object_id, max_output=q.MAX_FILE)
    q.require(len(data) == size, "GIT_BLOB_SIZE_MISMATCH")
    return data


def preflight(archive_bytes: bytes, expected_archive_sha256: str) -> planner.PreparedOverlay:
    """Read only a fresh, pinned Git HEAD in private isolated base checkout."""
    repo = fixed_checkout()
    # Forbid tracked or untracked modifications in the private base clone.
    q.require(_git(repo, "status", "--porcelain=v1",
                   "--untracked-files=all", max_output=65536) == b"",
              "ISOLATED_GIT_BASE_DIRTY")
    head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}",
                max_output=128).decode("ascii").strip()
    q.require(HEX40.fullmatch(head) is not None, "BASE_HEAD_INVALID")
    report = q.qualify_bytes(archive_bytes, expected_archive_sha256)
    q.require(report["base_commit"] == head, "CANARY_BASE_COMMIT_DRIFT")
    base = {entry["path"]: base_file(repo, head, entry["path"])
            for entry in report["files"]}
    # Recheck HEAD after all Git reads to avoid a moving base.
    last = _git(repo, "rev-parse", "--verify", "HEAD^{commit}",
                max_output=128).decode("ascii").strip()
    q.require(last == head, "BASE_CHANGED_DURING_READ")
    return planner.prepare(
        archive_bytes=archive_bytes,
        archive_sha256=expected_archive_sha256,
        independently_observed_commit=head,
        observed_base_files=base,
    )
