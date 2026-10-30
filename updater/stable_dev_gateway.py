"""Read-only, strict proposed stable FieldWork development URL and canary switch.

No Docker, host shell, network access, file writes or service reload. The on-Pi
adapter must independently check actual readiness, release ownership and origin
before using this *proposal*. An authenticated stable session requires preserving
both user database identity and JWT signing material across releases.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re

GATEWAY_HOST = '192.168.22.13'
GATEWAY_PORT = 18090
GATEWAY_PROJECT = 'fieldwork-dev-gateway'
GATEWAY_URL = f'http://{GATEWAY_HOST}:{GATEWAY_PORT}'
MILESTONE = re.compile(r'fieldwork-parity-m([1-9][0-9]*)\Z')
SHA256 = re.compile(r'[a-f0-9]{64}\Z')
TEST_PORTS = frozenset(range(18082, 18090)) | frozenset(range(18100, 18180))


class GatewayDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise GatewayDenied(reason)


def _string(value: object, maxlen: int = 128) -> str:
    require(type(value) is str and 0 < len(value) <= maxlen, 'VALUE_INVALID')
    return value


def verify_receipt(receipt: dict) -> dict:
    """Check bounds and traceability, *not* service health or receipt provenance."""
    require(type(receipt) is dict and set(receipt) == {
        'project', 'bind_ip', 'port', 'artifact_sha256', 'test_gate',
        'database_identity', 'auth_identity'
    }, 'RECEIPT_SCHEMA_DENIED')
    project = _string(receipt['project'])
    require(MILESTONE.fullmatch(project) is not None, 'PROJECT_NOT_CANARY')
    require(receipt['bind_ip'] == GATEWAY_HOST, 'TARGET_HOST_DENIED')
    port = receipt['port']
    require(type(port) is int and port in TEST_PORTS, 'TARGET_PORT_DENIED')
    require(type(receipt['artifact_sha256']) is str and
            SHA256.fullmatch(receipt['artifact_sha256']) is not None,
            'RELEASE_HASH_INVALID')
    require(receipt['test_gate'] == 'FULL_SUITE_PASS', 'FULL_SUITE_REQUIRED')
    _string(receipt['database_identity'])
    _string(receipt['auth_identity'])
    # The caller cannot set an arbitrary target host/URL or Nginx directives.
    return dict(receipt)


def render_nginx(port: int) -> str:
    """Generate the deterministic forwarder for a strictly allowed local port."""
    require(type(port) is int and port in TEST_PORTS, 'TARGET_PORT_DENIED')
    return (
        '# FieldWork DEV only; locally review and install after adapter approval.\n'
        'server {\n'
        '    listen 8080;\n'
        '    server_name _;\n'
        '    client_max_body_size 26m;\n'
        '    location / {\n'
        f'        proxy_pass http://{GATEWAY_HOST}:{port};\n'
        '        proxy_http_version 1.1;\n'
        '        proxy_set_header Host $http_host;\n'
        '        proxy_set_header X-Real-IP $remote_addr;\n'
        '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
        '        proxy_set_header X-Forwarded-Proto $scheme;\n'
        '        proxy_read_timeout 90s;\n'
        '    }\n'
        '}\n'
    )


def plan_switch(candidate: dict, current: dict | None = None) -> dict:
    """Produce a reviewable config; does not switch anything or assert health."""
    candidate = verify_receipt(candidate)
    if current is not None:
        current = verify_receipt(current)
        require(current['project'] != candidate['project'], 'ALREADY_ACTIVE_RELEASE')
    consistent_auth = (current is None or
                       current['auth_identity'] == candidate['auth_identity'])
    consistent_db = (current is None or
                     current['database_identity'] == candidate['database_identity'])
    # Same origin only preserves browser storage. Token continuity additionally
    # needs compatible signing keys and persisted user IDs in the same dev DB.
    requirements = ['actual_candidate_health_pass', 'dedicated_gateway_port_free',
                    'local_activation_approved', 'durable_backup_and_rollback',
                    'origin_is_not_publicly_exposed', 'release_manifest_verified']
    if current is not None and not consistent_auth:
        requirements.append('jwt_auth_identity_mismatch_must_be_resolved')
    if current is not None and not consistent_db:
        requirements.append('dev_database_identity_mismatch_must_be_resolved')
    rendered = render_nginx(candidate['port'])
    return {
        'status': 'REVIEW_ONLY_NOT_DEPLOYED',
        'stable_origin': GATEWAY_URL,
        'gateway_project': GATEWAY_PROJECT,
        'gateway_bind': f'{GATEWAY_HOST}:{GATEWAY_PORT}:8080',
        'target_project': candidate['project'],
        'target_port': candidate['port'],
        'nginx_config_sha256': sha256(rendered.encode('utf-8')).hexdigest(),
        'nginx_config': rendered,
        'browser_origin_stable': True,
        'authentication_continuity_proven': False,
        'same_database_identity': consistent_db,
        'same_auth_identity': consistent_auth,
        'requires': requirements,
        'activated': False,
        'production_modified': False,
    }
