#!/usr/bin/env python3
"""Locally approved first activation of fixed FieldWork DEV gateway; no production modifications."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

HOST = '192.168.22.13'
GATEWAY_PORT = 18090
UPSTREAM_PORT = 18085
BASE = Path.home() / '.local/state/fieldwork-pi-mcp-v03/stage-v06/parity-m5.Krm2sA3i'
STATE = Path.home() / '.local/state/fieldwork-dev-gateway'
CONTAINER = 'fieldwork-dev-gateway-r8'
UPSTREAM_PROJECT = 'fieldwork-parity-m5-r8'
UPSTREAM_NAMES = {service: f'{UPSTREAM_PROJECT}-{service}-1' for service in ('api', 'db', 'nginx')}
SOURCE_PINS = {
    'server/app/main.py': '335778df44c033f2b2f37f011add606a6ed542b5c6fb0a55894d538b1c1aed8f',
    'server/app/team_api.py': 'cf1db461dd8c4fec2b055bf4c72837d50bcefd79f8b83559431d85c06e6eabe8',
    'server/app/models.py': '7f2ed4efaee5a83fd8c9ad984cf6a0b901f903ec6dc2478e1169bbfa3478f6a8',
    'server/app/schemas.py': 'afacde08516cdcbc80e08db9303eb713802ead5a5647895393a890c0768625e1',
    'frontend/src/components/ReferenceTeam.tsx': '7086e81b591dadaff394309d862ac812c1a6279381f3cd26d356ae3a1c291ab9',
    'frontend/src/components/TeamDirectory.ts': 'c1a1353241e1ce01c08aa6ec7f35e482b6ae958a9b7b3c9e43ec6b245f3e854c',
    'frontend/src/components/Login.tsx': '75744d679f43e8c22b5ce2f82a16d8637ce2d7b2fddc7c4fdbd2d355bc5ee666',
}
CONFIG = '''# FieldWork DEV-only R8 gateway. No production endpoints or auth changes.
server {
    listen 8080;
    server_name _;
    client_max_body_size 26m;
    location / {
        proxy_pass http://192.168.22.13:18085;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
        proxy_send_timeout 90s;
    }
}
'''

def stop(code):
    raise RuntimeError('STOP: ' + code)

def invoke(*argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        stop('COMMAND_FAILED:' + argv[0] + ':' + (p.stderr.strip() or 'exit=' + str(p.returncode))[:180])
    return p.stdout.strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check_sources():
    if BASE.is_symlink() or not BASE.is_dir() or BASE.resolve() != BASE:
        stop('R8_BASE_INVALID')
    for rel, expected in SOURCE_PINS.items():
        file = BASE / rel
        if file.is_symlink() or not file.is_file() or sha(file) != expected:
            stop('R8_SOURCE_DRIFT:' + rel)
    for log in ('m5-frontend-test.log', 'm5-backend-test.log'):
        f = BASE / log
        if not f.is_file() or f.is_symlink():
            stop('R8_TEST_LOG_MISSING:' + log)
    print('R8_7_SOURCE_HASHES=PASS')

def docker_info():
    try:
        data = json.loads(invoke('docker', 'inspect', *(UPSTREAM_NAMES.values())))
    except json.JSONDecodeError:
        stop('R8_DOCKER_INSPECT_INVALID')
    if len(data) != 3:
        stop('R8_SERVICES_MISSING')
    for service, item in zip(UPSTREAM_NAMES, data):
        state = item.get('State', {})
        labels = item.get('Config', {}).get('Labels', {})
        if item.get('Name') != '/' + UPSTREAM_NAMES[service] or not state.get('Running'):
            stop('R8_SERVICE_DOWN:' + service)
        if labels.get('com.docker.compose.project') != UPSTREAM_PROJECT or labels.get('com.docker.compose.service') != service:
            stop('R8_SERVICE_PROVENANCE_INVALID:' + service)
        if service in ('api','db') and state.get('Health', {}).get('Status') != 'healthy':
            stop('R8_HEALTH_NOT_READY:' + service)
        if service == 'nginx':
            mapping = item.get('NetworkSettings', {}).get('Ports', {}).get('80/tcp') or []
            if not any(x.get('HostIp') == HOST and x.get('HostPort') == str(UPSTREAM_PORT) for x in mapping):
                stop('R8_UPSTREAM_PORT_MISMATCH')
    image = data[2].get('Image')
    if not isinstance(image, str) or not image.startswith('sha256:'):
        stop('R8_NGINX_IMAGE_INVALID')
    print('R8_DOCKER_IDENTITY=PASS')
    return image

def health(port):
    try:
        with urlopen(f'http://{HOST}:{port}/api/health', timeout=3) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read(1024))
        return data == {'status': 'ok'}
    except (OSError, ValueError):
        return False

def can_bind():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, GATEWAY_PORT))
        except OSError:
            stop('18090_PORT_UNAVAILABLE')

def ensure_empty_gateway():
    result = subprocess.run(['docker','container','inspect',CONTAINER],capture_output=True,text=True,timeout=10)
    if result.returncode == 0:
        stop('GATEWAY_CONTAINER_ALREADY_EXISTS_NO_OVERWRITE')
    if result.returncode != 1:
        stop('GATEWAY_CONTAINER_INSPECT_FAILED')
    if (STATE / 'release.json').exists() or (STATE / 'default.conf').exists():
        stop('GATEWAY_STATE_ALREADY_EXISTS_NO_OVERWRITE')

def precheck():
    check_sources()
    image = docker_info()
    if not health(UPSTREAM_PORT):
        stop('R8_API_HEALTH_FAIL')
    ensure_empty_gateway()
    can_bind()
    print('PORT_18090=AVAILABLE')
    print('R8_UPSTREAM_HEALTH=PASS')
    return image

def activate(image):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.is_symlink() or (STATE.stat().st_mode & 0o077):
        stop('GATEWAY_STATE_PERMISSIONS_INVALID')
    config = STATE / 'default.conf'
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(CONFIG)
        f.flush()
        os.fsync(f.fileno())
    cid = ''
    try:
        cmd = [
            'docker','run','-d','--name',CONTAINER,
            '--label','fieldwork.dev-gateway=locally-approved-r8',
            '--restart','unless-stopped',
            '--publish',f'{HOST}:{GATEWAY_PORT}:8080',
            '--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges',
            '--pids-limit','100','--memory','128m',
            '--user','101:101',
            '--tmpfs','/var/cache/nginx:rw,uid=101,gid=101,mode=0700',
            '--tmpfs','/var/run:rw,uid=101,gid=101,mode=0700',
            '--mount',f'type=bind,source={config},target=/etc/nginx/conf.d/default.conf,readonly',
            '--entrypoint','nginx', image, '-g', 'daemon off;',
        ]
        cid = invoke(*cmd)
        if len(cid) != 64 or any(c not in '0123456789abcdef' for c in cid):
            stop('NEW_CONTAINER_ID_INVALID')
        for _ in range(20):
            if health(GATEWAY_PORT):
                break
            time.sleep(1)
        else:
            stop('18090_GATEWAY_HEALTH_FAILED')
        result = {
            'status':'FIRST_ACTIVATION_HEALTH_PASS',
            'url':f'http://{HOST}:{GATEWAY_PORT}',
            'upstream':f'http://{HOST}:{UPSTREAM_PORT}',
            'project':UPSTREAM_PROJECT,
            'container_id':cid,
            'image_id':image,
            'config_sha256':hashlib.sha256(CONFIG.encode()).hexdigest(),
            'auth_identity_verified':False,
            'database_migration_performed':False,
            'future_release_promotion_authorized':False,
            'production_modified':False,
        }
        path = STATE / 'release.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,'w') as f:
            json.dump(result, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        print('GATEWAY_18090=HEALTH_PASS')
        print('UPSTREAM_R8_18085=UNCHANGED')
        print('PRODUCTION_AND_18081=NOT_MODIFIED_BY_THIS_SCRIPT')
        print('FIXED_DEV_URL=' + result['url'])
        print('DISCLAIMER=LAN_BIND_ONLY_FIREWALL_NOT_VERIFIED')
        print('DEV_DB_AUTH_CONTINUITY_ACROSS_FUTURE_RELEASES=NOT_VERIFIED')
    except Exception:
        if cid and len(cid) == 64 and all(c in '0123456789abcdef' for c in cid):
            subprocess.run(['docker','rm','-f',cid],capture_output=True,text=True,timeout=20)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--precheck',action='store_true')
    mode.add_argument('--activate',action='store_true')
    args=p.parse_args()
    if STATE.is_symlink():
        stop('GATEWAY_STATE_SYMLINK_DENIED')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.is_symlink() or (STATE.stat().st_mode & 0o077):
        stop('GATEWAY_STATE_PERMISSIONS_INVALID')
    lock = STATE / '.local-activation.lock'
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
        image=precheck()
        if args.activate:
            activate(image)
        else:
            print('REVIEW_ONLY_NOT_DEPLOYED=YES')
    finally:
        os.close(fd)

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
