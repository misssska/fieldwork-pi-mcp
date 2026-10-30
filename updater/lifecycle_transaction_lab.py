"""Offline multi-file MCP upgrade transaction *rehearsal*.

Safety boundary: only a newly created, user-owned temp directory matching
/tmp/fieldwork-mcp-lifecycle-lab-*/mcp. No command execution, network, systemd,
Docker, production files, local approval issuance, or activation entrypoint.
The intended runtime file set is fixed; overlays/manifest never get installed.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

MAIN = 'fieldwork_mcp.py'
MODULES = ('stage_async.py', 'stage_inspect.py', 'stage_start_async.py')
FILES = (MAIN, *MODULES)
HASH = re.compile(r'[0-9a-f]{64}\Z')
MAX_BYTES = 1_000_000
STATES = frozenset({'PREPARED', 'APPLYING', 'APPLIED', 'ROLLED_BACK', 'COMMITTED'})


class LifecycleTransactionError(RuntimeError):
    pass


def _must(ok: bool, code: str) -> None:
    if not ok:
        raise LifecycleTransactionError(code)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _owned_directory(path: Path) -> None:
    _must(path.is_dir() and not path.is_symlink(), 'LAB_DIRECTORY_UNSAFE')
    info = path.stat()
    _must(info.st_uid == os.getuid() and not info.st_mode & 0o022,
          'LAB_DIRECTORY_PERMISSIONS_UNSAFE')


def _lab_root(root: Path) -> None:
    base = Path(tempfile.gettempdir()).resolve()
    _must(isinstance(root, Path) and root.is_absolute() and root.parent.parent == base
          and root.name == 'mcp'
          and re.fullmatch(r'fieldwork-mcp-lifecycle-lab-[a-zA-Z0-9_-]+',
                           root.parent.name) is not None,
          'NON_LAB_DESTINATION_DENIED')
    _owned_directory(root.parent)
    _owned_directory(root)


def _read(path: Path) -> bytes:
    _must(not path.is_symlink() and path.is_file(), 'LAB_FILE_UNSAFE')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        _must(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
              and info.st_uid == os.getuid() and not info.st_mode & 0o022,
              'LAB_FILE_PERMISSIONS_UNSAFE')
        _must(0 < info.st_size <= MAX_BYTES, 'LAB_FILE_SIZE_DENIED')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            result = stream.read(MAX_BYTES + 1)
        _must(len(result) == info.st_size, 'LAB_FILE_CHANGED_DURING_READ')
        return result
    finally:
        os.close(fd)


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    _must(type(content) is bytes and 0 < len(content) <= MAX_BYTES,
          'LAB_PAYLOAD_INVALID')
    fd, name = tempfile.mkstemp(prefix='.lifecycle-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        _sync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


class LifecycleLabTransaction:
    """Rehearse atomic replacement and recovery; deliberately cannot deploy."""

    def __init__(self, root: Path):
        _lab_root(root)
        self.root = root
        self.journal = root / '.lifecycle-transaction.json'
        self.backup = root / '.lifecycle-original-backup'
        self.lock = root / '.lifecycle-transaction.lock'

    @contextmanager
    def _locked(self):
        _lab_root(self.root)
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(self.lock, flags, 0o600)
        try:
            info = os.fstat(fd)
            _must(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                  and info.st_nlink == 1 and not info.st_mode & 0o077,
                  'LAB_LOCK_UNSAFE')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _record(self) -> dict:
        try:
            record = json.loads(_read(self.journal))
        except (UnicodeError, ValueError) as exc:
            raise LifecycleTransactionError('LAB_JOURNAL_INVALID') from exc
        _must(type(record) is dict and set(record) == {
            'schema', 'state', 'original_sha256', 'original_mode', 'payload_sha256'
        }, 'LAB_JOURNAL_SCHEMA_DENIED')
        _must(type(record['schema']) is int and record['schema'] == 1
              and record['state'] in STATES, 'LAB_JOURNAL_STATE_DENIED')
        _must(type(record['original_sha256']) is str
              and HASH.fullmatch(record['original_sha256']) is not None,
              'LAB_ORIGINAL_HASH_DENIED')
        _must(type(record['original_mode']) is int
              and 0 <= record['original_mode'] <= 0o777
              and record['original_mode'] & 0o022 == 0,
              'LAB_ORIGINAL_MODE_DENIED')
        pins = record['payload_sha256']
        _must(type(pins) is dict and set(pins) == set(FILES),
              'LAB_PAYLOAD_SET_DENIED')
        for digest in pins.values():
            _must(type(digest) is str and HASH.fullmatch(digest) is not None,
                  'LAB_PAYLOAD_HASH_DENIED')
        return record

    def _save(self, record: dict) -> None:
        _atomic_write(self.journal,
                      (json.dumps(record, sort_keys=True) + '\n').encode('utf-8'))

    def prepare(self, payloads: dict[str, bytes], expected_original_sha256: str) -> dict:
        """Create durable backup + receipt without changing executable sources."""
        with self._locked():
            _must(not self.journal.exists() and not self.journal.is_symlink(),
                  'LAB_ALREADY_PREPARED')
            _must(not self.backup.exists() and not self.backup.is_symlink(),
                  'LAB_BACKUP_ALREADY_EXISTS')
            _must(type(payloads) is dict and set(payloads) == set(FILES),
                  'LAB_PAYLOAD_SET_DENIED')
            _must(type(expected_original_sha256) is str and
                  HASH.fullmatch(expected_original_sha256) is not None,
                  'LAB_ORIGINAL_HASH_DENIED')
            for name in MODULES:
                path = self.root / name
                _must(not path.exists() and not path.is_symlink(),
                      'LAB_MODULE_ALREADY_PRESENT')
            for value in payloads.values():
                _must(type(value) is bytes and 0 < len(value) <= MAX_BYTES,
                      'LAB_PAYLOAD_INVALID')
            main_path = self.root / MAIN
            original = _read(main_path)
            _must(_sha(original) == expected_original_sha256,
                  'LAB_ORIGINAL_SOURCE_DRIFT')
            _must(payloads[MAIN] != original, 'LAB_NO_SOURCE_CHANGE')
            mode = stat.S_IMODE(main_path.stat().st_mode)
            _atomic_write(self.backup, original)
            record = {'schema': 1, 'state': 'PREPARED',
                      'original_sha256': _sha(original), 'original_mode': mode,
                      'payload_sha256': {name: _sha(payloads[name]) for name in FILES}}
            self._save(record)
            return self._result('LAB_PREPARED', record)

    def apply(self, payloads: dict[str, bytes], *, fail_at: str | None = None) -> dict:
        with self._locked():
            record = self._record()
            _must(record['state'] == 'PREPARED', 'LAB_NOT_PREPARED')
            _must(type(payloads) is dict and set(payloads) == set(FILES),
                  'LAB_PAYLOAD_SET_DENIED')
            for name in FILES:
                _must(type(payloads[name]) is bytes and
                      _sha(payloads[name]) == record['payload_sha256'][name],
                      'LAB_PAYLOAD_DRIFT')
            _must(_sha(_read(self.root / MAIN)) == record['original_sha256'],
                  'LAB_ORIGINAL_SOURCE_DRIFT')
            _must(_sha(_read(self.backup)) == record['original_sha256'],
                  'LAB_BACKUP_DRIFT')
            for name in MODULES:
                path = self.root / name
                _must(not path.exists() and not path.is_symlink(),
                      'LAB_MODULE_ALREADY_PRESENT')
            record['state'] = 'APPLYING'
            self._save(record)
            self._crash(fail_at, 'after_journal')
            for name in MODULES:
                _atomic_write(self.root / name, payloads[name])
                self._crash(fail_at, 'after_' + name)
            _atomic_write(self.root / MAIN, payloads[MAIN], record['original_mode'])
            self._crash(fail_at, 'after_main')
            record['state'] = 'APPLIED'
            self._save(record)
            self._crash(fail_at, 'after_applied')
            return self._result('LAB_APPLIED_NOT_ACTIVATED', record)

    @staticmethod
    def _crash(actual: str | None, expected: str) -> None:
        if actual == expected:
            raise RuntimeError('SIMULATED_CRASH:' + expected)

    def recover(self) -> dict:
        """Restore original source on any incomplete rehearsal, fail on tamper."""
        with self._locked():
            record = self._record()
            _must(record['state'] in ('PREPARED', 'APPLYING', 'APPLIED'),
                  'LAB_NOT_RECOVERABLE')
            original = _read(self.backup)
            _must(_sha(original) == record['original_sha256'],
                  'LAB_BACKUP_DRIFT')
            main = self.root / MAIN
            main_hash = _sha(_read(main))
            _must(main_hash in (record['original_sha256'],
                               record['payload_sha256'][MAIN]),
                  'LAB_UNEXPECTED_MAIN_CHANGE')
            # Verify *all* files before doing any destructive rollback step.
            for name in MODULES:
                path = self.root / name
                if path.exists() or path.is_symlink():
                    _must(_sha(_read(path)) == record['payload_sha256'][name],
                          'LAB_UNEXPECTED_MODULE_CHANGE')
            if main_hash != record['original_sha256']:
                _atomic_write(main, original, record['original_mode'])
            for name in MODULES:
                path = self.root / name
                if path.exists():
                    path.unlink()
                    _sync_dir(self.root)
            record['state'] = 'ROLLED_BACK'
            self._save(record)
            return self._result('LAB_ROLLED_BACK', record)

    def mark_lab_verified(self) -> dict:
        """Local byte-integrity marker; emphatically NOT system health."""
        with self._locked():
            record = self._record()
            _must(record['state'] == 'APPLIED', 'LAB_NOT_APPLIED')
            for name in FILES:
                _must(_sha(_read(self.root / name)) == record['payload_sha256'][name],
                      'LAB_APPLIED_BYTES_CHANGED')
            record['state'] = 'COMMITTED'
            self._save(record)
            return self._result('LAB_BYTES_VERIFIED_ONLY', record)

    @staticmethod
    def _result(status: str, record: dict) -> dict:
        return {'status': status, 'state': record['state'],
                'activation_authorized': False, 'production_modified': False,
                'mcp_modified': False, 'tunnel_restarted': False}
