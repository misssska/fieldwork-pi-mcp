"""Detached fixed-scope staging start; never starts production or arbitrary commands.

Candidate extension only: requires a separately approved, hash-verified local
installation. Request and status return promptly; the worker calls only
stage_manager.start with the exact qualified proposal ID.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import stage_manager as stage
import stage_async as async_base

RUNNING = frozenset({'QUEUED', 'RUNNING'})
FINAL = frozenset({'START_COMMAND_PASS', 'START_COMMAND_ERROR'})


def _validated_id(args: dict) -> str:
    stage._fail(type(args) is dict and set(args) == {'proposal_id'}, 'STAGE_ARGS_DENIED')
    proposal_id = args['proposal_id']
    stage._fail(type(proposal_id) is str and stage.RELEASE_ID.fullmatch(proposal_id) is not None,
                'STAGE_RELEASE_ID_DENIED')
    stage._policy()
    return proposal_id


def _receipt() -> Path:
    return stage.STATE / 'async-start.json'


def _active_state() -> tuple[str | None, str | None]:
    path = stage.STATE / 'active.json'
    if not path.exists():
        return None, None
    data = json.loads(stage._owned_file(path))
    stage._fail(type(data) is dict and data.get('state') in ('STARTING', 'RUNNING')
                and type(data.get('proposal_id')) is str
                and stage.RELEASE_ID.fullmatch(data['proposal_id']) is not None,
                'STAGE_ACTIVE_STATE_INVALID')
    return data['proposal_id'], data['state']


def request(args: dict) -> dict:
    proposal_id = _validated_id(args)
    root, _ = stage._validated_release(proposal_id)
    result = json.loads(stage._owned_file(root / 'full-test.json'))
    stage._fail(result.get('status') == 'FULL_TEST_PASS', 'STAGE_FULL_TEST_REQUIRED')
    try:
        fd = async_base._locked(blocking=False)
    except BlockingIOError:
        return {'status': 'STAGE_ASYNC_BUSY', 'proposal_id': proposal_id,
                'production_modified': False}
    try:
        receipt = _receipt()
        prior = async_base._read(receipt)
        if prior:
            stage._fail(prior.get('proposal_id') == proposal_id, 'STAGE_START_OTHER_PROPOSAL_RECEIPT')
        if prior and prior.get('status') in RUNNING:
            return {'status': 'STAGE_START_ALREADY_REQUESTED' if async_base._live(prior)
                    else 'STAGE_START_WORKER_LOST', 'proposal_id': proposal_id,
                    'job_id': prior.get('job_id'), 'production_modified': False}
        active_id, state = _active_state()
        if active_id is not None:
            stage._fail(active_id == proposal_id, 'STAGE_OTHER_RELEASE_ACTIVE')
            return {'status': 'STAGE_ALREADY_ACTIVE' if state == 'RUNNING'
                    else 'STAGE_START_RECOVERY_REQUIRED', 'proposal_id': proposal_id,
                    'production_modified': False}
        # Block if another test is queued/running, even before it acquires the lock.
        for other in (stage.STATE / 'releases').glob('*/async-test.json'):
            previous = async_base._read(other)
            if previous and previous.get('status') in async_base.RUNNING:
                return {'status': 'STAGE_TEST_NOT_FINISHED', 'proposal_id': proposal_id,
                        'production_modified': False}
        # A final receipt from an earlier attempt is never silently overwritten.
        if prior:
            return {'status': 'STAGE_START_PREVIOUS_ATTEMPT', 'proposal_id': proposal_id,
                    'job_id': prior.get('job_id'), 'production_modified': False}
        job_id = secrets.token_hex(16)
        record = {'status': 'QUEUED', 'proposal_id': proposal_id, 'job_id': job_id,
                  'created_at_utc': int(time.time()), 'pid': None, 'proc_start_ticks': None}
        async_base._write(receipt, record)
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
            async_base._write(receipt, {**record, 'status': 'START_COMMAND_ERROR',
                                        'error': 'WORKER_SPAWN_FAILED'})
            raise ValueError('STAGE_ASYNC_START_SPAWN_FAILED') from None
        record.update(pid=worker.pid, proc_start_ticks=async_base._proc_ticks(worker.pid))
        async_base._write(receipt, record)
        return {'status': 'STAGE_START_QUEUED', 'proposal_id': proposal_id,
                'job_id': job_id, 'production_modified': False}
    finally:
        os.close(fd)


def status(args: dict) -> dict:
    proposal_id = _validated_id(args)
    record = async_base._read(_receipt())
    if record is None:
        return {'status': 'STAGE_START_NOT_REQUESTED', 'proposal_id': proposal_id,
                'production_modified': False}
    stage._fail(record.get('proposal_id') == proposal_id and record.get('status') in RUNNING | FINAL,
                'STAGE_START_RECEIPT_INVALID')
    state = record['status']
    if state in RUNNING and not async_base._live(record):
        if int(time.time()) - record.get('created_at_utc', 0) > 10:
            state = 'STAGE_START_WORKER_LOST'
    return {'status': state, 'proposal_id': proposal_id, 'job_id': record.get('job_id'),
            'production_modified': False}


def _worker(proposal_id: str, job_id: str) -> None:
    fd = async_base._locked()
    try:
        receipt = _receipt()
        record = async_base._read(receipt)
        if not record or record.get('job_id') != job_id or record.get('status') not in RUNNING:
            return
        record.update(status='RUNNING', pid=os.getpid(),
                      proc_start_ticks=async_base._proc_ticks(os.getpid()))
        async_base._write(receipt, record)
        try:
            result = stage.start({'proposal_id': proposal_id})
            state = 'START_COMMAND_PASS' if result.get('status') == 'STAGE_STARTED' else 'START_COMMAND_ERROR'
        except Exception as exc:
            state = 'START_COMMAND_ERROR'
            record['error'] = type(exc).__name__
        record.update(status=state, finished_at_utc=int(time.time()))
        async_base._write(receipt, record)
    finally:
        os.close(fd)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        sys.exit(2)
    proposal, job = sys.argv[2:]
    if not stage.RELEASE_ID.fullmatch(proposal) or not stage.RELEASE_ID.fullmatch(job):
        sys.exit(2)
    _worker(proposal, job)
