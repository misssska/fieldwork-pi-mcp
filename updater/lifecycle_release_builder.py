"""Build reproducible, non-installable four-file MCP lifecycle release ZIP.

Only exact Schemafix-r1 source bytes and exact five-file hash-pinned module
manifest are accepted. This module does not access the Pi, write files, execute source code,
execute commands, approve activation, or restart services. Zip is returned as
bytes for external review; manifest explicitly says NOT DEPLOYABLE.
"""
from __future__ import annotations

import ast
from io import BytesIO
import json
import hashlib
import zipfile

from experimental import lifecycle_qualification as qualification
from experimental import lifecycle_overlay
from updater import async_overlay, schemafix_lineage

FILE_NAMES = (
    'fieldwork_mcp.py',
    'stage_async.py',
    'stage_inspect.py',
    'stage_start_async.py',
)
MODULE_PATHS = {
    'stage_async.py': 'release/stage_async.py',
    'stage_inspect.py': 'experimental/stage_inspect.py',
    'stage_start_async.py': 'experimental/stage_start_async.py',
}
META_NAME = 'lifecycle-release.json'
ZIP_NAMES = frozenset((*FILE_NAMES, META_NAME))
MAX_ARCHIVE = 4_500_000
PINNED_MANIFEST_SHA256 = 'd500da3872ff05c22cefbc75fa8091fc30e39471a634926e127e3a48d13a1c0e'
MAX_FILE = 1_000_000
TIMESTAMP = (2026, 10, 30, 0, 0, 0)


class BundleRejected(ValueError):
    pass


def require(valid: bool, reason: str) -> None:
    if not valid:
        raise BundleRejected(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True) + '\n').encode('ascii')


def build(*, source: bytes, manifest: bytes, expected_manifest_sha256: str,
          modules: dict[str, bytes]) -> tuple[bytes, dict]:
    """Construct a fixed-scope, reproducible ZIP without any filesystem I/O."""
    require(type(source) is bytes and sha(source) == schemafix_lineage.SCHEMAFIX_SHA,
            'SCHEMAFIX_SOURCE_HASH_DENIED')
    require(expected_manifest_sha256 == PINNED_MANIFEST_SHA256,
            'UNTRUSTED_RELEASE_MANIFEST')
    require(type(modules) is dict and
            set(modules) == qualification.FILES, 'MODULE_FILE_SET_DENIED')
    result = qualification.qualify(
        installed_source=source,
        expected_installed_sha256=schemafix_lineage.SCHEMAFIX_SHA,
        manifest_bytes=manifest,
        expected_manifest_sha256=expected_manifest_sha256,
        blobs=modules,
    )
    require(result['status'] == 'LIFECYCLE_STATIC_QUALIFICATION_PASS' and
            result.get('activation_authorized') is False and
            result.get('mcp_modified') is False, 'QUALIFICATION_DENIED')
    candidate = lifecycle_overlay.overlay(async_overlay.overlay(source))
    require(sha(candidate) == schemafix_lineage.LIFECYCLE_SCHEMAFIX_SHA,
            'CANDIDATE_SHA_DENIED')
    require(result['candidate_sha256'] == sha(candidate),
            'QUALIFICATION_CANDIDATE_DRIFT')
    payloads = {'fieldwork_mcp.py': candidate}
    for dest, src in MODULE_PATHS.items():
        payloads[dest] = modules[src]
    for filename, data in payloads.items():
        require(type(data) is bytes and 0 < len(data) <= MAX_FILE,
                'FILE_SIZE_OR_TYPE_DENIED')
        try:
            ast.parse(data.decode('utf-8'), filename=filename)
        except (UnicodeError, SyntaxError) as exc:
            raise BundleRejected('INVALID_PYTHON:' + filename) from exc
    record = {
        'schema': 1,
        'purpose': 'fieldwork-pi-mcp-lifecycle-offline-review-only',
        'source_sha256': schemafix_lineage.SCHEMAFIX_SHA,
        'module_manifest_sha256': expected_manifest_sha256,
        'files': {name: sha(payloads[name]) for name in FILE_NAMES},
        'activation_authorized': False,
        'production_modified': False,
        'mcp_modified': False,
        'tunnel_restarted': False,
        'real_pi_readiness_verified': False,
    }
    package = BytesIO()
    with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        for filename in (*FILE_NAMES, META_NAME):
            data = _json(record) if filename == META_NAME else payloads[filename]
            info = zipfile.ZipInfo(filename, date_time=TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    zip_bytes = package.getvalue()
    require(len(zip_bytes) <= MAX_ARCHIVE, 'ARCHIVE_SIZE_DENIED')
    verify(zip_bytes, expected_manifest_sha256=expected_manifest_sha256)
    return zip_bytes, {'status': 'REVIEW_ZIP_READY_NOT_INSTALLABLE',
                       'zip_sha256': sha(zip_bytes),
                       'files': record['files'],
                       'activation_authorized': False,
                       'production_modified': False}


def verify(data: bytes, *, expected_manifest_sha256: str) -> dict:
    """Fail-closed archive integrity check, not trusted-source qualification."""
    require(type(data) is bytes and 0 < len(data) <= MAX_ARCHIVE,
            'ARCHIVE_SIZE_DENIED')
    require(type(expected_manifest_sha256) is str and
            len(expected_manifest_sha256) == 64 and
            all(c in '0123456789abcdef' for c in expected_manifest_sha256),
            'MANIFEST_PIN_DENIED')
    try:
        with zipfile.ZipFile(BytesIO(data), 'r') as archive:
            names = archive.namelist()
            require(len(names) == len(ZIP_NAMES) and set(names) == ZIP_NAMES,
                    'ARCHIVE_FILE_SET_DENIED')
            content = {}
            for info in archive.infolist():
                require(info.filename in ZIP_NAMES and
                        info.compress_type == zipfile.ZIP_STORED and
                        info.file_size > 0 and info.file_size <= MAX_FILE and
                        not info.is_dir() and info.create_system == 3 and
                        (info.external_attr >> 16) == 0o100600,
                        'ARCHIVE_ENTRY_UNSAFE')
                content[info.filename] = archive.read(info)
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, BundleRejected):
            raise
        raise BundleRejected('ARCHIVE_INVALID') from exc
    try:
        record = json.loads(content[META_NAME].decode('ascii'))
    except (UnicodeError, ValueError) as exc:
        raise BundleRejected('RELEASE_RECORD_INVALID') from exc
    require(type(record) is dict and set(record) == {
        'schema', 'purpose', 'source_sha256', 'module_manifest_sha256',
        'files', 'activation_authorized', 'production_modified',
        'mcp_modified', 'tunnel_restarted', 'real_pi_readiness_verified',
    }, 'RELEASE_RECORD_SCHEMA_DENIED')
    require(type(record['schema']) is int and record['schema'] == 1 and
            record['purpose'] == 'fieldwork-pi-mcp-lifecycle-offline-review-only'
            and record['source_sha256'] == schemafix_lineage.SCHEMAFIX_SHA
            and record['module_manifest_sha256'] == expected_manifest_sha256
            and all(record[key] is False for key in (
                'activation_authorized', 'production_modified',
                'mcp_modified', 'tunnel_restarted', 'real_pi_readiness_verified'
            )), 'RELEASE_RECORD_DENIED')
    require(type(record['files']) is dict and
            set(record['files']) == set(FILE_NAMES), 'FILE_PINS_DENIED')
    for filename in FILE_NAMES:
        require(type(record['files'][filename]) is str and
                record['files'][filename] == sha(content[filename]),
                'PAYLOAD_HASH_MISMATCH')
        try:
            ast.parse(content[filename].decode('utf-8'))
        except (UnicodeError, SyntaxError) as exc:
            raise BundleRejected('PAYLOAD_PYTHON_INVALID') from exc
    require(record['files']['fieldwork_mcp.py'] ==
            schemafix_lineage.LIFECYCLE_SCHEMAFIX_SHA,
            'MAIN_CANDIDATE_SHA_DENIED')
    return {'status': 'ARCHIVE_BYTE_INTEGRITY_PASS_NOT_AUTHORIZED',
            'zip_sha256': sha(data), 'activation_authorized': False,
            'production_modified': False}
