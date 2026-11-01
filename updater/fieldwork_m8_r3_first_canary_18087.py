#!/usr/bin/env python3
"""One-time M8 R3 LAN-only canary. Local admin consent; never touches production.

Read / test --precheck, start --launch. A private Compose project, DB and storage,
new signing/admin/database secrets, NO data/credentials migrated from M6/R8.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import urlopen

HOST = '192.168.22.13'
PORT = 18087
PROJECT = 'fieldwork-parity-m8-r3-canary'
STATE = Path.home() / '.local/state/fieldwork-pi-mcp-v03/stage-v06'
CAND = STATE / 'parity-m8-editor.u0ytzpgq'
M7 = STATE / 'parity-m7-video.7bc9a74m'
COMPOSE = 'docker-compose.stage.yml'
ENV_FILE = '.env.stage'
RECEIPT = 'm8-editor-source-receipt.json'
OVERRIDE = '.m8-r3-canary-override.yml'
SECRETS = '.m8-r3-canary-secrets.json'
RELEASE = 'm8-r3-canary-release.json'
START_LOG = 'm8-r3-canary-start.log'
ROLLBACK_LOG = 'm8-r3-canary-rollback.log'
FRONT_LOG = 'm8-editor-frontend-test.log'
BACK_LOG = 'm8-editor-backend-test.log'
CLEAN_LOG = 'm8-editor-test-cleanup.log'
REQUIRED_TESTS = (
    'test_owner_can_search_and_add_by_user_id',
    'test_unauthorized_candidate_directory_and_promotion_blocked',
    'test_global_editor_reads_all_but_cannot_mutate_unshared_project',
    'test_global_role_cannot_escalate_to_admin',
    'test_scope_changes_for_global_role_and_revocation',
    'test_membership_scope_grant_and_revoke_including_existing_records',
)
MAX_LOG_BYTES = 18_000_000


def deny(code):
    raise RuntimeError('M8_R3_CANARY_STOP:' + code)


def regular(path):
    return path.is_file() and not path.is_symlink()


def owner_dir(path):
    return path.is_dir() and not path.is_symlink() and path.resolve() == path and path.stat().st_uid == os.geteuid()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(128 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def log_text(filename):
    path = CAND / filename
    if not regular(path) or path.stat().st_size > MAX_LOG_BYTES:
        deny('M8_NATIVE_TEST_LOG_MISSING:' + filename)
    return path.read_text(encoding='utf-8', errors='replace')


def source_gate():
    if os.geteuid() == 0:
        deny('RUN_AS_NONROOT_ADMIN')
    if not all(owner_dir(x) for x in (STATE, CAND, CAND / 'server', CAND / 'frontend', M7)):
        deny('M8_SOURCE_OWNER_OR_PATH_UNSAFE')
    if CAND.parent != STATE or CAND.name != 'parity-m8-editor.u0ytzpgq':
        deny('M8_CANDIDATE_PATH_DRIFT')
    source = CAND / RECEIPT
    if not regular(source) or source.stat().st_size > 30000:
        deny('M8_SOURCE_RECEIPT_MISSING')
    data = json.loads(source.read_text(encoding='utf-8'))
    if (data.get('type') != 'fieldwork-m8-editor-team-scope-source-v1'
            or data.get('source_m7') != str(M7)
            or data.get('not_deployed') is not True
            or data.get('front_expected') != 112
            or data.get('back_expected') != 109
            or data.get('production_modified') is not False
            or data.get('active_canaries_targeted') is not False):
        deny('M8_SOURCE_RECEIPT_FIELDS_DRIFT')
    pins = data.get('modified_sha256')
    expected = {
        'server/app/team_api.py', 'server/app/account_api.py',
        'frontend/src/components/ReferenceTeam.tsx',
        'frontend/src/components/TeamDirectory.ts',
        'server/app/main.py', 'frontend/src/App.tsx',
        'frontend/src/api/fieldwork.ts',
        'server/tests/test_editor_team_m8.py',
    }
    if not isinstance(pins, dict) or set(pins) != expected:
        deny('M8_MODIFIED_FILE_COUNT_OR_SET_DRIFT')
    for rel, expected_hash in pins.items():
        f = CAND / rel
        if not isinstance(expected_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_hash):
            deny('M8_PIN_INVALID:' + rel)
        if not regular(f) or digest(f) != expected_hash:
            deny('M8_TESTED_SOURCE_BYTES_DRIFT:' + rel)
    f = log_text(FRONT_LOG)
    b = log_text(BACK_LOG)
    if not re.search(r'Test Files\s+19 passed \(19\)', f) or not re.search(r'Tests\s+112 passed \(112\)', f):
        deny('M8_112_FRONTEND_NOT_PROVEN')
    if not re.search(r'\b109 passed\b', b) or re.search(r'\b[1-9]\d* failed\b', b):
        deny('M8_109_BACKEND_NOT_PROVEN')
    for name in REQUIRED_TESTS:
        if not re.search(r'^tests/test_editor_team_m8.py::' + re.escape(name) + r'\s+PASSED', b, re.M):
            deny('M8_REQUIRED_CASE_NOT_PASS:' + name)
    if log_text(CLEAN_LOG).strip() != 'CLEANUP_EXIT=0':
        deny('M8_ISOLATED_TEST_DB_CLEANUP_NOT_CONFIRMED')
    for rel in (COMPOSE, ENV_FILE):
        path = CAND / rel
        if not regular(path) or path.stat().st_uid != os.geteuid():
            deny('COMPOSE_OR_ENV_SOURCE_MISSING_OR_UNSAFE:' + rel)
    if (CAND / '.env').exists() or (CAND / '.env').is_symlink():
        deny('UNEXPECTED_GENERIC_DOT_ENV')
    print('M8_R3_112_FRONTEND_AND_109_POSTGRES_NATIVE_TESTS=PASS', flush=True)
    print('M8_R3_TESTED_SOURCE_8_FILE_SHA_PINS=PASS', flush=True)


def run(argv, *, env=None, timeout=90):
    try:
        return subprocess.run(argv, cwd=CAND, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        deny('COMMAND_FAILED_OR_TIMEOUT:' + argv[0])


def compose_env():
    env = os.environ.copy()
    env['STAGE_HTTP_PORT'] = str(PORT)
    env['FIELDWORK_WEB_TAG'] = 'm8-r3-canary'
    return env


def compose_prefix(override):
    return ['docker', 'compose', '-p', PROJECT, '--env-file', ENV_FILE,
            '-f', COMPOSE, '-f', override]


def original_config(env):
    raw = run(['docker','compose','-p',PROJECT,'--env-file',ENV_FILE,
               '-f',COMPOSE,'config','--format','json'],env=env)
    if raw.returncode:
        deny('ORIGINAL_COMPOSE_CONFIG_FAILED')
    try:
        doc = json.loads(raw.stdout)
    except ValueError:
        deny('ORIGINAL_COMPOSE_CONFIG_NOT_JSON')
    if set(doc.get('services', {})) != {'db','api','nginx'}:
        deny('ORIGINAL_COMPOSE_SERVICE_DRIFT')
    return doc


def fresh_override(original):
    api = original['services']['api'].get('environment') or {}
    db = original['services']['db'].get('environment') or {}
    if not isinstance(api,dict) or not isinstance(db,dict):
        deny('COMPOSE_ENV_SHAPE_INVALID')
    orig_url = api.get('DATABASE_URL')
    if not isinstance(orig_url,str):
        deny('DATABASE_URL_MISSING')
    parsed = urlsplit(orig_url)
    if not parsed.scheme.startswith('postgresql') or parsed.hostname!='db' or parsed.port!=5432:
        deny('DATABASE_SOURCE_NOT_PRIVATE')
    if parsed.username is None or not parsed.path or parsed.path=='/':
        deny('DATABASE_URL_USER_OR_NAME_MISSING')
    if not isinstance(db.get('POSTGRES_PASSWORD'),str) or not db['POSTGRES_PASSWORD']:
        deny('POSTGRES_PASSWORD_NOT_AVAILABLE')
    new_password = secrets.token_hex(32)
    uri = urlunsplit((parsed.scheme, quote(parsed.username, safe='') + ':' +
                      quote(new_password, safe='') + '@db:5432',parsed.path,
                      parsed.query,parsed.fragment))
    credentials = {}
    # Derive security keys from the effective Compose configuration; reject
    # any composition not showing a secret and a bootstrap admin password.
    for key, value in api.items():
        if not isinstance(value,str):
            continue
        upper=key.upper()
        if upper == 'DATABASE_URL':
            continue
        if any(term in upper for term in ('SECRET','SIGNING','TOKEN_KEY','JWT_KEY','JWT_SECRET')):
            credentials[key] = secrets.token_hex(32)
        elif upper in ('ADMIN_PASSWORD','INITIAL_ADMIN_PASSWORD','BOOTSTRAP_ADMIN_PASSWORD'):
            credentials[key] = secrets.token_urlsafe(34)
    if (not any('PASSWORD' in k.upper() for k in credentials)
        or not any('PASSWORD' not in k.upper() for k in credentials)):
        deny('APPLICATION_SIGNING_OR_BOOTSTRAP_SECRET_NOT_DETECTED')
    override = {
        'services':{
            'db':{'environment':{'POSTGRES_PASSWORD':new_password}},
            'api':{'environment':{'DATABASE_URL':uri, **credentials}},
        }
    }
    auth={'mode':'private_M8_canary_only', 'admin_email':api.get('ADMIN_EMAIL'),
          'bootstrap':{k:v for k,v in credentials.items() if 'PASSWORD' in k.upper()},
          'service_account_password_rotated':True,
          'database_credentials_rotated':True}
    return override,auth


def validate_config(doc, original):
    if not isinstance(doc,dict) or doc.get('name')!=PROJECT:
        deny('PROJECT_NAME_DRIFT')
    services=doc.get('services')
    if not isinstance(services,dict) or set(services)!={'db','api','nginx'}:
        deny('COMPOSE_UNEXPECTED_SERVICES')
    for kind in ('networks','volumes'):
        resources=doc.get(kind,{})
        if not isinstance(resources,dict):
            deny('COMPOSE_RESOURCE_SHAPE:'+kind)
        for value in resources.values():
            if value.get('external') or not str(value.get('name','')).startswith(PROJECT+'_'):
                deny('EXTERNAL_OR_SHARED_COMPOSE_RESOURCE:'+kind)
    for name,service in services.items():
        if any(service.get(key) for key in ('privileged','network_mode','pid','ipc',
                       'devices','cap_add','extra_hosts','container_name','secrets')):
            deny('UNSAFE_HOST_OR_PRIVILEGED_SERVICE:'+name)
        for mount in service.get('volumes') or []:
            if not isinstance(mount,dict) or mount.get('type') not in ('volume','tmpfs'):
                deny('BIND_MOUNT_NOT_ALLOWED:'+name)
            if mount.get('type')=='volume':
                source = mount.get('source')
                resource = doc.get('volumes', {}).get(source)
                if not isinstance(resource,dict) or not str(resource.get('name','')).startswith(PROJECT+'_'):
                    deny('VOLUME_NAME_NOT_PRIVATE:'+name)
        if name!='nginx' and service.get('ports'):
            deny('UNEXPECTED_PUBLIC_SERVICE:'+name)
        build=service.get('build')
        if build:
            ctx=Path(build['context'])
            if not ctx.is_dir() or ctx.resolve()!=ctx or not ctx.is_relative_to(CAND):
                deny('DOCKER_BUILD_CONTEXT_OUTSIDE_M8:'+name)
        image_name=service.get('image','')
        if image_name and build and not (PROJECT in image_name or 'm8-r3-canary' in image_name):
            deny('BUILD_IMAGE_TAG_NOT_ISOLATED:'+name)
    ports=services['nginx'].get('ports') or []
    if (len(ports)!=1 or str(ports[0].get('published'))!=str(PORT)
       or ports[0].get('host_ip')!=HOST or str(ports[0].get('target'))!='80'):
        deny('NGINX_PORT_NOT_EXACT_18087')
    api_env=services['api'].get('environment') or {}
    db_env=services['db'].get('environment') or {}
    u=urlsplit(api_env.get('DATABASE_URL',''))
    if (u.hostname!='db' or u.port!=5432 or not u.password
        or u.password!=db_env.get('POSTGRES_PASSWORD')):
        deny('API_DB_CREDENTIALS_NOT_PRIVATE_MATCHING')
    if u.password == original['services']['db']['environment'].get('POSTGRES_PASSWORD'):
        deny('DB_SECRET_NOT_ROTATED')
    for key,orig_value in (original['services']['api'].get('environment') or {}).items():
        up=key.upper()
        if any(term in up for term in ('SECRET','SIGNING','TOKEN_KEY','JWT_KEY','JWT_SECRET')):
            if api_env.get(key)==orig_value:
                deny('AUTH_SECRET_REUSED:'+key)
        if up in ('ADMIN_PASSWORD','INITIAL_ADMIN_PASSWORD','BOOTSTRAP_ADMIN_PASSWORD'):
            if api_env.get(key)==orig_value:
                deny('ADMIN_PASSWORD_REUSED')
    if str(api_env.get('FIELDWORK_DEV_ADMIN_ALIAS','0'))=='1':
        deny('DEV_ADMIN_ALIAS_UNSAFE')
    print('M8_R3_PRIVATE_DB_STORAGE_AUTH_AND_LAN_ONLY=PASS',flush=True)


def verify_unused():
    for n in (OVERRIDE, SECRETS, START_LOG, ROLLBACK_LOG, RELEASE):
        if (CAND/n).exists() or (CAND/n).is_symlink():
            deny('CANARY_PREVIOUS_ATTEMPT_OR_CONFIG_EXISTS:'+n)
    exist=run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT])
    if exist.returncode or exist.stdout.strip():
        deny('CANARY_COMPOSE_PROJECT_NOT_EMPTY')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST,PORT))
        except OSError:
            deny('CANARY_PORT_18087_NOT_AVAILABLE')
    print('M8_R3_18087_FREE_AND_PROJECT_EMPTY=PASS',flush=True)


def write_new_file(path,payload):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as file:
        file.write(payload)
        file.flush()
        os.fsync(file.fileno())


def compose_config(env, override):
    result=run(compose_prefix(override)+['config','--format','json'],env=env)
    if result.returncode:
        deny('M8_OVERRIDE_COMPOSE_CONFIG_FAILED')
    try:
        return json.loads(result.stdout)
    except ValueError:
        deny('M8_OVERRIDE_CONFIG_INVALID_JSON')


def probe():
    try:
        with urlopen(f'http://{HOST}:{PORT}/api/health', timeout=5) as resp:
            if resp.status!=200 or json.loads(resp.read(1024))!={'status':'ok'}:
                return False
        with urlopen(f'http://{HOST}:{PORT}/',timeout=5) as resp:
            return resp.status==200 and b'FieldWork' in resp.read(32000)
    except (OSError,ValueError):
        return False


def launch(env,auth):
    write_new_file(CAND/SECRETS,json.dumps(auth,indent=2,ensure_ascii=False)+'\n')
    command=compose_prefix(OVERRIDE)
    with os.fdopen(os.open(CAND/START_LOG,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as log:
        try:
            p=subprocess.run(command+['up','-d','--build','--wait','--wait-timeout','240'],
                             cwd=CAND,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1500)
            rc=p.returncode
        except (OSError,subprocess.TimeoutExpired):
            rc=99
        log.flush();os.fsync(log.fileno())
    healthy=rc==0
    if healthy:
        for _ in range(14):
            if probe():break
            time.sleep(2)
        else:healthy=False
    if not healthy:
        with os.fdopen(os.open(CAND/ROLLBACK_LOG,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as log:
            result=run(command+['down','--remove-orphans'],env=env,timeout=120)
            log.write('DOWN_EXIT='+str(result.returncode)+'\n')
            log.flush();os.fsync(log.fileno())
        deny('CANARY_START_OR_HTTP_HEALTH_FAILED_REVIEW_LOGS')
    names=run(['docker','ps','-a','--filter','label=com.docker.compose.project='+PROJECT,'--format','{{.Names}}'])
    expected={PROJECT+'-'+service+'-1' for service in ('db','api','nginx')}
    if names.returncode or set(names.stdout.strip().splitlines())!=expected:
        deny('CANARY_COMPOSE_CONTAINER_SET_DRIFT_MANUAL_REVIEW')
    receipt={'status':'M8_R3_CANARY_HEALTH_PASS_NOT_PROMOTED',
             'url':f'http://{HOST}:{PORT}', 'source':str(CAND),
             'project':PROJECT, 'frontend_tests':112, 'backend_tests':109,
             'production_modified_by_script':False,'r8_18090_modified_by_script':False,
             'm6_18086_modified_by_script':False,'m6_data_migrated':False,
             'secrets_generated_privately':True,'gateway_promotion_authorized':False}
    write_new_file(CAND/RELEASE,json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print('M8_R3_CANARY_18087_HEALTH_PASS=YES',flush=True)
    print('M8_R3_CANARY_URL='+receipt['url'],flush=True)
    print('M8_R3_PRIVATE_BOOTSTRAP_CREDENTIALS_FILE='+str(CAND/SECRETS),flush=True)
    print('M6_18086_AND_R8_18090_NOT_TARGETED=YES',flush=True)
    print('M8_R3_BROWSER_USER_ACCEPTANCE=NOT_VERIFIED',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--precheck',action='store_true')
    choice.add_argument('--launch',action='store_true')
    opts=parser.parse_args()
    source_gate()
    lock=CAND/'.m8-r3-canary-first-launch.lock'
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify_unused()
        env=compose_env()
        original=original_config(env)
        override,auth=fresh_override(original)
        if opts.precheck:
            with tempfile.NamedTemporaryFile(prefix='.m8-r3-canary-precheck-',suffix='.yml',dir=CAND,mode='w',delete=False) as file:
                file.write(json.dumps(override))
                test_path=file.name
            try:
                validate_config(compose_config(env,Path(test_path).name),original)
            finally:
                Path(test_path).unlink(missing_ok=True)
            print('M8_R3_PRECHECK_PASS_NOT_LAUNCHED=YES',flush=True)
            return
        write_new_file(CAND/OVERRIDE,json.dumps(override,indent=2)+'\n')
        validate_config(compose_config(env,OVERRIDE),original)
        launch(env,auth)
    finally:
        os.close(fd)


if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,subprocess.TimeoutExpired) as exc:
        print('STOP: '+str(exc),file=sys.stderr,flush=True)
        sys.exit(2)
