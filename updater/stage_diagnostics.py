"""Pure, fail-closed interpretation of *fixed staging project* Docker Compose ps JSON.

No subprocesses, secrets, filesystem access, or production interaction.
"""
import json

SERVICES = frozenset({'api', 'db', 'nginx'})


def classify_compose_ps(exit_code: int, output: str) -> dict:
    """Classify a `docker compose -p fieldwork-stage ps -a --format json` result.

    This does not infer application health; always use a separate HTTP smoke test.
    """
    if exit_code != 0:
        return {'status': 'STAGE_DOCKER_PS_FAILED', 'service_states': {}}
    if not isinstance(output, str) or not output.strip():
        return {'status': 'STAGE_NO_CONTAINERS', 'service_states': {}}
    try:
        data = json.loads(output)
    except (ValueError, TypeError):
        try:
            data = [json.loads(line) for line in output.splitlines() if line.strip()]
        except (ValueError, TypeError):
            return {'status': 'STAGE_DOCKER_PS_UNPARSEABLE', 'service_states': {}}
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or any(not isinstance(v, dict) for v in data):
        return {'status': 'STAGE_DOCKER_PS_UNPARSEABLE', 'service_states': {}}
    states = {}
    for item in data:
        service = item.get('Service')
        if service not in SERVICES or service in states:
            return {'status': 'STAGE_DOCKER_PS_UNEXPECTED', 'service_states': {}}
        states[service] = str(item.get('State', 'unknown')).lower()
    if not states:
        status = 'STAGE_NO_CONTAINERS'
    elif any(s != 'running' for s in states.values()):
        status = 'STAGE_CONTAINERS_NOT_RUNNING'
    elif set(states) != SERVICES:
        status = 'STAGE_SERVICES_MISSING'
    else:
        status = 'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED'
    return {'status': status, 'service_states': states}
