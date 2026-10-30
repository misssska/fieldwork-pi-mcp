"""Durable, bounded, detached staging test runner (no generic host command).

The MCP call only launches a fixed worker. The worker runs the existing
stage_manager.full_test with the already-approved staging policy and its
strict test Compose preflight. No production writes or production mounts.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import stage_manager as stage

RUNNING = frozenset({'QUEUED', 'RUNNING'})
FINAL = frozenset({'FULL_TEST_PASS', 'FULL_TEST_FAIL', 'FULL_TEST_ERROR'})


def _validate(args: dict) -> str:
    stage._fail(type(args) is dict and set(args) == {'proposal_id'}, 'STAGE_ARGS_DENIED')
    proposal_id = args['proposal_id']
    stage._fail(type(proposal_id) is str and stage.RELEASE_ID.fullmatch(proposal_id) is not None,
                'STAGE_RELEASE_ID_DENIED')
    stage._policy()
    return proposal_id


def _paths(proposal_id: str) -> tuple[Path, Path, Path]:
    root = stage._root_for(proposal_id)
    return root, root / 'async-test.json', stage.STATE / 'async-test.lock'


def _write(path: Path, record: dict) -> None:
    stage._fail(path.parent.is_dir() and not path.parent.is_symlink(), 'STAGE_ROOT_DENIED')
    tmp = path.with_name(path.name + '.tmp-' + secrets.token_hex(8))
    try:
        # Exclusive file creation, mode 0600; atomic replacement.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    record = json.loads(stage._owned_file(path))
    stage._fail(type(record) is dict, 'STAGE_ASYNC_RECEIPT_INVALID')
    return record


def _locked(*, blocking: bool = True):
    stage._fail(stage.STATE.is_dir() and not stage.STATE.is_symlink(), 'STAGE_STATE_MISSING')
    fd = os.open(stage.STATE / 'async-test.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(fd)
        raise
    return fd


def _live(record: dict) -> bool:
    pid = record.get('pid')
    if type(pid) is not int or pid <= 1:
        return False
    try:
        # Distinguish a recycled PID from the original worker.
        stat_text = Path(f'/proc/{pid}/stat').read_text()
        start_ticks = stat_text.rsplit(')', 1)[1].split()[19]
        return start_ticks == record.get('proc_start_ticks')
    except (OSError, ValueError, IndexError):
        return False


def _proc_ticks(pid: int) -> str | None:
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def request(args: dict) -> dict:
    proposal_id = _validate(args)
    root, receipt, _ = _paths(proposal_id)
    # Validate release and test Compose BEFORE scheduling any host-side Docker operation.
    stage._validated_release(proposal_id)
    stage._preflight_test_compose(root)
    try:
        fd = _locked(blocking=False)
    except BlockingIOError:
        return {'status': 'ASYNC_TEST_BUSY', 'proposal_id': proposal_id,
                'production_modified': False}
    try:
        existing = _read(receipt)
        if existing and existing.get('status') in RUNNING:
            state = 'ASYNC_TEST_ALREADY_REQUESTED' if _live(existing) else 'ASYNC_TEST_WORKER_LOST'
            return {'status': state, 'proposal_id': proposal_id,
                    'job_id': existing.get('job_id'), 'production_modified': False}
        # Never run two stage test projects simultaneously, even for different proposals.
        for other in (stage.STATE / 'releases').glob('*/async-test.json'):
            if other == receipt: continue
            previous = _read(other)
            if previous and previous.get('status') in RUNNING and _live(previous):
                raise ValueError('STAGE_TEST_OTHER_JOB_RUNNING')
        # A PASS is immutable: no accidental repeat of a successful qualification.
        final = root / 'full-test.json'
        if final.exists() and _read(final).get('status') == 'FULL_TEST_PASS':
            return {'status': 'FULL_TEST_PASS', 'proposal_id': proposal_id,
                    'production_modified': False}
        job_id = secrets.token_hex(16)
        record = {'status': 'QUEUED', 'proposal_id': proposal_id, 'job_id': job_id,
                  'created_at_utc': int(time.time()), 'pid': None, 'proc_start_ticks': None}
        _write(receipt, record)
        module = Path(__file__).resolve()
        stage._fail(module.parent == Path(__file__).parent and not Path(__file__).is_symlink(),
                    'STAGE_WORKER_PATH_DENIED')
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(Path.home()),
               'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
        try:
            worker = subprocess.Popen([sys.executable, str(module), '--worker', proposal_id, job_id],
                                      cwd=module.parent, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      close_fds=True, start_new_session=True)
        except OSError:
            _write(receipt, {**record, 'status': 'FULL_TEST_ERROR', 'error': 'WORKER_SPAWN_FAILED'})
            raise ValueError('STAGE_ASYNC_WORKER_SPAWN_FAILED') from None
        record['pid'] = worker.pid
        record['proc_start_ticks'] = _proc_ticks(worker.pid)
        _write(receipt, record)
        return {'status': 'ASYNC_TEST_QUEUED', 'proposal_id': proposal_id, 'job_id': job_id,
                'production_modified': False}
    finally:
        os.close(fd)


def status(args: dict) -> dict:
    proposal_id = _validate(args)
    root, receipt, _ = _paths(proposal_id)
    stage._manifest(root)
    record = _read(receipt)
    if record is None:
        return {'status': 'ASYNC_TEST_NOT_REQUESTED', 'proposal_id': proposal_id,
                'production_modified': False}
    stage._fail(record.get('proposal_id') == proposal_id and record.get('status') in RUNNING | FINAL,
                'STAGE_ASYNC_RECEIPT_INVALID')
    state = record['status']
    # A crashed worker is not a PASS. Do not auto-start a duplicate Docker run.
    if state in RUNNING and not _live(record):
        # Short startup grace before a new worker has appeared in /proc.
        if int(time.time()) - record.get('created_at_utc', 0) > 10:
            state = 'ASYNC_TEST_WORKER_LOST'
    final = root / 'full-test.json'
    if final.exists():
        result = _read(final)
        if result.get('status') == 'FULL_TEST_PASS':
            state = 'FULL_TEST_PASS'
    return {'status': state, 'proposal_id': proposal_id, 'job_id': record.get('job_id'),
            'production_modified': False}


def _worker(proposal_id: str, job_id: str) -> None:
    root, receipt, _ = _paths(proposal_id)
    # A lock covers the entire test run, including Docker cleanup.
    fd = _locked()
    try:
        record = _read(receipt)
        if not record or record.get('job_id') != job_id or record.get('status') not in RUNNING:
            return
        record.update(status='RUNNING', pid=os.getpid(), proc_start_ticks=_proc_ticks(os.getpid()))
        _write(receipt, record)
        try:
            result = stage.full_test({'proposal_id': proposal_id})
            state = result['status']
        except Exception as exc:
            # Fixed Docker project only. Cleanup even if full_test throws or times out.
            try:
                stage._run(['docker', 'compose', '-p', 'fieldwork-stage-tests', '-f',
                            'docker-compose.test.yml', 'down', '-v', '--remove-orphans'],
                           cwd=root, timeout=100)
            except Exception:
                pass
            state = 'FULL_TEST_ERROR'
            record['error'] = type(exc).__name__  # never expose raw exception or secrets
        record.update(status=state, finished_at_utc=int(time.time()))
        _write(receipt, record)
    finally:
        os.close(fd)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        sys.exit(2)
    pid, token = sys.argv[2:]
    if not stage.RELEASE_ID.fullmatch(pid) or not stage.RELEASE_ID.fullmatch(token):
        sys.exit(2)
    _worker(pid, token)
