"""Operator-approved one-time private Git source bootstrap for FieldWork.

Creates an independent, fixed-path source base from the tracked Git objects
of /opt/fieldwork. The production checkout can be dirty and remains read-only;
this operation never stages, commits, resets, checks out or modifies it.

No MCP tool exposes this bootstrap. Only a local, explicitly approved operator
can run it, with a pinned HEAD. No production secrets, Docker, systemd,
network, shell commands or service changes are part of the operation.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from . import canary_archive_qualifier as q
from . import canary_git_base as gitbase
from . import canary_stage_materializer as stage

SOURCE = Path("/opt/fieldwork")
TARGET = gitbase.BASE_REL
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_TRACKED = 2500
MAX_GIT_LIST = 512_000


def _safe_dir(path: Path, *, private: bool = False) -> None:
    q.require(path.is_dir() and not path.is_symlink(), "BASE_DIRECTORY_UNSAFE")
    st = path.stat()
    q.require(st.st_uid == os.geteuid() and not (
        stat.S_IMODE(st.st_mode) & (0o077 if private else 0o022)),
        "BASE_DIRECTORY_MODE_DENIED")


def _private_parent() -> Path:
    q.require(os.geteuid() != 0, "BOOTSTRAP_ROOT_DENIED")
    home = Path.home()
    _safe_dir(home)
    current = home
    for part in TARGET.parts[:-1]:
        current = current / part
        q.require(not current.is_symlink(), "BASE_PARENT_SYMLINK_DENIED")
        if not current.exists():
            current.mkdir(mode=0o700)
        _safe_dir(current)
    _safe_dir(current, private=False)
    return current


def _git_args(repo: Path, *args: str) -> list[str]:
    return ["git", "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=/dev/null",
            "-c", "protocol.file.allow=never",
            "-C", str(repo), "--no-optional-locks", *args]


def _env() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C"}


def _invoke(argv: list[str], *, max_bytes: int = MAX_GIT_LIST,
            timeout: int = 90) -> bytes:
    try:
        p = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=_env(), close_fds=True)
        assert p.stdout is not None
        with p.stdout:
            out = p.stdout.read(max_bytes + 1)
        if len(out) > max_bytes:
            p.kill()
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)
            raise q.QualificationDenied("GIT_PROCESS_TIMEOUT")
    except (OSError, subprocess.SubprocessError) as exc:
        raise q.QualificationDenied("PINNED_GIT_OPERATION_FAILED") from exc
    q.require(rc == 0 and len(out) <= max_bytes, "PINNED_GIT_OPERATION_DENIED")
    return out


def _head(repo: Path) -> str:
    head = _invoke(_git_args(repo, "rev-parse", "--verify", "HEAD^{commit}"),
                   max_bytes=128).decode("ascii").strip()
    q.require(HEX40.fullmatch(head) is not None, "GIT_HEAD_INVALID")
    return head


def _audit_tree(repo: Path, commit: str) -> dict:
    """Audit every tree entry, including files omitted by the stage policy."""
    q.require(type(commit) is str and HEX40.fullmatch(commit) is not None,
              "EXPECTED_COMMIT_REQUIRED")
    listing = _invoke(_git_args(repo, "ls-tree", "-rz", "-l",
                                "--full-tree", commit),
                      max_bytes=MAX_GIT_LIST)
    rows = listing.split(b"\x00")
    q.require(rows[-1] == b"" and 0 < len(rows) - 1 <= MAX_TRACKED,
              "GIT_TREE_COUNT_INVALID")
    total = included = omitted = 0
    seen = set()
    for raw in rows[:-1]:
        try:
            header, raw_path = raw.split(b"\t", 1)
            mode, kind, oid, length = header.decode("ascii").split()
            path = raw_path.decode("utf-8", "strict")
            size = int(length)
        except (UnicodeError, ValueError) as exc:
            raise q.QualificationDenied("GIT_TREE_INVALID") from exc
        q.require(path not in seen, "GIT_DUPLICATE_PATH")
        seen.add(path)
        q.require(mode in ("100644", "100755") and kind == "blob" and
                  HEX40.fullmatch(oid) is not None,
                  "GIT_SPECIAL_FILE_DENIED")
        q.require(0 <= size <= stage.MAX_TREE_BLOB,
                  "GIT_BLOB_SIZE_DENIED")
        q.require(not path.endswith(".gitattributes") and
                  path != ".gitmodules", "GIT_ATTRIBUTES_OR_SUBMODULES_DENIED")
        decision = stage._source_policy(path)
        if decision == "INCLUDE":
            total += size
            included += 1
        else:
            omitted += 1
        q.require(total <= stage.MAX_TREE_BYTES, "GIT_TOTAL_SIZE_DENIED")
    q.require(included > 0, "GIT_NO_APP_SOURCE")
    return {"tracked_files": len(seen), "included_files": included,
            "omitted_files": omitted, "included_bytes": total}


def preflight(expected_commit: str) -> dict:
    """Read production HEAD/metadata without writing even private directories."""
    q.require(os.geteuid() != 0, "BOOTSTRAP_ROOT_DENIED")
    q.require(type(expected_commit) is str and
              HEX40.fullmatch(expected_commit) is not None,
              "EXPECTED_COMMIT_REQUIRED")
    home = Path.home()
    _safe_dir(home)
    current_parent = home
    for part in TARGET.parts[:-1]:
        current_parent = current_parent / part
        if current_parent.exists() or current_parent.is_symlink():
            _safe_dir(current_parent)
        else:
            break
    q.require(SOURCE.is_dir() and not SOURCE.is_symlink(),
              "PRODUCTION_REPO_NOT_DIRECTORY")
    target = Path.home() / TARGET
    q.require(not target.exists() and not target.is_symlink(),
              "PRIVATE_BASE_ALREADY_EXISTS")
    current = _head(SOURCE)
    q.require(current == expected_commit, "PRODUCTION_HEAD_PIN_MISMATCH")
    report = _audit_tree(SOURCE, current)
    q.require(_head(SOURCE) == current, "PRODUCTION_HEAD_MOVED")
    return {"status": "PRIVATE_BASE_PREFLIGHT_PASS_NOT_CLONED",
            "source_head": current, **report,
            "production_modified": False, "private_base_created": False}


def bootstrap(expected_commit: str, approved: str) -> dict:
    """Create fixed private Git clone only with exact interactive approval."""
    q.require(approved == "LETREHOZOM_A_PRIVAT_GIT_BAZIST",
              "LOCAL_BOOTSTRAP_APPROVAL_REQUIRED")
    report = preflight(expected_commit)
    parent = _private_parent()
    destination = Path.home() / TARGET
    # Clone with --local --no-hardlinks: copy object bytes, never symlink or
    # hardlink object store to the production repository. --no-checkout ensures
    # no application code/filters/hooks are run before the tree is audited.
    temp_parent = Path(tempfile.mkdtemp(prefix=".canary-base-stage-", dir=parent))
    _safe_dir(temp_parent, private=True)
    work = temp_parent / "source"
    try:
        _invoke(["git", "clone", "--local", "--no-hardlinks",
                 "--no-checkout", "--no-tags", "--", str(SOURCE), str(work)],
                timeout=90)
        q.require(_head(work) == expected_commit, "CLONE_HEAD_MISMATCH")
        _audit_tree(work, expected_commit)
        # Git clone creates a new config and no source hooks. The private
        # checkout must have no configured executable external filters.
        cfg = _git_args(work, "config", "--local", "--get-regexp", "^filter\\.")
        p = subprocess.run(cfg, env=_env(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False)
        q.require(p.returncode == 1, "CLONED_GIT_FILTER_CONFIG_DENIED")
        _invoke(_git_args(work, "checkout", "--detach", expected_commit),
                max_bytes=64_000)
        _invoke(_git_args(work, "remote", "remove", "origin"), max_bytes=64_000)
        # Clone creates the worktree with default umask (often 0755).
        # Enforce privacy before the private checkout becomes visible.
        work.chmod(0o700)
        (work / ".git").chmod(0o700)
        _safe_dir(work, private=True)
        _safe_dir(work / ".git", private=True)
        q.require(_head(work) == expected_commit, "PRIVATE_BASE_HEAD_DRIFT")
        q.require(_invoke(_git_args(work, "status", "--porcelain=v1",
                                    "--untracked-files=all"), max_bytes=64_000) == b"",
                  "PRIVATE_BASE_DIRTY")
        q.require(_head(SOURCE) == expected_commit, "PRODUCTION_HEAD_MOVED")
        q.require(not destination.exists() and not destination.is_symlink(),
                  "PRIVATE_BASE_RACE")
        work.rename(destination)
        gitbase.fixed_checkout()
        return {**report, "status": "PRIVATE_GIT_BASE_READY",
                "private_base_created": True, "production_modified": False}
    finally:
        # Only our own disposable, fixed-parent private temp directory.
        if temp_parent.exists():
            shutil.rmtree(temp_parent)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--expected-commit", required=True)
    p.add_argument("--activate", action="store_true")
    args = p.parse_args()
    try:
        before = preflight(args.expected_commit)
        if not args.activate:
            print(__import__("json").dumps(before, sort_keys=True))
            return 0
        consent = input("A privát Git-bázishoz írd be: ").strip()
        result = bootstrap(args.expected_commit, consent)
        print(__import__("json").dumps(result, sort_keys=True))
        return 0
    except (q.QualificationDenied, OSError, ValueError,
            subprocess.SubprocessError) as exc:
        print("PRIVATE_BASE_STOP=" + type(exc).__name__ + ":" + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
