#!/usr/bin/env python3
"""One-time, user-approved FieldWork Pi updater bootstrap.

Installs a read-only GitHub staging helper alongside the running MCP.
Does NOT change MCP files, production, Docker, systemd, or tunnels.
No remote shell or unattended installation is enabled by this bootstrap.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

OWNER = 'misssska'
REPO = 'fieldwork-pi-mcp'
FILES = ('updater/stage_release.py', 'updater/compatibility.py', 'updater/async_overlay.py', 'updater/qualification.py', 'updater/activation_plan.py')
COMMIT_RE = re.compile(r'[a-f0-9]{40}\Z')
HASH_RE = re.compile(r'[a-f0-9]{64}\Z')
MAX_FILE = 120_000
MAX_MANIFEST = 16_000


class Stop(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Stop('REDIRECT_DENIED')


def fetch(commit: str, path: str, limit: int) -> bytes:
    if path not in FILES and path != 'bootstrap/manifest.json':
        raise Stop('DOWNLOAD_PATH_DENIED')
    url = f'https://raw.githubusercontent.com/{OWNER}/{REPO}/{commit}/{path}'
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(urllib.request.Request(url, headers={'User-Agent': 'fieldwork-pi-bootstrap/1'}), timeout=20) as response:
        if response.status != 200:
            raise Stop('HTTP_STATUS_DENIED')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise Stop('DOWNLOAD_TOO_LARGE')
    return data


def parse_manifest(data: bytes) -> dict[str, str]:
    try:
        obj = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise Stop('MANIFEST_INVALID_JSON') from exc
    if type(obj) is not dict or set(obj) != {'schema', 'files'} or type(obj['schema']) is not int or obj['schema'] != 1:
        raise Stop('MANIFEST_INVALID_SCHEMA')
    entries = obj['files']
    if type(entries) is not list or len(entries) != len(FILES):
        raise Stop('MANIFEST_INVALID_COUNT')
    result: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {'path', 'sha256'}:
            raise Stop('MANIFEST_INVALID_ENTRY')
        name, digest = entry['path'], entry['sha256']
        if type(name) is not str or name not in FILES or name in result:
            raise Stop('MANIFEST_UNSAFE_PATH')
        if type(digest) is not str or HASH_RE.fullmatch(digest) is None:
            raise Stop('MANIFEST_INVALID_HASH')
        result[name] = digest
    if set(result) != set(FILES):
        raise Stop('MANIFEST_MISSING_FILE')
    return result


def ensure_safe_directory(directory: Path) -> None:
    for part in (directory, *directory.parents):
        if part.is_symlink():
            raise Stop('SYMLINK_DIRECTORY_DENIED')
    if directory.exists():
        if not directory.is_dir() or directory.stat().st_uid != os.getuid():
            raise Stop('DIRECTORY_NOT_OWNED')
        if directory.stat().st_mode & 0o022:
            raise Stop('DIRECTORY_WRITABLE_BY_OTHERS')
    else:
        directory.mkdir(mode=0o700, parents=True)
        directory.chmod(0o700)


def prepare(commit: str, manifest_hash: str, root: Path) -> dict:
    if COMMIT_RE.fullmatch(commit) is None or HASH_RE.fullmatch(manifest_hash) is None:
        raise Stop('PINNED_COMMIT_AND_MANIFEST_REQUIRED')
    if os.geteuid() == 0:
        raise Stop('DO_NOT_RUN_AS_ROOT')
    root = root.expanduser().absolute()
    # Fixed scope; never allow an arbitrary caller-selected production directory.
    expected_root = Path.home() / '.local/share/fieldwork-pi-mcp/update-agent'
    if root != expected_root:
        raise Stop('DESTINATION_DENIED')
    ensure_safe_directory(root)
    manifest_bytes = fetch(commit, 'bootstrap/manifest.json', MAX_MANIFEST)
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_hash:
        raise Stop('MANIFEST_HASH_MISMATCH')
    expected = parse_manifest(manifest_bytes)
    files: dict[str, bytes] = {}
    for name in FILES:
        data = fetch(commit, name, MAX_FILE)
        if hashlib.sha256(data).hexdigest() != expected[name]:
            raise Stop('FILE_HASH_MISMATCH:' + name)
        try:
            ast.parse(data.decode('utf-8'), filename=name)
        except (SyntaxError, UnicodeError) as exc:
            raise Stop('INVALID_PYTHON:' + name) from exc
        files[name] = data
    dest = root / (commit + '-' + manifest_hash[:12])
    if dest.exists() or dest.is_symlink():
        raise Stop('VERSION_ALREADY_STAGED')
    tmp = Path(tempfile.mkdtemp(prefix='.new-', dir=root))
    try:
        for name, data in files.items():
            path = tmp / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            path.chmod(0o600)
        receipt = {'status': 'UPDATER_STAGED_ONLY', 'commit': commit,
                   'manifest_sha256': manifest_hash,
                   'created_at_utc': datetime.now(timezone.utc).isoformat(),
                   'files': list(FILES), 'production_modified': False,
                   'mcp_modified': False, 'tunnel_restarted': False}
        with (tmp / 'receipt.json').open('x', encoding='utf-8') as handle:
            json.dump(receipt, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        (tmp / 'receipt.json').chmod(0o600)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    return {'status': 'UPDATER_STAGED_ONLY', 'path': str(dest),
            'production_modified': False, 'mcp_modified': False,
            'tunnel_restarted': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.commit, args.manifest_sha256,
                         Path.home() / '.local/share/fieldwork-pi-mcp/update-agent')
    except (Stop, OSError, urllib.error.URLError) as exc:
        print('BOOTSTRAP_FAILED=' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
