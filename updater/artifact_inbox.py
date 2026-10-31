"""Unprivileged, host-shell-free transport for FieldWork canary release artifacts.

This is a staging-only library. It neither executes nor extracts received bytes,
nor touches a running MCP, Docker, systemd, or /opt/fieldwork. A separately
qualified and locally activated MCP adapter may expose its bounded operations.
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

HEX32 = re.compile(r"[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
MAX_ARTIFACT = 32 * 1024 * 1024
MAX_CHUNK = 128 * 1024
MAX_TRANSFERS = 8
SCHEMA = 1
STATE = Path('.local/state/fieldwork-pi-mcp/artifact-inbox')


class InboxDenied(RuntimeError):
    """Refuse unsafe or inconsistent transfer state without mutating it."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise InboxDenied(reason)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir() -> Path:
    require(os.geteuid() != 0, 'ROOT_DENIED')
    home = Path.home()
    base = home / STATE
    # No caller-supplied filesystem destination. This cannot become a production path.
    current = home
    require(current.is_dir() and not current.is_symlink(), 'HOME_UNSAFE')
    for piece in STATE.parts:
        current = current / piece
        require(not current.is_symlink(), 'SYMLINK_DENIED')
        if not current.exists():
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
        require(current.is_dir() and not current.is_symlink(), 'DIR_UNSAFE')
        st = current.stat()
        require(st.st_uid == os.geteuid() and not (st.st_mode & 0o022),
                'DIR_PERMISSIONS_DENIED')
    require(not (base.stat().st_mode & 0o077), 'INBOX_NOT_PRIVATE')
    return base


def _valid_id(transfer_id: str) -> None:
    require(type(transfer_id) is str and HEX32.fullmatch(transfer_id) is not None,
            'TRANSFER_ID_INVALID')


def _owned_file(path: Path, *, max_size: int = MAX_ARTIFACT) -> bytes:
    require(path.is_file() and not path.is_symlink(), 'TRANSFER_FILE_UNSAFE')
    st = path.stat()
    require(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) & 0o077 == 0,
            'TRANSFER_FILE_PERMISSIONS_DENIED')
    require(st.st_size <= max_size, 'TRANSFER_FILE_TOO_LARGE')
    return path.read_bytes()


def _transfer(transfer_id: str) -> Path:
    _valid_id(transfer_id)
    root = _dir() / transfer_id
    require(root.is_dir() and not root.is_symlink(), 'TRANSFER_NOT_FOUND')
    st = root.stat()
    require(st.st_uid == os.geteuid() and not (st.st_mode & 0o077), 'TRANSFER_DIR_UNSAFE')
    return root


def _record(root: Path) -> dict[str, Any]:
    try:
        data = json.loads(_owned_file(root / 'record.json', max_size=2048))
    except (UnicodeError, ValueError) as exc:
        raise InboxDenied('RECORD_INVALID') from exc
    require(type(data) is dict and set(data) == {
        'schema', 'transfer_id', 'size', 'sha256', 'kind'
    }, 'RECORD_SCHEMA_DENIED')
    require(data['schema'] == SCHEMA and type(data['schema']) is int,
            'RECORD_SCHEMA_DENIED')
    require(data['kind'] == 'fieldwork-canary', 'ARTIFACT_KIND_DENIED')
    require(type(data['size']) is int and 0 < data['size'] <= MAX_ARTIFACT,
            'RECORD_SIZE_INVALID')
    require(type(data['sha256']) is str and HEX64.fullmatch(data['sha256']) is not None,
            'RECORD_HASH_INVALID')
    require(root.name == data['transfer_id'], 'RECORD_TRANSFER_MISMATCH')
    return data


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                 getattr(os, 'O_NOFOLLOW', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        # fdopen closes file on normal and exceptional exit
        pass


def _lock(root: Path):
    path = root / 'lock'
    require(not path.is_symlink(), 'LOCK_SYMLINK_DENIED')
    fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
    st = os.fstat(fd)
    try:
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and
                stat.S_IMODE(st.st_mode) & 0o077 == 0, 'LOCK_PERMISSIONS_DENIED')
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd
    except Exception:
        os.close(fd)
        raise


def begin(transfer_id: str, size: int, sha256: str) -> dict[str, Any]:
    """Create one immutable upload slot; IDs cannot be reused or overwritten."""
    _valid_id(transfer_id)
    require(type(size) is int and 0 < size <= MAX_ARTIFACT, 'ARTIFACT_SIZE_DENIED')
    require(type(sha256) is str and HEX64.fullmatch(sha256) is not None,
            'ARTIFACT_HASH_INVALID')
    base = _dir()
    tombstone = base / ('retired-' + transfer_id + '.json')
    require(not tombstone.exists() and not tombstone.is_symlink(),
            'TRANSFER_ID_RETIRED')
    # Only active 32-hex transfer directories count toward concurrent slots.
    # Retired transfers retain an immutable tombstone, never a reusable ID.
    active = [p for p in base.iterdir() if HEX32.fullmatch(p.name)
              and (p.is_dir() or p.is_symlink())]
    require(len(active) < MAX_TRANSFERS, 'INBOX_CAPACITY_REACHED')
    root = base / transfer_id
    try:
        root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise InboxDenied('TRANSFER_ALREADY_EXISTS') from exc
    # An interrupted begin is never accepted as an upload; fail closed.
    data = {'schema': SCHEMA, 'transfer_id': transfer_id, 'size': size,
            'sha256': sha256, 'kind': 'fieldwork-canary'}
    _write_exclusive(root / 'lock', b'')
    _write_exclusive(root / 'record.json',
                     (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode())
    _write_exclusive(root / 'payload.part', b'')
    _sync_dir(root)
    _sync_dir(base)
    return {'status': 'UPLOAD_STARTED', 'transfer_id': transfer_id,
            'received_bytes': 0, 'expected_bytes': size, 'executable': False}


def _content_state(root: Path, record: dict[str, Any]) -> tuple[Path, int, str]:
    final = root / 'artifact.bin'
    partial = root / 'payload.part'
    require(not final.is_symlink() and not partial.is_symlink(), 'PAYLOAD_SYMLINK_DENIED')
    require(not (final.exists() and partial.exists()), 'AMBIGUOUS_TRANSFER_STATE')
    if final.exists():
        data = _owned_file(final)
        require(len(data) == record['size'] and _digest(data) == record['sha256'],
                'VERIFIED_ARTIFACT_TAMPERED')
        return final, len(data), 'VERIFIED'
    data = _owned_file(partial)
    require(len(data) <= record['size'], 'PAYLOAD_OVERSIZE')
    return partial, len(data), 'UPLOADING'


def append(transfer_id: str, offset: int, chunk_base64: str) -> dict[str, Any]:
    """Append exactly one ordered chunk; identical retries are safe."""
    require(type(offset) is int and offset >= 0, 'OFFSET_INVALID')
    require(type(chunk_base64) is str and 0 < len(chunk_base64) <= 180_000,
            'CHUNK_LENGTH_DENIED')
    try:
        data = base64.b64decode(chunk_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InboxDenied('CHUNK_ENCODING_INVALID') from exc
    require(0 < len(data) <= MAX_CHUNK, 'CHUNK_SIZE_DENIED')
    root = _transfer(transfer_id)
    fd = _lock(root)
    try:
        record = _record(root)
        path, received, state = _content_state(root, record)
        require(state == 'UPLOADING', 'ALREADY_VERIFIED')
        require(offset <= received, 'OUT_OF_ORDER_CHUNK')
        require(offset + len(data) <= record['size'], 'ARTIFACT_OVERRUN')
        if offset < received:
            require(offset + len(data) <= received, 'OVERLAPPING_CHUNK_DENIED')
            with path.open('rb') as f:
                f.seek(offset)
                require(f.read(len(data)) == data, 'REPLAY_DATA_MISMATCH')
        else:
            handle = os.open(path, os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0))
            try:
                require(os.fstat(handle).st_size == received, 'CONCURRENT_WRITE_DENIED')
                os.lseek(handle, received, os.SEEK_SET)
                view = memoryview(data)
                while view:
                    count = os.write(handle, view)
                    require(count > 0, 'WRITE_FAILED')
                    view = view[count:]
                os.fsync(handle)
            finally:
                os.close(handle)
            received += len(data)
        return {'status': 'UPLOADING', 'transfer_id': transfer_id,
                'received_bytes': received, 'expected_bytes': record['size'],
                'executable': False}
    finally:
        os.close(fd)


def finalize(transfer_id: str) -> dict[str, Any]:
    """Publish a hash-verified, inert byte artifact. Never deploy or execute it."""
    root = _transfer(transfer_id)
    fd = _lock(root)
    try:
        record = _record(root)
        path, received, state = _content_state(root, record)
        if state == 'UPLOADING':
            require(received == record['size'], 'UPLOAD_INCOMPLETE')
            require(_digest(_owned_file(path)) == record['sha256'], 'ARTIFACT_HASH_MISMATCH')
            os.replace(path, root / 'artifact.bin')
            _sync_dir(root)
        return {'status': 'VERIFIED_NOT_DEPLOYED', 'transfer_id': transfer_id,
                'sha256': record['sha256'], 'size': received, 'executable': False,
                'production_modified': False, 'mcp_modified': False}
    finally:
        os.close(fd)


def status(transfer_id: str) -> dict[str, Any]:
    root = _transfer(transfer_id)
    fd = _lock(root)
    try:
        record = _record(root)
        _, received, state = _content_state(root, record)
        return {'status': state, 'transfer_id': transfer_id,
                'received_bytes': received, 'expected_bytes': record['size'],
                'sha256': record['sha256'], 'executable': False}
    finally:
        os.close(fd)
