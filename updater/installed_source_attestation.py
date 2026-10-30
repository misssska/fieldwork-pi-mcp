"""Local, read-only FieldWork Pi MCP source fingerprint and structural check.

No source code, arbitrary string literals or credentials are returned.
No code execution, install, approval, service restart, network or production write.
The CLI audits only the fixed MCP source path under the current user's home.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

RELATIVE_SOURCE = Path('.local/share/fieldwork-pi-mcp/v0.6.1/fieldwork_mcp.py')
BASELINE_SHA256 = 'b504460dc1477898dc048dc990e7fd432ba880926f9f063904cd6a9b085e5948'
PREVIOUSLY_REPORTED_PI_SHA256 = '7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04'
MAX_BYTES = 1_000_000
STAGE_TOOL_NAMES = frozenset({
    'fieldwork_stage_test_request', 'fieldwork_stage_test_status',
    'fieldwork_stage_start_request', 'fieldwork_stage_start_status',
    'fieldwork_stage_inspect',
})


class AuditBlocked(RuntimeError):
    """Expected fail-closed check, whose message contains no source data."""


def require(valid: bool, reason: str) -> None:
    if not valid:
        raise AuditBlocked(reason)


def _safe_dir(path: Path, uid: int) -> None:
    # lstat does not follow the symlink for this path component.
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode), 'UNSAFE_PARENT_TYPE')
    require(st.st_uid in (0, uid), 'UNSAFE_PARENT_OWNER')
    require((st.st_mode & 0o022) == 0, 'UNSAFE_PARENT_MODE')


def _safe_ancestors(path: Path, home: Path, uid: int) -> None:
    require(path.is_absolute() and home.is_absolute(), 'NON_ABSOLUTE_PATH')
    require(path == home / RELATIVE_SOURCE, 'SOURCE_PATH_DENIED')
    current = home
    _safe_dir(current, uid)
    for part in RELATIVE_SOURCE.parts[:-1]:
        current = current / part
        _safe_dir(current, uid)


def _read_secure(path: Path, uid: int) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                'UNSAFE_SOURCE_TYPE')
        require(before.st_uid == uid, 'UNSAFE_SOURCE_OWNER')
        require((before.st_mode & 0o022) == 0, 'UNSAFE_SOURCE_MODE')
        require(0 < before.st_size <= MAX_BYTES, 'SOURCE_SIZE_DENIED')
        data = bytearray()
        while len(data) < MAX_BYTES + 1:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        require(len(data) == before.st_size and
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                 before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                 after.st_ctime_ns), 'SOURCE_CHANGED_DURING_READ')
        on_disk = os.stat(path, follow_symlinks=False)
        require((after.st_dev, after.st_ino) == (on_disk.st_dev, on_disk.st_ino),
                'SOURCE_PATH_CHANGED')
        return bytes(data)
    finally:
        os.close(fd)


def _registration_tuple_names(tree: ast.AST) -> list[str]:
    """Static tuple candidates ONLY; never claims actual runtime MCP discovery."""
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or not node.elts:
            continue
        literal = node.elts[0]
        if isinstance(literal, ast.Constant) and type(literal.value) is str:
            if literal.value in STAGE_TOOL_NAMES:
                result.append(literal.value)
    return result


def inspect(*, home: Path | None = None, uid: int | None = None) -> dict:
    """Return sanitized evidence only; tests may use a disposable HOME tree."""
    home = Path.home() if home is None else home
    uid = os.getuid() if uid is None else uid
    path = home / RELATIVE_SOURCE
    try:
        require(os.geteuid() != 0, 'ROOT_EXECUTION_DENIED')
        _safe_ancestors(path, home, uid)
        data = _read_secure(path, uid)
        sha256 = hashlib.sha256(data).hexdigest()
        tree = ast.parse(data.decode('utf-8'), filename='fieldwork_mcp.py')
        found = _registration_tuple_names(tree)
    except (OSError, AuditBlocked, UnicodeError, SyntaxError, ValueError) as exc:
        reason = (str(exc) if isinstance(exc, AuditBlocked)
                  else 'INVALID_PYTHON' if isinstance(exc, (UnicodeError, SyntaxError))
                  else 'UNREADABLE_OR_RACED_SOURCE')
        return {'status': 'BLOCKED', 'reason': reason, 'activation_authorized': False,
                'source_disclosed': False, 'mcp_modified': False}
    if sha256 == BASELINE_SHA256:
        status = 'KNOWN_BUNDLE_HASH_ONLY'
    elif sha256 == PREVIOUSLY_REPORTED_PI_SHA256:
        status = 'PREVIOUSLY_OBSERVED_PI_HASH_UNREVIEWED'
    else:
        status = 'UNKNOWN_SOURCE_HASH'
    counts = {name: found.count(name) for name in sorted(STAGE_TOOL_NAMES)}
    return {'status': status, 'sha256': sha256, 'size_bytes': len(data),
            'python_ast_valid': True, 'stage_registration_tuple_counts': counts,
            'structural_check_only': True, 'source_reviewed': False,
            'activation_authorized': False, 'source_disclosed': False,
            'mcp_modified': False, 'next_step': 'LOCAL_SOURCE_REVIEW_REQUIRED'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()  # No customizable path or execution mode.
    result = inspect()
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'KNOWN_BUNDLE_HASH_ONLY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
