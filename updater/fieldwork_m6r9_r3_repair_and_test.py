#!/usr/bin/env python3
"""M6 R9 R3: SHA-pinned LOGIN UNIT-TEST fixture repair on isolated candidate, fresh full tests.

No production writes, no R8 or live 18090 gateway changes, no deployments.
Only the known failed M6 candidate can be changed, with a byte-exact backup.
The backend Postgres test project is disposable and has no production mounts.
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
TESTFILE_REL = 'frontend/src/components/Login.test.tsx'
LOGIN_REL = 'frontend/src/components/Login.tsx'
TESTFILE_SHA_BEFORE = 'cab031dd037e246ba7246cb91af65b5d94e2e95f116f377afbf30ea26f09c6e4'
OLD_LABEL = "screen.getByLabelText('Admin e-mail')"
NEW_LABEL = "screen.getByLabelText('E-mail vagy felhasználónév')"
TEST_PROJECT = 'fieldwork-parity-m6-integrated-tests'
IMAGE = 'fieldwork-frontend-gate:parity-m6-r9-r3'
DOCKERFILE = 'Dockerfile.m6-r3-frontend-test'
REQUIRED_CASES = (
    'test_admin_provisions_new_worker_without_project_access',
    'test_duplicate_and_bad_password_rejected',
    'test_non_admin_cannot_enumerate_or_create',
    'test_viewer_can_read_but_cannot_post',
)
FRONT_BUILD_LOG = 'm6-r3-frontend-build.log'
FRONT_LOG = 'm6-r3-frontend-test.log'
DB_LOG = 'm6-r3-backend-db.log'
BACK_LOG = 'm6-r3-backend-test.log'
BACK_DOWN_LOG = 'm6-r3-backend-cleanup.log'


def stop(code: str):
    raise RuntimeError('M6_R3_STOP:' + code)


def sha(data: bytes):
    return hashlib.sha256(data).hexdigest()


def regular(path: Path):
    return path.is_file() and not path.is_symlink()


def stage_guard():
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
    if not regular(receipt_path):
        stop('M6_R2_RECEIPT_MISSING')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('source') != str(BASE) or receipt.get('status') != 'M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED':
        stop('M6_R2_SOURCE_IDENTITY_MISMATCH')
    previous = str(STATE / '.parity-m6-preparing._sdfbhky')
    if receipt.get('candidate') != previous or receipt.get('production_modified') is not False:
        stop('M6_R2_RECEIPT_MISMATCH')
    old = BASE / TESTFILE_REL
    if not regular(old) or sha(old.read_bytes()) != TESTFILE_SHA_BEFORE:
        stop('BASE_LOGIN_TEST_SHA_DRIFT')
    testfile = CANDIDATE / TESTFILE_REL
    ui = CANDIDATE / LOGIN_REL
    if not regular(testfile) or not regular(ui):
        stop('M6_LOGIN_SOURCE_OR_TEST_MISSING')
    if b'E-mail vagy felhaszn\xc3\xa1l\xc3\xb3n\xc3\xa9v' not in ui.read_bytes():
        stop('M6_LOGIN_NEW_LABEL_MISSING')
    if not regular(CANDIDATE / 'docker-compose.m4-test-v4.yml'):
        stop('ISOLATED_TEST_COMPOSE_MISSING')
    if regular(CANDIDATE / '.env') or (CANDIDATE / '.env').is_symlink():
        # Never accidentally inherit a local .env with production credentials.
        stop('CANDIDATE_ENV_FILE_PRESENT')
    return testfile


def amended_bytes(original: bytes):
    if sha(original) != TESTFILE_SHA_BEFORE:
        stop('LOGIN_TEST_EXPECTED_SHA_MISMATCH')
    raw = original.decode('utf-8')
    if raw.count(OLD_LABEL) != 2 or NEW_LABEL in raw:
        stop('LOGIN_TEST_EXACT_TWO_ANCHORS_REQUIRED')
    changed = raw.replace(OLD_LABEL, NEW_LABEL).encode('utf-8')
    if changed == original or OLD_LABEL.encode() in changed or changed.count(NEW_LABEL.encode()) != 2:
        stop('LOGIN_TEST_REPLACEMENT_INVALID')
    return changed


def patch_test(testfile: Path):
    old = testfile.read_bytes()
    changed = amended_bytes(old)
    backup = testfile.with_name('Login.test.tsx.m6-r3-original.bak')
    if backup.exists() or backup.is_symlink():
        stop('ALREADY_PATCHED_OR_BACKUP_EXISTS')
    # Write and fsync the source backup *before* changing the isolated candidate.
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(old)
        f.flush()
        os.fsync(f.fileno())
    tmp = None
    try:
        fd, name = tempfile.mkstemp(prefix='.m6-r3-login-test-', dir=testfile.parent)
        tmp = Path(name)
        with os.fdopen(fd, 'wb') as f:
            f.write(changed)
            f.flush()
            os.fsync(f.fileno())
        if not regular(testfile) or sha(testfile.read_bytes()) != TESTFILE_SHA_BEFORE:
            stop('RACE_LOGIN_TEST_CHANGED')
        os.replace(tmp, testfile)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    if sha(testfile.read_bytes()) != sha(changed) or sha(backup.read_bytes()) != TESTFILE_SHA_BEFORE:
        stop('LOGIN_TEST_POSTPATCH_VERIFY_FAILED')
    print('M6_R3_LOGIN_TEST_TWO_LABEL_FIXES=PASS', flush=True)
    print('M6_R3_TEST_BEFORE_SHA=' + TESTFILE_SHA_BEFORE, flush=True)
    print('M6_R3_TEST_AFTER_SHA=' + sha(changed), flush=True)


def run_logged(argv: list[str], log_name: str, timeout: int = 900, env: dict | None = None):
    path = CANDIDATE / log_name
    if path.exists() or path.is_symlink():
        stop('LOG_PATH_ALREADY_EXISTS:' + log_name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        try:
            result = subprocess.run(argv, cwd=CANDIDATE, stdout=f, stderr=subprocess.STDOUT,
                                    timeout=timeout, env=env, check=False)
        except subprocess.TimeoutExpired:
            stop('TIMED_OUT:' + log_name)
        except OSError:
            stop('RUNNER_UNAVAILABLE:' + log_name)
        f.flush()
        os.fsync(f.fileno())
    if result.returncode:
        print('M6_R3_FAILED_LOG=' + str(path), flush=True)
        stop('PROCESS_FAIL:' + log_name + ':exit=' + str(result.returncode))
    return path.read_text(encoding='utf-8', errors='replace')


def compose_guard():
    p = subprocess.run(['docker', 'compose', '-p', TEST_PROJECT,
                        '-f', 'docker-compose.m4-test-v4.yml', 'config', '--format', 'json'],
                       cwd=CANDIDATE, capture_output=True, text=True, timeout=30, check=False)
    if p.returncode:
        stop('COMPOSE_CONFIG_FAILED')
    cfg = json.loads(p.stdout)
    services = cfg.get('services')
    if not isinstance(services, dict) or set(services) != {'test-db', 'backend-tests'}:
        stop('COMPOSE_SERVICES_NOT_ISOLATED')
    if any(x.get('external') for x in cfg.get('volumes', {}).values()) or any(
        x.get('external') for x in cfg.get('networks', {}).values()
    ):
        stop('COMPOSE_EXTERNAL_RESOURCE')
    for name, svc in services.items():
        if any(svc.get(key) for key in ('privileged', 'ports', 'volumes', 'network_mode',
                                        'devices', 'pid', 'ipc', 'extra_hosts', 'cap_add')):
            stop('COMPOSE_UNSAFE_SERVICE:' + name)
    if 'tmpfs' not in services['test-db']:
        stop('DATABASE_NOT_EPHEMERAL')
    env = services['backend-tests'].get('environment') or {}
    if env.get('FIELDWORK_TESTING') != '1' or 'DATABASE_URL' in env:
        stop('BACKEND_TEST_ENV_NOT_SAFE')
    url = env.get('FIELDWORK_TEST_DATABASE_URL')
    if not isinstance(url, str):
        stop('BACKEND_TEST_DATABASE_URL_MISSING')
    parsed = urlsplit(url)
    if not parsed.scheme.startswith('postgresql') or parsed.hostname != 'test-db' or parsed.port != 5432:
        stop('BACKEND_TEST_DATABASE_OUTSIDE_PRIVATE_COMPOSE')
    running = subprocess.run(['docker', 'ps', '-aq', '--filter',
                              'label=com.docker.compose.project=' + TEST_PROJECT],
                             capture_output=True, text=True, timeout=30, check=False)
    if running.returncode or running.stdout.strip():
        stop('TEST_PROJECT_NOT_FREE')
    print('M6_R3_EPHEMERAL_POSTGRES_SCOPE=PASS', flush=True)


def frontend_tests():
    dockerfile = CANDIDATE / DOCKERFILE
    if dockerfile.exists() or dockerfile.is_symlink():
        stop('R3_DOCKERFILE_EXISTS')
    dockerfile.write_text('FROM node:22.16-alpine\nWORKDIR /app\n'
                          'COPY frontend/package.json frontend/package-lock.json ./\n'
                          'RUN npm ci\nCOPY frontend/ ./\n', encoding='utf-8')
    run_logged(['docker', 'build', '--progress=plain', '-t', IMAGE,
                '-f', DOCKERFILE, '.'], FRONT_BUILD_LOG, timeout=1500)
    report = run_logged(['docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
                         '--security-opt', 'no-new-privileges', IMAGE,
                         'sh', '-lc', 'npm run typecheck && npm run lint && npm test'],
                        FRONT_LOG, timeout=1200)
    if not re.search(r'Test Files\s+17 passed \(17\)', report) or not re.search(
        r'Tests\s+107 passed \(107\)', report
    ):
        stop('FRONTEND_EXACT_17_FILES_107_TESTS_NOT_VERIFIED')
    print('M6_R3_FRONTEND_TYPECHECK_LINT_17_FILES_107_TESTS=PASS', flush=True)


def backend_tests():
    command_prefix = ['docker', 'compose', '-p', TEST_PROJECT,
                      '-f', 'docker-compose.m4-test-v4.yml']
    try:
        run_logged(command_prefix + ['up', '-d', '--wait', '--wait-timeout', '120', 'test-db'],
                   DB_LOG, timeout=300)
        report = run_logged(command_prefix + ['run', '--rm', '--build',
                                               '-e', 'PYTHONPATH=/app', 'backend-tests',
                                               'python', '-m', 'pytest', '-v', 'tests'],
                            BACK_LOG, timeout=1500)
        if not re.search(r'\b95 passed\b', report):
            stop('BACKEND_EXACT_95_TESTS_NOT_VERIFIED')
        for case in REQUIRED_CASES:
            if not re.search(r'^tests/test_\S+::' + re.escape(case) + r'\s+PASSED',
                             report, re.MULTILINE):
                stop('BACKEND_NAMED_CASE_MISSING:' + case)
        print('M6_R3_POSTGRES_BACKEND_95_TESTS=PASS', flush=True)
    finally:
        # Only our exact, prevalidated disposable test project is targeted.
        result = subprocess.run(command_prefix + ['down', '--remove-orphans'],
                                cwd=CANDIDATE, capture_output=True, text=True, timeout=90,
                                check=False)
        path = CANDIDATE / BACK_DOWN_LOG
        path.write_text('CLEANUP_EXIT=' + str(result.returncode) + '\n', encoding='ascii')
        if result.returncode != 0:
            stop('TEST_POSTGRES_CLEANUP_FAILED')


def main():
    if len(sys.argv) != 2 or sys.argv[1] != '--repair-and-test':
        stop('USE_EXACT_REPAIR_AND_TEST_FLAG')
    testfile = stage_guard()
    compose_guard()
    patch_test(testfile)
    frontend_tests()
    backend_tests()
    print('M6_R3_FULL_TESTS_PASS_NO_DEPLOYMENT', flush=True)
    print('DEV_GATEWAY_18090_R8_NOT_TOUCHED', flush=True)
    print('M6_R3_SOURCE_CANDIDATE=' + str(CANDIDATE), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(2)
