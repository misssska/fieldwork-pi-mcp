"""FieldWork Pi MCP activation planner; read-only, fail-closed.

This module does not activate, restart, write or roll back a service. It produces
an immutable review plan only when a prequalified release exactly matches the
currently installed source. The actual local approval gate is a separate task.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
MAX_SOURCE = 1_000_000


class ActivationBlocked(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ActivationBlocked(code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_private_file(path: Path, *, limit: int = MAX_SOURCE) -> bytes:
    require(not path.is_symlink() and path.is_file(), 'SOURCE_MISSING_OR_SYMLINK')
    st = path.stat()
    require(st.st_uid == os.getuid(), 'SOURCE_NOT_OWNED')
    require(stat.S_IMODE(st.st_mode) & 0o022 == 0, 'SOURCE_WRITABLE_BY_OTHERS')
    require(st.st_size <= limit, 'SOURCE_TOO_LARGE')
    return path.read_bytes()


def build_plan(*, installed: Path, candidate: bytes, extension: bytes,
               qualification: dict, commit: str, manifest_sha256: str) -> dict:
    """Validate exact hashes and return a dry-run activation plan, no writes."""
    require(type(qualification) is dict, 'QUALIFICATION_REQUIRED')
    require(HEX40.fullmatch(commit) is not None, 'COMMIT_REQUIRED')
    require(HEX64.fullmatch(manifest_sha256) is not None, 'MANIFEST_HASH_REQUIRED')
    require(qualification.get('status') == 'STATIC_QUALIFICATION_PASS',
            'QUALIFICATION_NOT_PASSED')
    require(qualification.get('commit') == commit and
            qualification.get('release_manifest_sha256') == manifest_sha256,
            'QUALIFICATION_RELEASE_MISMATCH')
    require(qualification.get('activation_authorized') is False and
            qualification.get('production_modified') is False and
            qualification.get('mcp_modified') is False and
            qualification.get('tunnel_restarted') is False,
            'QUALIFICATION_FLAGS_UNEXPECTED')
    main = read_private_file(installed)
    installed_hash = sha(main)
    require(installed_hash == qualification.get('installed_source_sha256'),
            'INSTALLED_SOURCE_CHANGED')
    require(len(candidate) <= MAX_SOURCE and len(extension) <= MAX_SOURCE,
            'CANDIDATE_TOO_LARGE')
    require(sha(candidate) == qualification.get('candidate_source_sha256'),
            'CANDIDATE_HASH_MISMATCH')
    require(sha(extension) == qualification.get('stage_async_sha256'),
            'EXTENSION_HASH_MISMATCH')
    require(installed.parent.is_dir() and not installed.parent.is_symlink(),
            'MCP_DIRECTORY_UNSAFE')
    require(not (installed.parent / 'stage_async.py').exists() and
            not (installed.parent / 'stage_async.py').is_symlink(),
            'EXTENSION_ALREADY_PRESENT')
    # A plan is not permission to install. No executable script or arbitrary path.
    return {
        'status': 'DRY_RUN_PLAN_ONLY',
        'commit': commit,
        'release_manifest_sha256': manifest_sha256,
        'installed_source_sha256': installed_hash,
        'candidate_source_sha256': sha(candidate),
        'extension_sha256': sha(extension),
        'production_modified': False,
        'mcp_modified': False,
        'tunnel_restarted': False,
        'activation_authorized': False,
        'requires': ['isolated_unit_test_pass', 'local_explicit_approval',
                     'atomic_backup_and_replace', 'existing_tunnel_health_check',
                     'automatic_rollback_on_failure'],
    }
