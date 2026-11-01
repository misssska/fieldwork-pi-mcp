#!/usr/bin/env python3
"""Locally approved M5 R7-only canary launcher for the exact inert Pi inbox ZIP.

No host shell capability is exposed to MCP. An admin explicitly invokes this
program locally. This is NOT a remote deployment tool; it never edits
production or the existing 18081 stage. It only prepares under stage-v06 and
invokes the pinned M5 R7 package's own fail-closed test/isolated launcher.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import zipfile

ARCHIVE_SHA = '71c90075deaedced316f6428a0b4325b68ab7f164b8be5d30547c2f68c8b4374'
ARCHIVE_SIZE = 40776
ENTRY_PREFIX = 'FieldWork_Paritas_M5/'
ENTRY_COUNT = 20
MANIFEST_COUNT = 19
STATE_REL = '.local/state/fieldwork-pi-mcp-v03/stage-v06'
M4_DIR = 'parity-m4.d2DIn9Zr'
BUNDLE_DIR = '.m5r7-verified-bundle-' + ARCHIVE_SHA[:16]
PROJ = 'fieldwork-parity-m5-r7'
TEST_PROJ = 'fieldwork-parity-m5-r7-test'
PORT = 18085
IP = '192.168.22.13'
MAX_INDIVIDUAL_FILE = 250_000


def deny(reason: str) -> None:
    print('M5_R7_LOCAL_LAUNCH_BLOCKED:' + reason, flush=True)
    raise SystemExit(2)


def filehash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(64 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def locate_archive(home: Path) -> Path:
    """Read-only scan of *user-local* state/share, never of /opt or other users."""
    matches = []
    for root in (home / '.local/state', home / '.local/share'):
        if not root.is_dir() or root.is_symlink():
            continue
        for dirname, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', '.venv', '__pycache__'}
                       and not (Path(dirname) / d).is_symlink()]
            for name in files:
                path = Path(dirname) / name
                try:
                    if path.is_symlink() or not path.is_file() or path.stat().st_size != ARCHIVE_SIZE:
                        continue
                    if filehash(path) == ARCHIVE_SHA:
                        matches.append(path)
                        if len(matches) > 1:
                            deny('MORE_THAN_ONE_EXACT_INBOX_ZIP')
                except OSError:
                    continue
    if len(matches) != 1:
        deny('VERIFIED_INBOX_ZIP_NOT_FOUND_IN_USER_LOCAL_STATE')
    print('PASS exact_inert_zip_found_without_scp')
    return matches[0]


def check_manifest(z: zipfile.ZipFile) -> dict[str, str]:
    infos = z.infolist()
    names = [info.filename for info in infos]
    if len(names) != ENTRY_COUNT or len(names) != len(set(names)):
        deny('ZIP_MEMBER_COUNT_OR_DUPLICATION')
    if any(not n.startswith(ENTRY_PREFIX) or n.endswith('/') for n in names):
        deny('ZIP_MEMBER_ROOT_OR_DIRECTORY')
    for inf in infos:
        rel = inf.filename[len(ENTRY_PREFIX):]
        parts = PurePosixPath(rel).parts
        mode = inf.external_attr >> 16
        if (not parts or len(parts) != 1 or parts[0] in ('.', '..') or '\\' in rel
                or inf.file_size > MAX_INDIVIDUAL_FILE or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
            deny('ZIP_MEMBER_UNSAFE')
    manifest_member = ENTRY_PREFIX + 'manifest.json'
    if manifest_member not in names:
        deny('ZIP_MANIFEST_MISSING')
    try:
        manifest = json.loads(z.read(manifest_member))
    except (ValueError, UnicodeDecodeError, RuntimeError):
        deny('ZIP_MANIFEST_MALFORMED')
    if (not isinstance(manifest, dict) or len(manifest) != MANIFEST_COUNT
            or set(manifest) != {n[len(ENTRY_PREFIX):] for n in names} - {'manifest.json'}):
        deny('ZIP_MANIFEST_MEMBER_DRIFT')
    for name, digest in manifest.items():
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            deny('ZIP_MANIFEST_HASH_INVALID')
        if hashlib.sha256(z.read(ENTRY_PREFIX + name)).hexdigest() != digest:
            deny('ZIP_SOURCE_SHA256_MISMATCH')
    for mandatory in ('verify.py', 'launch_canary.sh', 'integrate.py', 'm5r5_test_gate.py', 'test_m5r7_regressions.py'):
        if mandatory not in manifest:
            deny('ZIP_REQUIRED_MEMBER_MISSING')
    print('PASS bundle_19_files_manifest_SHA256')
    return manifest


def verified_bundle_path(home: Path, archive: Path) -> Path:
    state = home / STATE_REL
    if not state.is_dir() or state.is_symlink():
        deny('EXACT_STAGE_V06_ROOT_MISSING')
    if (not (state / M4_DIR).is_dir()) or (state / M4_DIR).is_symlink():
        deny('M4_BASE_MISSING_OR_SYMLINK')
    prepared = state / BUNDLE_DIR
    with zipfile.ZipFile(archive) as z:
        manifest = check_manifest(z)
        if prepared.exists() or prepared.is_symlink():
            if prepared.is_symlink() or not prepared.is_dir():
                deny('BUNDLE_DIR_DRIFT')
            root = prepared / 'FieldWork_Paritas_M5'
            for name, digest in manifest.items():
                p = root / name
                if not p.is_file() or p.is_symlink() or filehash(p) != digest:
                    deny('EXISTING_BUNDLE_TAMPERED')
            if not (root / 'manifest.json').is_file() or (root / 'manifest.json').is_symlink():
                deny('EXISTING_BUNDLE_MANIFEST_MISSING')
            if hashlib.sha256((root / 'manifest.json').read_bytes()).digest() != hashlib.sha256(z.read(ENTRY_PREFIX + 'manifest.json')).digest():
                deny('EXISTING_BUNDLE_MANIFEST_DRIFT')
        else:
            tmp = Path(tempfile.mkdtemp(prefix='.m5r7-preparing-', dir=state))
            try:
                root = tmp / 'FieldWork_Paritas_M5'
                root.mkdir(mode=0o700)
                for inf in z.infolist():
                    dest = root / inf.filename[len(ENTRY_PREFIX):]
                    # All member names prevalidated and source ZIP SHA-pinned.
                    with z.open(inf) as source, dest.open('xb') as target:
                        shutil.copyfileobj(source, target)
                    dest.chmod(0o600)
                tmp.rename(prepared)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
    print('PASS stage_only_bundle_prepared_replay_safe')
    return prepared / 'FieldWork_Paritas_M5'


def checked_subprocess(argv: list[str], *, cwd: Path | None = None, env: dict | None = None) -> str:
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, check=False, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        deny('DOCKER_READ_ONLY_PREFLIGHT_UNAVAILABLE')
    if p.returncode != 0:
        deny('DOCKER_READ_ONLY_PREFLIGHT_FAILED')
    return p.stdout


def check_compose(base: Path) -> None:
    env = os.environ.copy()
    env['STAGE_HTTP_PORT'] = str(PORT)
    cfg = checked_subprocess(['docker', 'compose', '-p', PROJ,
                              '--env-file', str(base / '.env.stage'),
                              '-f', str(base / 'docker-compose.stage.yml'),
                              'config', '--format', 'json'], cwd=base, env=env)
    try:
        doc = json.loads(cfg)
    except json.JSONDecodeError:
        deny('STAGE_COMPOSE_JSON_INVALID')
    services = doc.get('services', {})
    if set(services) != {'api', 'db', 'nginx'}:
        deny('STAGE_COMPOSE_UNEXPECTED_SERVICES')
    if any(x.get('external') for x in doc.get('networks', {}).values()):
        deny('STAGE_COMPOSE_EXTERNAL_NETWORK')
    if any(x.get('external') for x in doc.get('volumes', {}).values()):
        deny('STAGE_COMPOSE_EXTERNAL_VOLUME')
    for name, svc in services.items():
        if svc.get('privileged') or svc.get('network_mode') or svc.get('pid') == 'host' or svc.get('ipc') == 'host' or svc.get('container_name') or svc.get('devices') or svc.get('cap_add') or svc.get('extra_hosts') or svc.get('secrets'):
            deny('STAGE_COMPOSE_PRIVILEGED_OR_HOST_SCOPE:' + name)
        for vol in svc.get('volumes', []):
            if not isinstance(vol, dict) or vol.get('type') not in ('volume', 'tmpfs'):
                deny('STAGE_COMPOSE_BIND_OR_UNKNOWN_VOLUME:' + name)
        ports = svc.get('ports', [])
        if name != 'nginx' and ports:
            deny('STAGE_COMPOSE_UNEXPECTED_PUBLIC_PORT:' + name)
        if name == 'nginx':
            if len(ports) != 1 or str(ports[0].get('published')) != str(PORT) or ports[0].get('host_ip') != IP:
                deny('STAGE_COMPOSE_PORT_18085_POLICY')
    # The API must reach ONLY the private Compose database service.
    api_env = services['api'].get('environment', {})
    if not isinstance(api_env, dict) or 'DATABASE_URL' not in api_env:
        deny('STAGE_COMPOSE_DATABASE_URL_MISSING')
    try:
        parsed = urlsplit(api_env['DATABASE_URL'])
        if not parsed.scheme.startswith('postgresql') or parsed.hostname != 'db' or parsed.port != 5432:
            deny('STAGE_COMPOSE_DATABASE_OUTSIDE_ISOLATED_PROJECT')
    except (ValueError, TypeError):
        deny('STAGE_COMPOSE_DATABASE_URL_INVALID')
    print('PASS compose_scope_only_private_db_no_host_mount_or_external_network')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-only', action='store_true', help='SHA-verify and unpack inert M5 R7 bundle in isolated stage-v06 only')
    group.add_argument('--launch', action='store_true', help='LOCAL ADMIN APPROVAL: full tests then canary on 18085')
    args = ap.parse_args()
    if os.geteuid() == 0:
        deny('ROOT_EXECUTION_FORBIDDEN')
    home = Path.home().resolve()
    if os.stat(home).st_uid != os.geteuid():
        deny('HOME_OWNER_MISMATCH')
    archive = locate_archive(home)
    if filehash(archive) != ARCHIVE_SHA:
        deny('INBOX_SHA256_DRIFT')
    package = verified_bundle_path(home, archive)
    if args.prepare_only:
        print('M5_R7_PREPARED_ONLY_NO_DOCKER_OR_CANARY_ACTION')
        return
    base = home / STATE_REL / M4_DIR
    for path in ('docker-compose.stage.yml', '.env.stage'):
        if not (base / path).is_file() or (base / path).is_symlink():
            deny('M4_COMPOSE_OR_ENV_MISSING_OR_SYMLINK')
    check_compose(base)
    print('M5_R7_LOCAL_LAUNCH_REQUESTED_FULL_TESTS_BEFORE_18085', flush=True)
    # The bundled launcher checks exact M4 SHA lineage, M5 project absence,
    # frontend TS/ESLint/all Vitest, backend pytest/migrations and HTTP health.
    # No production Docker project or pre-existing 18081 stage is targeted.
    result = subprocess.run(['bash', str(package / 'launch_canary.sh')], cwd=package,
                            env=os.environ.copy(), check=False)
    if result.returncode:
        print('M5_R7_LOCAL_TEST_OR_CANARY_FAILED_NO_RELEASE_APPROVAL', flush=True)
        raise SystemExit(result.returncode)
    print('M5_R7_LOCAL_CANARY_LAUNCH_COMPLETED_VERIFY_UI_AT_HTTP_192.168.22.13_18085', flush=True)


if __name__ == '__main__':
    main()
