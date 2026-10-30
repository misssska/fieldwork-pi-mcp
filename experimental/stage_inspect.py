"""Read-only fixed-project staging Docker inspection; no host shell or raw output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import stage_manager as stage

_SERVICES = frozenset({'api', 'db', 'nginx'})
_MAX_BYTES = 65536


def classify_ps(code: int, raw: bytes) -> dict:
    """Parse Compose JSON array/object or NDJSON; fail closed on unexpected services."""
    if code != 0:
        return {'status': 'STAGE_PS_FAILED', 'services': {}}
    if not isinstance(raw, bytes) or len(raw) > _MAX_BYTES:
        return {'status': 'STAGE_PS_INVALID', 'services': {}}
    if not raw.strip():
        return {'status': 'STAGE_NO_CONTAINERS', 'services': {}}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        try:
            data = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except (ValueError, UnicodeError):
            return {'status': 'STAGE_PS_INVALID', 'services': {}}
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) > len(_SERVICES):
        return {'status': 'STAGE_PS_INVALID', 'services': {}}
    states = {}
    for item in data:
        if not isinstance(item, dict):
            return {'status': 'STAGE_PS_INVALID', 'services': {}}
        service = item.get('Service')
        state = item.get('State')
        if service not in _SERVICES or service in states or state not in ('running', 'exited', 'created', 'restarting', 'paused', 'dead'):
            return {'status': 'STAGE_PS_INVALID', 'services': {}}
        states[service] = state
    if not states:
        status = 'STAGE_NO_CONTAINERS'
    elif any(s != 'running' for s in states.values()):
        status = 'STAGE_CONTAINERS_NOT_RUNNING'
    elif set(states) != _SERVICES:
        status = 'STAGE_SERVICES_MISSING'
    else:
        status = 'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED'
    return {'status': status, 'services': states}


def status(args: dict) -> dict:
    stage._fail(type(args) is dict and not args, 'STAGE_ARGS_DENIED')
    policy = stage._policy()
    active = stage.STATE / 'active.json'
    if not active.exists():
        return {'status': 'STAGE_NOT_STARTED', 'project': stage.STAGE_PROJECT,
                'production_modified': False}
    root, manifest = stage._active()
    active_record = json.loads(stage._owned_file(active))
    active_state = active_record.get('state')
    stage._fail(active_state in ('STARTING', 'RUNNING') and
                active_record.get('proposal_id') == manifest['proposal_id'],
                'STAGE_ACTIVE_STATE_INVALID')
    # Fixed project, fixed Compose file, fixed release. Never accept user argv or paths.
    argv = stage._compose(root, 'ps', '-a', '--format', 'json')
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(Path.home()),
           'DOCKER_CLI_HINTS': 'false'}
    try:
        p = subprocess.run(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        result = {'status': 'STAGE_PS_UNAVAILABLE', 'services': {}}
    else:
        result = classify_ps(p.returncode, p.stdout)
    return {**result, 'active_state': active_state,
            'proposal_id': manifest['proposal_id'],
            'project': stage.STAGE_PROJECT,
            'url': f"http://{policy['bind_ip']}:{stage.PORT}",
            'production_modified': False}
