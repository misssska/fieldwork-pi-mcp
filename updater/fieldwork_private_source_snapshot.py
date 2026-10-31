"""Read-only FieldWork code snapshot for later private-repo migration.

Runs locally by a human. Never calls git add/commit/push, Docker, sudo, network,
or modifies the application's files, index, refs, or worktree. Creates exactly
one candidate ZIP outside the checkout with explicit scope and risk inventory.
This is not secret-proof: review the ZIP before ANY upload.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

MAX_FILES = 550
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
SOURCE_ROOTS = {
    'frontend': {'.ts', '.tsx', '.css', '.html', '.json', '.mjs', '.js', '.svg'},
    'server': {'.py', '.toml', '.txt', '.ini'},
    'nginx': {'.conf'},
    'scripts': {'.py', '.sh'},
    'docs': {'.md'},
}
SOURCE_ROOT_FILES = frozenset({
    'README.md', '.gitignore', 'docker-compose.yml',
    'docker-compose.test.yml', 'docker-compose.e2e.yml',
    'docker-compose.override.yml',
})
BANNED_PARTS = frozenset({
    '.git', '.env', '.venv', '.ssh', 'node_modules', '__pycache__',
    'dist', 'build', 'storage', 'uploads', 'backup', 'backups', 'secrets',
    'credentials', 'private', '.next', 'coverage', '.pytest_cache',
})
SENSITIVE_BASENAME = re.compile(
    r'(?:^|[._-])(?:id_rsa|id_ed25519|private_key|credential|secret|password|token|api_key|\.env)(?:[._-]|$)',
    re.IGNORECASE)
SENSITIVE_CONTENT = re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----|'
                               rb'github_pat_[a-zA-Z0-9_]{20,}|ghp_[a-zA-Z0-9]{20,}|'
                               rb'AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{30,}|'
                               rb'xox[baprs]-[a-zA-Z0-9-]{18,}')

class SnapshotDenied(ValueError):
    pass

def ensure(value: bool, message: str) -> None:
    if not value:
        raise SnapshotDenied(message)

def command(root: Path, args: tuple[str, ...]) -> bytes:
    ensure(args in {
        ('rev-parse', '--show-toplevel'), ('rev-parse', 'HEAD'),
        ('ls-files', '-z', '--cached', '--others', '--exclude-standard'),
        ('status', '--porcelain', '--untracked-files=all'),
    }, 'GIT_COMMAND_DENIED')
    try:
        run = subprocess.run(['git', '-C', str(root), *args], shell=False,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=15,
                             env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, subprocess.SubprocessError):
        raise SnapshotDenied('GIT_FAILED') from None
    ensure(run.returncode == 0 and len(run.stdout) <= 4_000_000, 'GIT_RESULT_DENIED')
    return run.stdout

def admissible(rel: str) -> bool:
    if not rel or '\\' in rel or len(rel) > 260 or rel.startswith('/'):
        return False
    pp = PurePosixPath(rel)
    if any(p in ('', '.', '..') or p.lower() in BANNED_PARTS for p in pp.parts):
        return False
    if SENSITIVE_BASENAME.search(pp.name):
        return False
    if len(pp.parts) == 1:
        return rel in SOURCE_ROOT_FILES
    return pp.parts[0] in SOURCE_ROOTS and pp.suffix.lower() in SOURCE_ROOTS[pp.parts[0]]

def inspect(root: Path) -> tuple[list[tuple[str, bytes]], dict]:
    ensure(root.is_absolute() and root == root.resolve(strict=True), "SOURCE_ROOT_NOT_CANONICAL")
    ensure(root.is_dir() and not root.is_symlink() and
           command(root, ('rev-parse', '--show-toplevel')).decode().strip() == str(root),
           'SOURCE_NOT_GIT_ROOT')
    sha = command(root, ('rev-parse', 'HEAD')).decode().strip()
    ensure(re.fullmatch(r'[0-9a-f]{40}', sha) is not None, 'SOURCE_COMMIT_INVALID')
    names = command(root, ('ls-files', '-z', '--cached', '--others', '--exclude-standard')).decode('utf-8').strip('\x00').split('\x00')
    ensure(len(names) == len(set(names)) and len(names) <= MAX_FILES,
           'SOURCE_FILE_COUNT_DENIED')
    accepted, blocked, byte_count = [], [], 0
    for rel in sorted(names):
        if not admissible(rel):
            blocked.append(rel)
            continue
        path = root
        for part in PurePosixPath(rel).parts:
            path = path / part
            ensure(not path.is_symlink(), 'SYMLINK_SOURCE_DENIED:'+rel)
        ensure(path.resolve().is_relative_to(root), 'SOURCE_ESCAPE_DENIED:'+rel)
        ensure(path.is_file(), "SOURCE_FILE_MISSING:"+rel)
        # O_NOFOLLOW closes the symlink swap window between path inspection and open.
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except OSError:
            raise SnapshotDenied('SOURCE_OPEN_DENIED:'+rel) from None
        with os.fdopen(fd, 'rb') as handle:
            st = os.fstat(handle.fileno())
            ensure(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= MAX_FILE_BYTES,
                   'INVALID_FILE_SIZE_OR_TYPE:'+rel)
            byte_count += st.st_size
            ensure(byte_count <= MAX_TOTAL_BYTES, 'TOTAL_FILE_SIZE_DENIED')
            data = handle.read(MAX_FILE_BYTES + 1)
            ensure(len(data) == st.st_size, 'FILE_MODIFIED_DURING_SNAPSHOT:'+rel)
            ensure(os.fstat(handle.fileno()).st_size == st.st_size,
                   'FILE_CHANGED_WHILE_READING:'+rel)
        ensure(not SENSITIVE_CONTENT.search(data), 'EMBEDDED_CREDENTIAL_DETECTED:'+rel)
        accepted.append((rel, data))
    # Existing worktree is intentionally preserved and its status recorded.
    status = command(root, ('status', '--porcelain', '--untracked-files=all'))
    report = {
        'format': 'FIELDWORK_PRIVATE_SOURCE_CANDIDATE_V1',
        'source_head': sha, 'dirty_worktree': bool(status),
        'source_status_sha256': hashlib.sha256(status).hexdigest(),
        'source_files': {k: hashlib.sha256(b).hexdigest() for k, b in accepted},
        'excluded_paths': blocked, 'source_bytes': byte_count,
        'contains_private_data_audit': 'REVIEW_REQUIRED_BEFORE_UPLOAD',
        'remote_push_performed': False, 'source_modified': False,
    }
    ensure(bool(accepted) and 'frontend/package-lock.json' in report['source_files'],
           'MANDATORY_FRONTEND_LOCKFILE_MISSING')
    return accepted, report

def export(root: Path, destination: Path) -> dict:
    ensure(destination.is_absolute() and destination.suffix == '.zip' and
           not destination.exists() and destination.parent.is_dir() and
           not destination.parent.is_symlink(), 'INVALID_DESTINATION')
    ensure(root.is_absolute() and root == root.resolve(strict=True), "SOURCE_ROOT_NOT_CANONICAL")
    ensure(not destination.resolve().is_relative_to(root), 'DESTINATION_MUST_BE_OUTSIDE_SOURCE')
    selected, report = inspect(root)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.fieldwork-source-', suffix='.tmp',
                                         dir=destination.parent, delete=False) as f:
            temp = Path(f.name)
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel, data in selected:
                meta = zipfile.ZipInfo(rel, (2020, 1, 1, 0, 0, 0))
                meta.compress_type = zipfile.ZIP_DEFLATED
                meta.external_attr = (0o100644 << 16)
                z.writestr(meta, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
            meta = zipfile.ZipInfo('_FIELDWORK_PRIVATE_SOURCE_MANIFEST.json', (2020, 1, 1, 0, 0, 0))
            meta.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(meta, json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2).encode(),
                       compress_type=zipfile.ZIP_DEFLATED)
        os.chmod(temp, 0o600)
        with temp.open('rb') as f:
            os.fsync(f.fileno())
        # If a local file changed mid-export, do not deliver a misleading archive.
        selected2, report2 = inspect(root)
        ensure(report == report2 and len(selected) == len(selected2),
               'SOURCE_CHANGED_DURING_EXPORT')
        os.replace(temp, destination)
        temp = None
        report['archive_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
        report['archive_path'] = str(destination)
        return report
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

def verify(archive: Path) -> dict:
    ensure(archive.is_file() and not archive.is_symlink() and
           0 < archive.stat().st_size <= 50 * 1024 * 1024,
           'ARCHIVE_SIZE_OR_TYPE_DENIED')
    try:
        with zipfile.ZipFile(archive, 'r') as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            manifest_name = '_FIELDWORK_PRIVATE_SOURCE_MANIFEST.json'
            ensure(len(names) == len(set(names)) and names.count(manifest_name) == 1
                   and len(infos) <= MAX_FILES + 1,
                   'ARCHIVE_DUPLICATE_OR_MANIFEST_MISSING')
            ensure(all(not n.startswith('/') and '..' not in PurePosixPath(n).parts
                       for n in names), 'INVALID_ARCHIVE_PATH')
            require_size = 0
            for info in infos:
                ensure(not info.is_dir() and info.file_size <= MAX_FILE_BYTES and
                       info.compress_size <= 50 * 1024 * 1024,
                       'ARCHIVE_FILE_SIZE_DENIED')
                require_size += info.file_size
                ensure(require_size <= MAX_TOTAL_BYTES + 1024 * 1024,
                       'ARCHIVE_TOTAL_SIZE_DENIED')
            report = json.loads(z.read(manifest_name))
            ensure(report.get('format') == 'FIELDWORK_PRIVATE_SOURCE_CANDIDATE_V1'
                   and type(report.get('source_files')) is dict and
                   set(names) == set(report['source_files']) | {manifest_name},
                   'ARCHIVE_MANIFEST_CONTRACT_DENIED')
            for name, expected in report['source_files'].items():
                ensure(admissible(name) and
                       re.fullmatch(r'[a-f0-9]{64}', expected) is not None and
                       hashlib.sha256(z.read(name)).hexdigest() == expected,
                       'ARCHIVE_MEMBER_HASH_OR_PATH_DENIED:'+name)
            ensure(report.get('remote_push_performed') is False and
                   report.get('source_modified') is False and
                   report.get('contains_private_data_audit') == 'REVIEW_REQUIRED_BEFORE_UPLOAD',
                   'ARCHIVE_READONLY_REVIEW_CONTRACT_DENIED')
            return {'status': 'FIELDWORK_PRIVATE_SOURCE_ARCHIVE_VERIFIED',
                    'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'file_count': len(report['source_files']),
                    'source_head': report['source_head'],
                    'ready_to_upload': False,
                    'private_data_review_required': True}
    except (OSError, zipfile.BadZipFile, ValueError, KeyError, AssertionError) as exc:
        if isinstance(exc, SnapshotDenied):
            raise
        raise SnapshotDenied('ARCHIVE_UNVERIFIED') from exc

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path)
    ap.add_argument('--destination', type=Path)
    ap.add_argument('--verify', type=Path)
    args = ap.parse_args()
    if args.verify is not None:
        result = verify(args.verify)
    else:
        ensure(args.source is not None and args.destination is not None,
               'SOURCE_AND_DESTINATION_REQUIRED')
        result = export(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))

if __name__ == '__main__':
    main()
