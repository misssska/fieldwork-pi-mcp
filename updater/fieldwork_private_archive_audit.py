#!/usr/bin/env python3
"""Local, read-only FieldWork source ZIP pre-import audit.

Does NOT extract, execute, upload, mutate or publish the archive. It never
prints matched content or potential secret values. An accepted result only
means structural/integrity checks PASS; human secret/licence review is REQUIRED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_SOURCE_BYTES = 48 * 1024 * 1024
MAX_MEMBERS = 600
EXPECTED_FILES = 107
EXPECTED_SOURCE_HEAD = '592c4becceadd9780759ae06ae5a004fa74454df'
EXPECTED_ARCHIVE_SHA256 = '6ed1902f0c7df48ef61841f5dafe2a2d04463ce7168e276decc42d7a2c0e8195'
MANIFEST = '_FIELDWORK_PRIVATE_SOURCE_MANIFEST.json'
REQUIRED = frozenset({
    '.dockerignore', 'Dockerfile', '.github/workflows/backend-tests.yml',
    'nginx/Dockerfile', 'server/Dockerfile', 'server/Dockerfile.test',
    'server/alembic/script.py.mako', 'server/scripts/rotate_admin_password.py',
    'frontend/package.json', 'frontend/package-lock.json',
    'frontend/src/data/FieldworkContext.tsx',
    'frontend/src/components/DocumentViewer.test.tsx',
    'server/app/__init__.py', 'server/alembic/env.py',
})
FORBIDDEN_PARTS = frozenset({'.git', '.env', '.ssh', '.venv', 'node_modules',
                             'uploads', 'upload', 'storage', 'backups', 'backup', 'secrets',
                             'credentials', 'reference', '.next', 'coverage',
                             'postgres_data', 'pgdata'})
ALLOWED_ROOTS = frozenset({'frontend', 'server', 'nginx', 'docs', 'scripts', '.github'})
ALLOWED_ROOT_FILES = frozenset({'.dockerignore', '.gitignore', 'Dockerfile',
                                'README.md', 'docker-compose.yml',
                                'docker-compose.test.yml',
                                'docker-compose.e2e.yml',
                                'docker-compose.override.yml'})
# These rules are intentionally conservative: findings always require a human.
# They are NOT evidence that an archive with zero findings is secret-free.
SECRET_PATTERNS = {
    'private_key_header': re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----'),
    'github_token': re.compile(rb'\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b'),
    'aws_access_key': re.compile(rb'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),
    'api_key_prefix': re.compile(rb'\bsk-[A-Za-z0-9_-]{30,}\b'),
    'slack_token': re.compile(rb'\bxox[baprs]-[a-zA-Z0-9-]{18,}\b'),
    'connection_uri_credentials': re.compile(rb'\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/:@]{1,80}:[^\s/@]{3,80}@'),
    'suspicious_assignment': re.compile(
        rb'(?im)^\s*(?:[\w.\[\]"\']{0,35}(?:password|secret|access_token|api_key|private_key|db_pass)[\w.\[\]"\']{0,15})\s*[:=]\s*[\"\']?([^\s,\"\']{10,})'),
}
# Exclude clearly synthetic test placeholders from the last heuristic only.
PLACEHOLDER = re.compile(rb'(?i)(?:example|changeme|placeholder|dummy|your_|test_|<|\$\{|os\.environ|settings\.|getenv\(|None\b)')

class AuditDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise AuditDenied(reason)


def safe_name(name: str) -> bool:
    if not isinstance(name, str) or not name or len(name) > 280 or '\\' in name or name.startswith('/'):
        return False
    p = PurePosixPath(name)
    if any(t in ('', '.', '..') or t.lower() in FORBIDDEN_PARTS for t in p.parts):
        return False
    if len(p.parts) == 1:
        return name in ALLOWED_ROOT_FILES or name == MANIFEST
    if p.parts[0] not in ALLOWED_ROOTS:
        return False
    if p.parts[0] == '.github' and name != '.github/workflows/backend-tests.yml':
        return False
    if p.name.startswith('.env'):
        return False
    return True


def line_no(content: bytes, match_start: int) -> int:
    return content.count(b'\n', 0, match_start) + 1


def audit(archive: Path) -> dict:
    require(archive.is_absolute() and archive.is_file() and not archive.is_symlink(),
            'ZIP_PATH_NOT_REGULAR_OR_ABSOLUTE')
    require(0 < archive.stat().st_size <= MAX_ZIP_BYTES, 'ZIP_SIZE_DENIED')
    raw_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    require(raw_sha == EXPECTED_ARCHIVE_SHA256, 'ZIP_SHA256_MISMATCH')
    findings = []
    total_size = 0
    with zipfile.ZipFile(archive, 'r') as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        require(len(infos) == EXPECTED_FILES + 1 and len(infos) <= MAX_MEMBERS,
                'ZIP_MEMBER_COUNT_DENIED')
        require(len(names) == len(set(names)), 'ZIP_DUPLICATE_PATH_DENIED')
        require(all(safe_name(n) for n in names), 'ZIP_UNSAFE_PATH_DENIED')
        require(MANIFEST in names and REQUIRED.issubset(names), 'REQUIRED_FILES_MISSING')
        info = {i.filename: i for i in infos}
        for i in infos:
            require(not i.is_dir() and i.file_size <= 3 * 1024 * 1024,
                    'ZIP_MEMBER_TYPE_OR_SIZE_DENIED')
            mode = i.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG), 'ZIP_SYMLINK_OR_SPECIAL_DENIED')
            total_size += i.file_size
            require(total_size <= MAX_SOURCE_BYTES, 'ZIP_TOTAL_UNCOMPRESSED_SIZE_DENIED')
        manifest = json.loads(z.read(MANIFEST))
        require(type(manifest) is dict and
                manifest.get('format') == 'FIELDWORK_PRIVATE_SOURCE_CANDIDATE_V1' and
                manifest.get('source_head') == EXPECTED_SOURCE_HEAD and
                manifest.get('source_modified') is False and
                manifest.get('remote_push_performed') is False and
                manifest.get('contains_private_data_audit') == 'REVIEW_REQUIRED_BEFORE_UPLOAD',
                'ZIP_MANIFEST_CONTEXT_INVALID')
        sources = manifest.get('source_files')
        require(type(sources) is dict and len(sources) == EXPECTED_FILES and
                set(sources) == set(names) - {MANIFEST}, 'ZIP_MANIFEST_FILE_LIST_INVALID')
        byte_count = 0
        for name in sorted(sources):
            content = z.read(name)
            byte_count += len(content)
            expected = sources[name]
            require(type(expected) is str and re.fullmatch(r'[a-f0-9]{64}', expected) is not None and
                    hashlib.sha256(content).hexdigest() == expected,
                    'ZIP_SOURCE_MEMBER_HASH_MISMATCH')
            for rule, pattern in SECRET_PATTERNS.items():
                for m in pattern.finditer(content):
                    if rule == 'suspicious_assignment' and PLACEHOLDER.search(m.group(0)):
                        continue
                    # Report only rule, file and line -- NEVER match/secret data.
                    findings.append({'file': name, 'line': line_no(content, m.start()), 'rule': rule})
        require(byte_count == manifest.get('source_bytes'), 'ZIP_SOURCE_SIZE_MISMATCH')
        require(z.read('server/app/__init__.py') == b'', 'ZERO_BYTE_INIT_DRIFT')
        # Defensive check: the expected number of private source files is from
        # the Pi log. This audit does not certify licence/PII absence.
    return {
        'status': 'SOURCE_STRUCTURE_AND_SHA_PASS',
        'sha256': raw_sha,
        'files': EXPECTED_FILES,
        'source_bytes': byte_count,
        'source_head': EXPECTED_SOURCE_HEAD,
        'required_files': len(REQUIRED),
        'findings_count': len(findings),
        'findings': findings[:100],
        'findings_truncated': len(findings) > 100,
        'private_data_review_required': True,
        'ready_to_upload': False,
        'git_push_performed': False,
        'production_modified': False,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive', type=Path, required=True)
    args = ap.parse_args()
    try:
        result = audit(args.archive)
    except (AuditDenied, OSError, zipfile.BadZipFile, UnicodeError, ValueError,
            KeyError, TypeError) as exc:
        code = str(exc) if isinstance(exc, AuditDenied) else 'ZIP_CANNOT_BE_VERIFIED'
        print(json.dumps({'status': 'BLOCKED', 'reason': code,
                          'ready_to_upload': False}), flush=True)
        sys.exit(2)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))

if __name__ == '__main__':
    main()
