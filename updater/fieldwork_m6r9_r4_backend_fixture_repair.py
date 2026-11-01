#!/usr/bin/env python3
"""M6 R9 R4: one-file fail-closed isolated backend-test fixture correction.

Changes only the pinned M6 candidate server/tests/test_account_m6.py,
not code, prod, R8 or 18090. Runs isolated PostgreSQL and full 95 backend tests.
Use only with local host-admin approval. Never grants remote host shell to MCP.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

HOME = Path.home()
STATE = HOME / '.local/state/fieldwork-pi-mcp-v03/stage-v06'
BASE = STATE / 'parity-m5.Krm2sA3i'
CANDIDATE = STATE / 'parity-m6._sdfbhky'
TESTFILE_REL = 'server/tests/test_account_m6.py'
FRONT_TEST_REL = 'frontend/src/components/Login.test.tsx'
TESTFILE_BEFORE_SHA = '85e275f12237cfd7c52b121140bc829d28d09566fdacef42dabbbb680aa8f3e7'
TESTFILE_AFTER_SHA = 'd58df43a030610ce04a4192f4708099bff69afd87f9f761c43a8dfb1e1169d27'
FRONT_TEST_SHA = 'c492dbd18ad63fc3d9505a88f41fbb09aa6ecd164eba606170d2038cda18a97c'
OLD = b'@example.test'
NEW = b'@example.com'
COUNT = 4
TEST_PROJECT = 'fieldwork-parity-m6-integrated-tests'
COMPOSE_FILE = 'docker-compose.m4-test-v4.yml'
DB_LOG = 'm6-r4-backend-db.log'
BACK_LOG = 'm6-r4-backend-test.log'
CLEANUP_LOG = 'm6-r4-backend-cleanup.log'
FRONT_R3_LOG = 'm6-r3-frontend-test.log'
BACK_R3_LOG = 'm6-r3-backend-test.log'
CLEANUP_R3_LOG = 'm6-r3-backend-cleanup.log'
REQUIRED_CASES = (
    'test_admin_provisions_new_worker_without_project_access',
    'test_duplicate_and_bad_password_rejected',
    'test_non_admin_cannot_enumerate_or_create',
    'test_viewer_can_read_but_cannot_post',
)


def stop(code: str) -> None:
    raise RuntimeError('M6_R4_STOP:' + code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def limited_text(path: Path, size_limit: int = 10_000_000) -> str:
    if not regular(path) or path.stat().st_size > size_limit:
        stop('REQUIRED_EVIDENCE_MISSING_OR_UNSAFE:' + path.name)
    return path.read_text(encoding='utf-8', errors='replace')


def stage_guard() -> Path:
    if os.geteuid() == 0:
        stop('ROOT_EXECUTION_FORBIDDEN')
    for path in (STATE, BASE, CANDIDATE):
        if not path.is_dir() or path.is_symlink() or path.resolve() != path:
            stop('STAGE_OR_CANDIDATE_NOT_CANONICAL')
        if path.stat().st_uid != os.geteuid():
            stop('DIRECTORY_NOT_OWNED_BY_ADMIN')
    if CANDIDATE.parent != STATE or CANDIDATE.name != 'parity-m6._sdfbhky':
        stop('CANDIDATE_SCOPE_CHANGED')
    receipt_path = CANDIDATE / '.m6-r9-source-receipt.json'
    receipt = json.loads(limited_text(receipt_path, 50_000))
    if (receipt.get('source') != str(BASE) or
        receipt.get('candidate') != str(STATE / '.parity-m6-preparing._sdfbhky') or
        receipt.get('status') != 'M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED' or
        receipt.get('production_modified') is not False):
        stop('M6_SOURCE_RECEIPT_INVALID')
    if (CANDIDATE / '.env').exists() or (CANDIDATE / '.env').is_symlink():
        stop('CANDIDATE_ENV_FILE_PRESENT')
    if not regular(CANDIDATE / COMPOSE_FILE):
        stop('ISOLATED_COMPOSE_MISSING')
    frontend = CANDIDATE / FRONT_TEST_REL
    if not regular(frontend) or sha(frontend.read_bytes()) != FRONT_TEST_SHA:
        stop('R3_FRONTEND_SOURCE_HASH_DRIFT')
    frontend_report = limited_text(CANDIDATE / FRONT_R3_LOG)
    if (not re.search(r'Test Files\s+17 passed \(17\)', frontend_report)
        or not re.search(r'Tests\s+107 passed \(107\)', frontend_report)):
        stop('R3_FRONTEND_PASS_NOT_PROVEN')
    back_report = limited_text(CANDIDATE / BACK_R3_LOG)
    if not re.search(r'3 failed, 92 passed', back_report):
        stop('R3_EXPECTED_BACKEND_FAILURE_NOT_PROVEN')
    for case in REQUIRED_CASES[:3]:
        if not re.search(r'^FAILED tests/test_account_m6\.py::' + re.escape(case), back_report, re.MULTILINE):
            stop('R3_FAILURE_SET_NOT_MATCHED')
    if 'special-use or reserved name' not in back_report or '@example.test' not in back_report:
        stop('R3_EXPECTED_EMAIL_VALIDATOR_FAILURE_NOT_PROVEN')
    cleanup_report = limited_text(CANDIDATE / CLEANUP_R3_LOG, 100_000)
    if cleanup_report.strip() != 'CLEANUP_EXIT=0':
        stop('R3_TEST_DB_CLEANUP_NOT_PROVEN')
    target = CANDIDATE / TESTFILE_REL
    if not regular(target) or sha(target.read_bytes()) != TESTFILE_BEFORE_SHA:
        stop('M6_ACCOUNT_TEST_FILE_SHA_DRIFT')
    if target.parent.is_symlink() or not target.parent.is_dir() or target.parent.stat().st_uid != os.geteuid():
        stop('TARGET_PARENT_UNSAFE')
    print('M6_R4_R3_FRONTEND_107_PASS_AND_EXPECTED_BACKEND_3_FAIL=VERIFIED', flush=True)
    return target


def amended_bytes(original: bytes) -> bytes:
    if sha(original) != TESTFILE_BEFORE_SHA:
        stop('TEST_SOURCE_HASH_MISMATCH')
    if original.count(OLD) != COUNT:
        stop('EXACT_FOUR_EMAIL_FIXTURES_REQUIRED')
    changed = original.replace(OLD, NEW)
    if sha(changed) != TESTFILE_AFTER_SHA or changed.count(NEW) != original.count(NEW) + COUNT:
        stop('REPLACEMENT_SHA_MISMATCH')
    if changed != original.replace(OLD, NEW):
        stop('NON_FIXTURE_CHANGE_DETECTED')
    return changed


def patch_test(target: Path) -> None:
    previous = target.read_bytes()
    changed = amended_bytes(previous)
    backup = target.with_name('test_account_m6.py.m6-r4-original.bak')
    if backup.exists() or backup.is_symlink():
        stop('ALREADY_PATCHED_OR_BACKUP_PRESENT')
    # Verify and save byte-exact previous source before atomic replace.
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(previous)
        f.flush()
        os.fsync(f.fileno())
    temp = None
    try:
        fd, name = tempfile.mkstemp(prefix='.m6-r4-account-test-', dir=target.parent)
        temp = Path(name)
        with os.fdopen(fd, 'wb') as f:
            f.write(changed)
            f.flush()
            os.fsync(f.fileno())
        if not regular(target) or sha(target.read_bytes()) != TESTFILE_BEFORE_SHA:
            stop('TEST_SOURCE_CHANGED_DURING_PATCH')
        os.replace(temp, target)
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    if sha(target.read_bytes()) != TESTFILE_AFTER_SHA or sha(backup.read_bytes()) != TESTFILE_BEFORE_SHA:
        stop('POSTPATCH_HASH_INVALID')
    print('M6_R4_TEST_FIXTURE_FOUR_EMAIL_DOMAIN_REPLACEMENTS=PASS', flush=True)
    print('M6_R4_TEST_AFTER_SHA=' + TESTFILE_AFTER_SHA, flush=True)


def compose_guard() -> None:
    p = subprocess.run(['docker', 'compose', '-p', TEST_PROJECT,
                        '-f', COMPOSE_FILE, 'config', '--format', 'json'],
                       cwd=CANDIDATE, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        stop('ISOLATED_COMPOSE_CONFIG_FAILED')
    data = json.loads(p.stdout)
    services = data.get('services', {})
    if set(services) != {'test-db', 'backend-tests'}:
        stop('ISOLATED_COMPOSE_SERVICE_DRIFT')
    if any(x.get('external') for x in data.get('volumes', {}).values()) or any(
        x.get('external') for x in data.get('networks', {}).values()
    ):
        stop('ISOLATED_COMPOSE_EXTERNAL_RESOURCE')
    for name, svc in services.items():
        if any(svc.get(k) for k in ('privileged', 'ports', 'volumes', 'network_mode',
                                    'devices', 'pid', 'ipc', 'extra_hosts', 'cap_add')):
            stop('ISOLATED_COMPOSE_UNSAFE_SERVICE:' + name)
    if 'tmpfs' not in services['test-db']:
        stop('ISOLATED_DB_NOT_EPHEMERAL')
    env = services['backend-tests'].get('environment', {})
    if env.get('FIELDWORK_TESTING') != '1' or 'DATABASE_URL' in env:
        stop('ISOLATED_TEST_ENV_INVALID')
    url = env.get('FIELDWORK_TEST_DATABASE_URL')
    if not isinstance(url, str):
        stop('ISOLATED_TEST_DB_URL_MISSING')
    parsed = urlsplit(url)
    if parsed.scheme not in ('postgresql', 'postgresql+psycopg') or parsed.hostname != 'test-db' or parsed.port != 5432:
        stop('ISOLATED_TEST_DB_URL_OUTSIDE_PRIVATE_PROJECT')
    existing = subprocess.run(['docker', 'ps', '-aq', '--filter',
                               'label=com.docker.compose.project=' + TEST_PROJECT],
                              capture_output=True, text=True, timeout=30)
    if existing.returncode or existing.stdout.strip():
        stop('ISOLATED_TEST_PROJECT_NOT_EMPTY')
    print('M6_R4_ISOLATED_POSTGRES_COMPOSE=PASS', flush=True)


def run_logged(args: list[str], log: str, timeout: int) -> str:
    target = CANDIDATE / log
    if target.exists() or target.is_symlink():
        stop('LOG_ALREADY_EXISTS:' + log)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        try:
            result = subprocess.run(args, cwd=CANDIDATE, stdout=f, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            stop('PROCESS_TIMEOUT:' + log)
        except OSError:
            stop('PROCESS_UNAVAILABLE:' + log)
        f.flush()
        os.fsync(f.fileno())
    if result.returncode != 0:
        print('M6_R4_FAILED_LOG=' + str(target), flush=True)
        stop('PROCESS_FAILED:' + log + ':exit=' + str(result.returncode))
    return limited_text(target, 14_000_000)


def backend_tests() -> None:
    prefix = ['docker', 'compose', '-p', TEST_PROJECT, '-f', COMPOSE_FILE]
    started = False
    try:
        # Prevalidated exact dedicated temporary service; never named prod or live stage.
        started = True
        run_logged(prefix + ['up', '-d', '--wait', '--wait-timeout', '120', 'test-db'], DB_LOG, 300)
        report = run_logged(prefix + ['run', '--rm', '--build', '-e', 'PYTHONPATH=/app',
                                      'backend-tests', 'python', '-m', 'pytest', '-v', 'tests'],
                            BACK_LOG, 1500)
        if not re.search(r'\b95 passed\b', report):
            stop('BACKEND_95_PASS_NOT_PROVEN')
        for case in REQUIRED_CASES:
            if not re.search(r'^tests/test_\S+::' + re.escape(case) + r'\s+PASSED',
                             report, re.MULTILINE):
                stop('BACKEND_REQUIRED_CASE_NOT_PASSED:' + case)
        print('M6_R4_POSTGRES_BACKEND_95_TESTS=PASS', flush=True)
    finally:
        if started:
            p = subprocess.run(prefix + ['down', '--remove-orphans'],
                               cwd=CANDIDATE, capture_output=True, text=True, timeout=90)
            out = CANDIDATE / CLEANUP_LOG
            if out.exists() or out.is_symlink():
                stop('CLEANUP_LOG_ALREADY_EXISTS')
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w', encoding='ascii') as f:
                f.write('CLEANUP_EXIT=' + str(p.returncode) + '\n')
            if p.returncode != 0:
                stop('TEST_POSTGRES_CLEANUP_FAILED')


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != '--repair-and-test':
        stop('USE_EXACT_REPAIR_AND_TEST_FLAG')
    target = stage_guard()
    compose_guard()
    patch_test(target)
    backend_tests()
    print('M6_R4_FRONTEND_PREVIOUSLY_VERIFIED_107_PASS', flush=True)
    print('M6_R4_FULL_TESTS_PASS_NO_DEPLOYMENT', flush=True)
    print('DEV_GATEWAY_18090_R8_UNCHANGED', flush=True)
    print('M6_R4_CANDIDATE=' + str(CANDIDATE), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        print('STOP: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(2)
