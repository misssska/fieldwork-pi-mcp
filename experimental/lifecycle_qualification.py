"""Read-only, fail-closed qualification of the five-file lifecycle MCP candidate.

No installation, network, subprocess, service restart or production access.
A trusted caller must pin the manifest hash and the installed main-file hash.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re

from updater import async_overlay
from experimental import lifecycle_overlay

FILES = frozenset({
    'release/stage_async.py',
    'release/async_overlay.py',
    'experimental/stage_inspect.py',
    'experimental/stage_start_async.py',
    'experimental/lifecycle_overlay.py',
})
NEW_TOOLS = frozenset({
    'fieldwork_stage_test_request', 'fieldwork_stage_test_status',
    'fieldwork_stage_start_request', 'fieldwork_stage_start_status',
    'fieldwork_stage_inspect',
})
HEX64 = re.compile(r'[a-f0-9]{64}\Z')
MAX_SOURCE = 1_000_000
MAX_MANIFEST = 16_384


class QualificationBlocked(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise QualificationBlocked(code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(raw: bytes, expected_sha: str) -> dict[str, str]:
    require(type(expected_sha) is str and HEX64.fullmatch(expected_sha) is not None,
            'MANIFEST_PIN_REQUIRED')
    require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST,
            'MANIFEST_SIZE_DENIED')
    require(sha(raw) == expected_sha, 'MANIFEST_HASH_MISMATCH')
    try:
        obj = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise QualificationBlocked('MANIFEST_INVALID') from exc
    require(type(obj) is dict and set(obj) == {'schema', 'purpose', 'files'},
            'MANIFEST_SCHEMA_DENIED')
    require(type(obj['schema']) is int and obj['schema'] == 1 and
            obj['purpose'] == 'fieldwork-pi-mcp-lifecycle-static', 'MANIFEST_PURPOSE_DENIED')
    entries = obj['files']
    require(type(entries) is list and len(entries) == len(FILES), 'MANIFEST_FILE_COUNT_DENIED')
    pins = {}
    for entry in entries:
        require(type(entry) is dict and set(entry) == {'path', 'sha256'},
                'MANIFEST_ENTRY_DENIED')
        path, digest = entry['path'], entry['sha256']
        require(type(path) is str and path in FILES and path not in pins,
                'MANIFEST_PATH_DENIED')
        require(type(digest) is str and HEX64.fullmatch(digest) is not None,
                'MANIFEST_DIGEST_DENIED')
        pins[path] = digest
    require(set(pins) == FILES, 'MANIFEST_MISSING_FILES')
    return pins


def _tool_names(source: bytes) -> list[str]:
    tree = ast.parse(source.decode('utf-8'))
    return [node.elts[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Tuple) and node.elts and
            isinstance(node.elts[0], ast.Constant) and
            type(node.elts[0].value) is str and
            node.elts[0].value.startswith('fieldwork_')]


def qualify(*, installed_source: bytes, expected_installed_sha256: str,
            manifest_bytes: bytes, expected_manifest_sha256: str,
            blobs: dict[str, bytes]) -> dict:
    """Produce a non-authorizing candidate fingerprint, never candidate bytes."""
    require(type(installed_source) is bytes and 0 < len(installed_source) <= MAX_SOURCE,
            'INSTALLED_SOURCE_INVALID')
    require(type(expected_installed_sha256) is str and
            HEX64.fullmatch(expected_installed_sha256) is not None,
            'INSTALLED_PIN_REQUIRED')
    require(sha(installed_source) == expected_installed_sha256,
            'INSTALLED_SOURCE_DRIFT')
    pins = _manifest(manifest_bytes, expected_manifest_sha256)
    require(type(blobs) is dict and set(blobs) == FILES, 'BUNDLE_FILE_SET_DENIED')
    for path, data in blobs.items():
        require(type(data) is bytes and 0 < len(data) <= MAX_SOURCE,
                'BUNDLE_FILE_INVALID')
        require(sha(data) == pins[path], 'BUNDLE_HASH_MISMATCH:' + path)
        try:
            ast.parse(data.decode('utf-8'), filename=path)
        except (UnicodeError, SyntaxError) as exc:
            raise QualificationBlocked('BUNDLE_PYTHON_INVALID:' + path) from exc
    # Compare both reviewed transformation implementations to the actual
    # module bytes being executed, not only to a mutable manifest entry.
    require(blobs['release/async_overlay.py'] ==
            Path(async_overlay.__file__).read_bytes(), 'ASYNC_OVERLAY_IMPLEMENTATION_DRIFT')
    require(blobs['experimental/lifecycle_overlay.py'] ==
            Path(lifecycle_overlay.__file__).read_bytes(), 'LIFECYCLE_OVERLAY_IMPLEMENTATION_DRIFT')
    try:
        candidate = lifecycle_overlay.overlay(async_overlay.overlay(installed_source))
        names = _tool_names(candidate)
    except (UnicodeError, SyntaxError, ValueError) as exc:
        raise QualificationBlocked('CANDIDATE_INCOMPATIBLE:' + type(exc).__name__) from exc
    require(len(candidate) <= MAX_SOURCE, 'CANDIDATE_TOO_LARGE')
    require(all(names.count(name) == 1 for name in NEW_TOOLS),
            'CANDIDATE_TOOL_INVENTORY_DENIED')
    require(len(names) == len(set(names)), 'CANDIDATE_DUPLICATE_TOOL_DENIED')
    return {
        'status': 'LIFECYCLE_STATIC_QUALIFICATION_PASS',
        'installed_sha256': expected_installed_sha256,
        'manifest_sha256': expected_manifest_sha256,
        'candidate_sha256': sha(candidate),
        'new_tools': sorted(NEW_TOOLS),
        'unit_tests_run': False,
        'runtime_tests_run': False,
        'activation_authorized': False,
        'mcp_modified': False,
        'production_modified': False,
        'tunnel_restarted': False,
    }
