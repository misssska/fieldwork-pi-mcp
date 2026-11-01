#!/usr/bin/env python3
"""FieldWork M6 R9: locally approved first canary launch on isolated LAN port 18086.

Only the existing, fully tested M6 candidate is used. Cannot modify /opt/fieldwork,
R8 18085, stable gateway 18090 or stage 18081. Creates its OWN Compose project,
network and named volumes. This script does NOT promote to 18090, reset credentials,
or copy data/JWTs from R8. Requires local admin --launch and is not exposed to MCP.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

HOST = '192.168.22.13'
PORT = 18086
PROJECT = 'fieldwork-parity-m6-r9'
STATE = Path.home() / '.local/state/fieldwork-pi-mcp-v03/stage-v06'
CAND = STATE / 'parity-m6._sdfbhky'
BASE = STATE / 'parity-m5.Krm2sA3i'
COMPOSE = 'docker-compose.stage.yml'
ENV = '.env.stage'
RECEIPT = '.m6-r9-source-receipt.json'
R3_LOGIN_TEST = 'frontend/src/components/Login.test.tsx'
R4_ACCOUNT_TEST = 'server/tests/test_account_m6.py'
R3_LOGIN_SHA = 'c492dbd18ad63fc3d9505a88f41fbb09aa6ecd164eba606170d2038cda18a97c'
R4_ACCOUNT_SHA = 'd58df43a030610ce04a4192f4708099bff69afd87f9f761c43a8dfb1e1169d27'
R3_LOGIN_OLD_SHA = 'cab031dd037e246ba7246cb91af65b5d94e2e95f116f377afbf30ea26f09c6e4'
R4_ACCOUNT_OLD_SHA = '85e275f12237cfd7c52b121140bc829d28d09566fdacef42dabbbb680aa8f3e7'
ORIGINAL_SOURCE_PINS = {
    'server/app/main.py': '335778df44c033f2b2f37f011add606a6ed542b5c6fb0a55894d538b1c1aed8f',
    'server/app/team_api.py': 'cf1db461dd8c4fec2b055bf4c72837d50bcefd79f8b83559431d85c06e6eabe8',
    'server/app/models.py': '7f2ed4efaee5a83fd8c9ad984cf6a0b901f903ec6dc2478e1169bbfa3478f6a8',
    'server/app/schemas.py': 'afacde08516cdcbc80e08db9303eb713802ead5a5647895393a890c0768625e1',
}
REQUIRED_CASES = (
    'test_admin_provisions_new_worker_without_project_access',
    'test_duplicate_and_bad_password_rejected',
    'test_non_admin_cannot_enumerate_or_create',
    'test_viewer_can_read_but_cannot_post',
)
MAXLOG = 18_000_000


def deny(code):
    raise RuntimeError('M6_R5_STOP:' + code)


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def regular(path):
    return path.is_file() and not path.is_symlink()


def read_log(name):
    file = CAND / name
    if not regular(file) or file.stat().st_size > MAXLOG:
        deny('TEST_EVIDENCE_MISSING_OR_UNSAFE:' + name)
    return file.read_text(encoding='utf-8', errors='replace')


def verify_source_and_tests():
    if os.geteuid() == 0:
        deny('RUN_AS_NONROOT_ADMIN')
    for root in (STATE, BASE, CAND, CAND / 'server', CAND / 'frontend'):
        if not root.is_dir() or root.is_symlink() or root.resolve() != root:
            deny('SOURCE_DIRECTORY_INVALID:' + root.name)
        if root.stat().st_uid != os.geteuid():
            deny('SOURCE_NOT_OWNED_BY_LOCAL_ADMIN:' + root.name)
    if CAND.parent != STATE or CAND.name != 'parity-m6._sdfbhky':
        deny('M6_CANDIDATE_SCOPE_MISMATCH')
    if not regular(CAND / RECEIPT):
        deny('SOURCE_RECEIPT_NOT_PRESENT')
    data = json.loads((CAND / RECEIPT).read_text(encoding='utf-8'))
    if (data.get('status') != 'M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED'
        or data.get('source') != str(BASE)
        or data.get('candidate') != str(STATE / '.parity-m6-preparing._sdfbhky')
        or data.get('production_modified') is not False
        or data.get('required_frontend_tests') != 107
        or data.get('required_backend_tests') != 95):
        deny('M6_SOURCE_RECEIPT_DRIFT')
    pins = data.get('modified')
    if not isinstance(pins, dict) or len(pins) != 11:
        deny('SOURCE_OVERLAY_COUNT_DRIFT')
    for rel, value in pins.items():
        if not isinstance(rel, str) or not re.fullmatch(r'[a-zA-Z0-9_./-]{4,160}', rel) or '..' in Path(rel).parts:
            deny('SOURCE_OVERLAY_PATH_INVALID')
        path = CAND / rel
        if not regular(path) or digest_file(path) != value:
            deny('M6_OVERLAY_FILE_SHA_DRIFT:' + rel)
    for rel, sha in ORIGINAL_SOURCE_PINS.items():
        path = BASE / rel
        if not regular(path) or digest_file(path) != sha:
            deny('R8_BASE_SOURCE_SHA_DRIFT:' + rel)
    for path, expected in ((R3_LOGIN_TEST, R3_LOGIN_SHA), (R4_ACCOUNT_TEST, R4_ACCOUNT_SHA)):
        f = CAND / path
        if not regular(f) or digest_file(f) != expected:
            deny('PATCHED_TEST_FILE_SHA_DRIFT:' + path)
    for path, expected in ((R3_LOGIN_TEST+'.m6-r3-original.bak', R3_LOGIN_OLD_SHA),
                           (R4_ACCOUNT_TEST+'.m6-r4-original.bak', R4_ACCOUNT_OLD_SHA)):
        f = CAND / path
        if not regular(f) or digest_file(f) != expected:
            deny('TEST_BACKUP_MISSING_OR_DRIFT:' + path)
    front = read_log('m6-r3-frontend-test.log')
    back = read_log('m6-r4-backend-test.log')
    if not re.search(r'Test Files\s+17 passed \(17\)', front) or not re.search(r'Tests\s+107 passed \(107\)', front):
        deny('FRONTEND_107_RECEIPT_DENIED')
    if not re.search(r'\b95 passed\b', back) or re.search(r'(^FAILED\s|\b[1-9]\d* failed\b)', back, re.M):
        deny('POSTGRES_95_RECEIPT_DENIED')
    for test in REQUIRED_CASES:
        if not re.search(r'^tests/test_\S+::'+re.escape(test)+r'\s+PASSED', back, re.M):
            deny('REQUIRED_BACKEND_CASE_MISSING:' + test)
    if read_log('m6-r4-backend-cleanup.log').strip() != 'CLEANUP_EXIT=0':
        deny('BACKEND_TEST_DB_CLEANUP_NOT_CONFIRMED')
    if (CAND / '.env').exists() or (CAND / '.env').is_symlink():
        deny('UNEXPECTED_CANDIDATE_DOT_ENV')
    for name in (COMPOSE, ENV):
        if not regular(CAND / name) or (CAND / name).stat().st_uid != os.geteuid():
            deny('COMPOSE_OR_ENV_MISSING_OR_UNSAFE:'+name)
    print('M6_R5_107_FRONTEND_AND_95_POSTGRES_TESTS=PASS', flush=True)
    print('M6_R5_SOURCE_AND_BACKUP_HASH_PINS=PASS', flush=True)


def run(args, *, env=None, timeout=50):
    try:
        return subprocess.run(args, cwd=CAND, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        deny('SUBPROCESS_UNAVAILABLE_OR_TIMEOUT:' + args[0])


def env_for_compose():
    env = os.environ.copy()
    env['STAGE_HTTP_PORT'] = str(PORT)
    return env


def cmd_prefix():
    return ['docker', 'compose', '-p', PROJECT, '--env-file', ENV, '-f', COMPOSE]


def check_compose_config(config):
    if not isinstance(config, dict) or config.get('name') != PROJECT:
        deny('COMPOSE_PROJECT_DRIFT')
    services = config.get('services')
    if not isinstance(services, dict) or set(services) != {'db','api','nginx'}:
        deny('COMPOSE_UNEXPECTED_SERVICES')
    for k in ('networks','volumes'):
        doc = config.get(k,{})
        if not isinstance(doc, dict):
            deny('COMPOSE_RESOURCE_SHAPE_INVALID:'+k)
        for item in doc.values():
            if item.get('external'):
                deny('COMPOSE_EXTERNAL_RESOURCE:'+k)
            if item.get('name') and not item['name'].startswith(PROJECT+'_'):
                deny('COMPOSE_RESOURCE_NAME_NOT_SCOPED:'+k)
    for service, cfg in services.items():
        if any(cfg.get(k) for k in ('privileged','network_mode','pid','ipc','devices','cap_add','extra_hosts','secrets','container_name')):
            deny('COMPOSE_HOST_OR_PRIVILEGED_SCOPE:'+service)
        for vol in cfg.get('volumes',[]):
            if not isinstance(vol,dict) or vol.get('type') not in ('volume','tmpfs'):
                deny('COMPOSE_BIND_MOUNT_DENIED:'+service)
        if service != 'nginx' and cfg.get('ports'):
            deny('COMPOSE_UNEXPECTED_PUBLIC_PORT:'+service)
        for entry in cfg.get('networks',[]):
            if entry not in config.get('networks',{}):
                deny('COMPOSE_UNKNOWN_NETWORK:'+service)
        build = cfg.get('build')
        if build:
            if not isinstance(build,dict) or not isinstance(build.get('context'),str):
                deny('BUILD_CONTEXT_INVALID:'+service)
            path = Path(build['context'])
            if not path.is_dir() or path.resolve() != path or not path.is_relative_to(CAND):
                deny('BUILD_CONTEXT_OUTSIDE_M6:'+service)
    ports = services['nginx'].get('ports') or []
    if len(ports) != 1 or str(ports[0].get('published')) != str(PORT) or ports[0].get('host_ip') != HOST:
        deny('NGINX_BIND_NOT_EXACT_LAN_18086')
    dburl = services['api'].get('environment',{}).get('DATABASE_URL')
    if not isinstance(dburl,str):
        deny('API_DATABASE_URL_MISSING')
    try:
        url=urlsplit(dburl)
        if not url.scheme.startswith('postgresql') or url.hostname!='db' or url.port!=5432:
            deny('DATABASE_NOT_PRIVATE_M6_COMPOSE')
    except ValueError:
        deny('DATABASE_URL_INVALID')
    if str(services['api'].get('environment',{}).get('FIELDWORK_DEV_ADMIN_ALIAS','0')) == '1':
        deny('UNVERIFIED_ADMIN_ALIAS_MUST_REMAIN_OFF')
    print('M6_R5_COMPOSE_PRIVATE_DB_AND_LAN_ONLY=PASS', flush=True)


def ensure_absent():
    p = run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT])
    if p.returncode != 0 or p.stdout.strip():
        deny('M6_PROJECT_NOT_EMPTY_OR_DOCKER_UNAVAILABLE')
    for name in ('m6-r5-canary-start.log','m6-r5-canary-rollback.log','m6-r5-canary-release.json'):
        if (CAND/name).exists() or (CAND/name).is_symlink():
            deny('M6_R5_LAUNCH_ALREADY_ATTEMPTED')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST,PORT))
        except OSError:
            deny('PORT_18086_NOT_AVAILABLE')
    print('M6_R5_18086_FREE_AND_PROJECT_EMPTY=PASS', flush=True)


def probe():
    try:
        with urlopen('http://'+HOST+':'+str(PORT)+'/api/health',timeout=5) as resp:
            if resp.status!=200 or json.loads(resp.read(1024)) != {'status':'ok'}:
                return False
        with urlopen('http://'+HOST+':'+str(PORT)+'/',timeout=5) as resp:
            return resp.status==200 and b'FieldWork' in resp.read(32000)
    except (OSError, ValueError):
        return False


def create_log(name):
    return os.fdopen(os.open(CAND/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w',encoding='utf-8')


def activation(env):
    prefix=cmd_prefix()
    with create_log('m6-r5-canary-start.log') as log:
        try:
            r=subprocess.run(prefix+['up','-d','--build','--wait','--wait-timeout','240'],cwd=CAND,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1500)
            rc=r.returncode
        except (OSError,subprocess.TimeoutExpired):
            rc=99
        log.flush();os.fsync(log.fileno())
    good=rc==0
    if good:
        for _ in range(12):
            if probe():
                break
            time.sleep(2)
        else:
            good=False
    if not good:
        with create_log('m6-r5-canary-rollback.log') as log:
            r=run(prefix+['down','--remove-orphans'],env=env,timeout=100)
            log.write('DOWN_EXIT='+str(r.returncode)+'\n')
            log.flush();os.fsync(log.fileno())
        print('M6_R5_START_FAILED_LOG='+str(CAND/'m6-r5-canary-start.log'),flush=True)
        deny('CANARY_DID_NOT_START_OR_HEALTHCHECK_FAIL;_DOWN_PRESERVED_VOLUMES')
    inspect=run(['docker','ps','-a','--filter','label=com.docker.compose.project='+PROJECT,'--format','{{.Names}}'],timeout=20)
    names=set(inspect.stdout.strip().splitlines()) if inspect.returncode==0 else set()
    expected={PROJECT+'-'+x+'-1' for x in ('db','api','nginx')}
    if names!=expected:
        deny('CANARY_CONTAINER_INVENTORY_UNEXPECTED_REVIEW_MANUALLY')
    release={
      'status':'M6_R5_CANARY_HEALTH_PASS_NOT_PROMOTED',
      'url':'http://'+HOST+':'+str(PORT),
      'project':PROJECT,
      'source_candidate':str(CAND),
      'full_frontend_tests':107,
      'full_backend_tests':95,
      'production_modified_by_launcher':False,
      'r8_gateway_18090_modified_by_launcher':False,
      'database_migrated_from_r8':False,
      'shared_auth_session_continuity':False,
      'gateway_promotion_authorized':False,
      'dev_admin_alias_enabled':False,
    }
    fd=os.open(CAND/'m6-r5-canary-release.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump(release,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.flush();os.fsync(f.fileno())
    print('M6_R5_CANARY_18086_HEALTH_PASS=YES',flush=True)
    print('M6_R5_URL='+release['url'],flush=True)
    print('R8_18085_AND_GATEWAY_18090_NOT_TARGETED=YES',flush=True)
    print('M6_R5_AUTH_AND_DATA_MIGRATION_NOT_VERIFIED=YES',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument('--precheck',action='store_true')
    x.add_argument('--launch',action='store_true')
    args=p.parse_args()
    verify_source_and_tests()
    lock=CAND/'.m6-r5-first-launch.lock'
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        env=env_for_compose()
        result=run(cmd_prefix()+['config','--format','json'],env=env)
        if result.returncode:
            deny('DOCKER_COMPOSE_CONFIG_REJECTED')
        config=json.loads(result.stdout)
        check_compose_config(config)
        ensure_absent()
        if args.precheck:
            print('M6_R5_PRECHECK_PASS_NOT_LAUNCHED=YES',flush=True)
        else:
            activation(env)
    finally:
        os.close(fd)


if __name__=='__main__':
    try:
        main()
    except (RuntimeError,OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,subprocess.TimeoutExpired) as exc:
        print('STOP: '+str(exc),file=sys.stderr,flush=True)
        sys.exit(2)
