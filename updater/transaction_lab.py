"""Crash-recovery rehearsal for two-file MCP updates, restricted to a test sandbox.

NO production path, no host service, no tunnel, no network, no shell, no install CLI.
State is persisted before any replacement. A new process can call recover().
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


class TransactionError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise TransactionError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd, name = tempfile.mkstemp(prefix='.txn-', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        _sync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def _read(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), 'FILE_UNSAFE')
    st = path.stat()
    require(st.st_uid == os.getuid() and not (st.st_mode & 0o022), 'FILE_PERMISSIONS_UNSAFE')
    require(st.st_size <= 1_000_000, 'FILE_TOO_LARGE')
    return path.read_bytes()


def _sandbox(root: Path) -> None:
    """Hard boundary: only inside the OS temporary folder, never a real Pi MCP."""
    base = Path(tempfile.gettempdir()).resolve()
    require(root.is_absolute() and root.parent.parent == base and
            re.fullmatch(r'fieldwork-mcp-lab-[a-z0-9_-]+', root.parent.name) is not None and
            root.name == 'mcp', 'NON_TEST_DESTINATION_DENIED')
    for path in (root, root.parent):
        require(path.is_dir() and not path.is_symlink(), 'TEST_DIRECTORY_UNSAFE')
        st = path.stat()
        require(st.st_uid == os.getuid() and not (st.st_mode & 0o022),
                'TEST_DIRECTORY_PERMISSIONS_UNSAFE')


class LabTransaction:
    """Single two-file transaction. Intentional: no activation/approval entrypoint."""

    def __init__(self, root: Path):
        _sandbox(root)
        self.root = root
        self.main = root / 'fieldwork_mcp.py'
        self.extension = root / 'stage_async.py'
        self.backup = root / '.transaction-backup'
        self.journal = root / '.transaction.json'

    def _journal(self) -> dict:
        obj = json.loads(_read(self.journal))
        require(type(obj) is dict and set(obj) == {
            'schema', 'status', 'original_sha256', 'candidate_sha256',
            'extension_sha256', 'original_mode'
        } and obj['schema'] == 1, 'JOURNAL_SCHEMA_INVALID')
        require(obj['status'] in ('PREPARED', 'APPLYING', 'APPLIED',
                                  'ROLLED_BACK', 'COMMITTED'), 'JOURNAL_STATUS_INVALID')
        for key in ('original_sha256', 'candidate_sha256', 'extension_sha256'):
            require(type(obj[key]) is str and re.fullmatch('[0-9a-f]{64}', obj[key]),
                    'JOURNAL_HASH_INVALID')
        require(type(obj['original_mode']) is int and 0 <= obj['original_mode'] <= 0o777,
                'JOURNAL_MODE_INVALID')
        return obj

    def _save(self, obj: dict) -> None:
        _write_atomic(self.journal, (json.dumps(obj, sort_keys=True) + '\n').encode())

    def prepare(self, candidate: bytes, extension: bytes, expected_sha256: str) -> dict:
        require(not self.journal.exists() and not self.journal.is_symlink(),
                'TRANSACTION_ALREADY_EXISTS')
        require(not self.backup.exists() and not self.backup.is_symlink(),
                'BACKUP_ALREADY_EXISTS')
        require(not self.extension.exists() and not self.extension.is_symlink(),
                'EXTENSION_ALREADY_EXISTS')
        require(len(candidate) <= 1_000_000 and len(extension) <= 1_000_000,
                'CANDIDATE_TOO_LARGE')
        original = _read(self.main)
        require(sha(original) == expected_sha256, 'INSTALLED_SOURCE_DRIFT')
        require(candidate != original, 'CANDIDATE_NOT_CHANGED')
        mode = stat.S_IMODE(self.main.stat().st_mode)
        # Durable backup must exist BEFORE journal, and journal BEFORE any replacement.
        _write_atomic(self.backup, original)
        record = {'schema': 1, 'status': 'PREPARED',
                  'original_sha256': sha(original), 'candidate_sha256': sha(candidate),
                  'extension_sha256': sha(extension), 'original_mode': mode}
        self._save(record)
        return record

    def apply(self, candidate: bytes, extension: bytes, *, fail_at: str | None = None) -> dict:
        record = self._journal()
        require(record['status'] == 'PREPARED', 'TRANSACTION_NOT_PREPARED')
        require(sha(_read(self.main)) == record['original_sha256'], 'INSTALLED_SOURCE_DRIFT')
        require(sha(_read(self.backup)) == record['original_sha256'], 'BACKUP_HASH_MISMATCH')
        require(sha(candidate) == record['candidate_sha256'] and
                sha(extension) == record['extension_sha256'], 'PAYLOAD_HASH_MISMATCH')
        require(not self.extension.exists() and not self.extension.is_symlink(),
                'EXTENSION_ALREADY_EXISTS')
        record['status'] = 'APPLYING'
        self._save(record)
        if fail_at == 'after_journal':
            raise RuntimeError('SIMULATED_CRASH')
        _write_atomic(self.extension, extension)
        if fail_at == 'after_extension':
            raise RuntimeError('SIMULATED_CRASH')
        _write_atomic(self.main, candidate, record['original_mode'])
        if fail_at == 'after_main':
            raise RuntimeError('SIMULATED_CRASH')
        record['status'] = 'APPLIED'
        self._save(record)
        return record

    def recover(self) -> dict:
        record = self._journal()
        require(record['status'] in ('PREPARED', 'APPLYING', 'APPLIED'),
                'TRANSACTION_NOT_RECOVERABLE')
        original = _read(self.backup)
        require(sha(original) == record['original_sha256'], 'BACKUP_HASH_MISMATCH')
        # Do not destroy unexpected concurrent changes during recovery.
        current = _read(self.main)
        require(sha(current) in (record['original_sha256'], record['candidate_sha256']),
                'UNEXPECTED_MAIN_CHANGE')
        if self.extension.exists() or self.extension.is_symlink():
            require(sha(_read(self.extension)) == record['extension_sha256'],
                    'UNEXPECTED_EXTENSION_CHANGE')
        if sha(current) != record['original_sha256']:
            _write_atomic(self.main, original, record['original_mode'])
        if self.extension.exists():
            self.extension.unlink()
            _sync_dir(self.root)
        record['status'] = 'ROLLED_BACK'
        self._save(record)
        return record

    def mark_health_verified_for_lab(self) -> dict:
        """Only a lab marker. Not an operational service-health assertion."""
        record = self._journal()
        require(record['status'] == 'APPLIED', 'NOT_APPLIED')
        require(sha(_read(self.main)) == record['candidate_sha256'] and
                sha(_read(self.extension)) == record['extension_sha256'],
                'APPLIED_BYTES_CHANGED')
        record['status'] = 'COMMITTED'
        self._save(record)
        return record
