#!/usr/bin/env python3
"""Prepare and fully test a NEW isolated M7 video+viewer candidate on Pi.

Never touches active M6 18086, R8 18085/18090, stage 18081, or production.
This tool does not deploy, promote, modify Gmail/Calendar or create users.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlsplit
from video_overlay import SOURCE_PATCHERS, SOURCE_PINS, ROLE_HOOK, patch_existing, sha, SourceStop

STATE = Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
BASE = STATE/'parity-m5.Krm2sA3i'
M6 = STATE/'parity-m6._sdfbhky'
DOC = Path(__file__).resolve().parent
FULL_TEST_PROJECT = 'fieldwork-parity-m7-video-fulltest'
BACKEND_COMPOSE = 'docker-compose.m4-test-v4.yml'
RECEIPT = '.m6-r9-source-receipt.json'
EXPECTED_R4_SHA = 'd58df43a030610ce04a4192f4708099bff69afd87f9f761c43a8dfb1e1169d27'
EXPECTED_R4_ORIGINAL = '85e275f12237cfd7c52b121140bc829d28d09566fdacef42dabbbb680aa8f3e7'
EXPECTED_R3_SHA = 'c492dbd18ad63fc3d9505a88f41fbb09aa6ecd164eba606170d2038cda18a97c'
SOURCES = {
    'server/tests/test_video_m7.py': 'test_video_m7.py',
    'frontend/src/components/DocumentViewerVideo.test.tsx': 'DocumentViewerVideo.test.tsx',
    'frontend/src/components/useProjectWrite.test.tsx': 'useProjectWrite.test.tsx',
}
NEW_HOOK = 'frontend/src/components/useProjectWrite.ts'
EXPECTED_FRONT = 112
EXPECTED_BACK = 103  # 95 pre-existing + 8 M7 backend tests


def fail(code):
    raise SourceStop('M7_STOP:'+code)

def file_regular(path):
    return path.is_file() and not path.is_symlink()

def safe_dir(path):
    return path.is_dir() and not path.is_symlink() and path.resolve()==path and path.stat().st_uid==os.geteuid()

def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(128*1024),b''):
            h.update(block)
    return h.hexdigest()

def precheck():
    if os.geteuid()==0:fail('NO_ROOT')
    if not all(safe_dir(p) for p in (STATE,BASE,M6,M6/'server',M6/'frontend')):
        fail('STAGE_SOURCE_PATH_NOT_CANONICAL_OR_UNOWNED')
    if M6.parent!=STATE or M6.name!='parity-m6._sdfbhky':fail('M6_SOURCE_NOT_FIXED')
    if (M6/'.env').exists() or (M6/'.env').is_symlink():fail('SOURCE_ENV_OUTSIDE_APPROVED_STAGE')
    r=M6/RECEIPT
    if not file_regular(r):fail('M6_RECEIPT_MISSING')
    record=json.loads(r.read_text())
    if record.get('status')!='M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED' or record.get('source')!=str(BASE) or record.get('production_modified') is not False:
        fail('M6_RECEIPT_FIELDS_INVALID')
    pins=record.get('modified')
    if not isinstance(pins,dict) or len(pins)!=11:fail('M6_OVERLAY_SET_DRIFT')
    for rel,wanted in pins.items():
        if not re.fullmatch(r'[A-Za-z0-9_./-]{4,160}',rel) or '..' in Path(rel).parts:
            fail('M6_OVERLAY_BAD_PATH')
        f=M6/rel
        if not file_regular(f):fail('M6_OVERLAY_MISSING:'+rel)
        actual=digest_file(f)
        if rel=='server/tests/test_account_m6.py':
            if wanted!=EXPECTED_R4_ORIGINAL or actual!=EXPECTED_R4_SHA:
                fail('R4_TEST_SOURCE_NOT_MATCHED')
        elif actual!=wanted: fail('M6_OVERLAY_DRIFT:'+rel)
    if not file_regular(M6/'frontend/src/components/Login.test.tsx') or digest_file(M6/'frontend/src/components/Login.test.tsx')!=EXPECTED_R3_SHA:
        fail('R3_LOGIN_TEST_DRIFT')
    for rel,expected in SOURCE_PINS.items():
        p=M6/rel
        if not file_regular(p) or digest_file(p)!=expected:
            fail('UNMODIFIED_SOURCE_PIN_DRIFT:'+rel)
    for name,needle in [('m6-r3-frontend-test.log',r'Tests\s+107 passed \(107\)'),('m6-r4-backend-test.log',r'\b95 passed\b')]:
        p=M6/name
        if not file_regular(p) or p.stat().st_size>18_000_000 or not re.search(needle,p.read_text(errors='replace')):
            fail('M6_TEST_RECEIPT_MISSING:'+name)
    if not file_regular(M6/'m6-r5-canary-release.json'):
        fail('M6_LIVE_CANARY_RELEASE_MISSING')
    live=json.loads((M6/'m6-r5-canary-release.json').read_text())
    if live.get('status')!='M6_R5_CANARY_HEALTH_PASS_NOT_PROMOTED' or live.get('project')!='fieldwork-parity-m6-r9' or live.get('url')!='http://192.168.22.13:18086':
        fail('M6_CANARY_PROOF_MISSING')
    if not file_regular(M6/BACKEND_COMPOSE):fail('ISOLATED_BACKEND_COMPOSE_MISSING')
    for rel in SOURCES.values():
        if not file_regular(DOC/rel):fail('M7_BUNDLE_FILE_MISSING:'+rel)
    if not file_regular(DOC/'video_overlay.py'):fail('M7_OVERLAY_MISSING')
    for rel in set(SOURCE_PATCHERS)|set(SOURCES)|{NEW_HOOK}:
        f=M6/rel
        if rel in SOURCES or rel==NEW_HOOK:
            if f.exists() or f.is_symlink():fail('M7_FILE_EXISTS_IN_M6:'+rel)
        elif not file_regular(f):fail('M7_TARGET_NOT_REGULAR:'+rel)
    print('M7_PRECHECK_M6_107_95_HASHES_AND_CANARY=PASS',flush=True)
    return record


def render_source(record):
    outputs={}
    for rel in SOURCE_PATCHERS:
        src=(M6/rel).read_bytes()
        expected=record['modified'].get(rel) if rel in record['modified'] else SOURCE_PINS.get(rel)
        outputs[rel]=patch_existing(rel,src,expected)
    outputs[NEW_HOOK]=ROLE_HOOK.encode()
    for dest,src in SOURCES.items():outputs[dest]=(DOC/src).read_bytes()
    if len(outputs)!=len(SOURCE_PATCHERS)+1+len(SOURCES):fail('OUTPUT_SET_COLLISION')
    for dest,data in outputs.items():
        if not dest.startswith(('frontend/src/','server/app/','server/tests/','nginx/')):
            fail('OUTPUT_PATH_OUTSIDE_ALLOWLIST')
        if b'\x00' in data: fail('NUL_IN_OUTPUT')
    print(f'M7_VIDEO_AND_VIEWER_PATCH_PLAN_{len(outputs)}_FILES=PASS',flush=True)
    return outputs


def prepare(record,outputs):
    tmp=Path(tempfile.mkdtemp(prefix='.m7-video-preparing-',dir=STATE))
    if not safe_dir(tmp):fail('PREPARATION_DIRECTORY_INVALID')
    try:
        tmp.rmdir()  # copytree requires absent destination
        shutil.copytree(M6,tmp,symlinks=True,ignore=shutil.ignore_patterns('node_modules','.venv','.git'))
        for rel,data in sorted(outputs.items()):
            target=tmp/rel
            if target.is_symlink() or target.parent.is_symlink():fail('NEW_SOURCE_SYMLINK_BLOCKED:'+rel)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
            if digest_file(target)!=sha(data):fail('POST_WRITE_HASH_MISMATCH:'+rel)
        receipt={
            'type':'fieldwork-m7-video-role-isolated-candidate-v1',
            'source_m6':str(M6),'mode':'prepare-and-test','not_deployed':True,
            'frontend_expected':EXPECTED_FRONT,'backend_expected':EXPECTED_BACK,
            'changed_files_sha256':{p:sha(b) for p,b in sorted(outputs.items())},
            'r8_and_18090_modified':False,'gmail_modified':False,
        }
        (tmp/'m7-video-source-receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True))
        final=STATE/('parity-m7-video.'+tmp.name.rsplit('-',1)[-1])
        if final.exists() or final.is_symlink():fail('FINAL_CANDIDATE_ALREADY_EXISTS')
        tmp.rename(final)
        print('M7_PREPARED_ISOLATED_SOURCE='+str(final),flush=True)
        return final
    except Exception:
        print('M7_PREPARE_STOP_ORPHAN_REQUIRES_REVIEW='+str(tmp),file=sys.stderr,flush=True)
        raise


def run_logged(cand,argv,name,timeout=1600):
    f=cand/name
    if f.exists() or f.is_symlink():fail('LOG_ALREADY_EXISTS:'+name)
    with f.open('x') as log:
        try:
            p=subprocess.run(argv,cwd=cand,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        except subprocess.TimeoutExpired:
            fail('TIMEOUT:'+name)
        log.flush();os.fsync(log.fileno())
    if p.returncode:
        print('M7_FAILED_LOG='+str(f),flush=True)
        fail('PROCESS_FAIL:'+name+':'+str(p.returncode))
    return f.read_text(errors='replace')


def guard_compose(cand):
    prefix=['docker','compose','-p',FULL_TEST_PROJECT,'-f',BACKEND_COMPOSE]
    p=subprocess.run(prefix+['config','--format','json'],cwd=cand,capture_output=True,text=True,timeout=30)
    if p.returncode:fail('COMPOSE_CONFIG_FAIL')
    c=json.loads(p.stdout)
    if c.get('name')!=FULL_TEST_PROJECT or set(c.get('services',{}))!={'test-db','backend-tests'}:
        fail('TEST_COMPOSE_SET_OR_NAME_INVALID')
    services=c['services']
    for cfg in services.values():
        if any(cfg.get(k) for k in ('ports','privileged','network_mode','volumes','devices','pid','ipc','cap_add','extra_hosts','container_name')):
            fail('TEST_COMPOSE_EXTERNAL_ACCESS_DENIED')
    for obj in ('networks','volumes'):
        if any(v.get('external') for v in c.get(obj,{}).values()):fail('EXTERNAL_COMPOSE_RESOURCE_DENIED')
    if not services['test-db'].get('tmpfs'):fail('TEST_DB_NOT_TMPFS')
    env=services['backend-tests'].get('environment',{})
    url=urlsplit(env.get('FIELDWORK_TEST_DATABASE_URL',''))
    if env.get('FIELDWORK_TESTING')!='1' or url.hostname!='test-db' or url.port!=5432 or 'DATABASE_URL' in env:
        fail('TEST_DATABASE_NOT_EPHEMERAL')
    p=subprocess.run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+FULL_TEST_PROJECT],capture_output=True,text=True,timeout=30)
    if p.returncode or p.stdout.strip():fail('TEST_COMPOSE_ALREADY_RUNNING')
    print('M7_ISOLATED_POSTGRES_TEST_PROJECT=PASS',flush=True)
    return prefix


def full_tests(cand):
    prefix=guard_compose(cand)
    # Reuse the exact M6 Dockerfile: the newly copied M7 frontend sources are built in.
    run_logged(cand,['docker','build','-f','Dockerfile.m6-frontend-test','-t','fieldwork-frontend-gate:parity-m7-video','.'],'m7-video-frontend-build.log',1500)
    front=run_logged(cand,['docker','run','--rm','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
             'fieldwork-frontend-gate:parity-m7-video','sh','-lc','npm run typecheck && npm run lint && npm test'],
             'm7-video-frontend-test.log',1200)
    if not re.search(r'Test Files\s+19 passed \(19\)',front) or not re.search(r'Tests\s+112 passed \(112\)',front):
        fail('FRONTEND_112_NOT_PROVEN')
    print('M7_FRONTEND_TYPECHECK_LINT_19_FILES_112_TESTS=PASS',flush=True)
    started=False
    try:
        started=True
        run_logged(cand,prefix+['up','-d','--wait','--wait-timeout','120','test-db'],'m7-video-postgres-up.log',300)
        back=run_logged(cand,prefix+['run','--rm','--build','-e','PYTHONPATH=/app',
               'backend-tests','python','-m','pytest','-v','tests'],'m7-video-backend-test.log',1500)
        if not re.search(r'\b103 passed\b',back):fail('BACKEND_103_NOT_PROVEN')
        for name in ('test_valid_mp4_project_document_and_authenticated_download','test_valid_webm_project_document',
                     'test_viewer_can_download_but_cannot_upload_or_modify'):
            if not re.search(r'^tests/test_video_m7.py::'+re.escape(name)+r'\s+PASSED',back,re.M):
                fail('M7_BACKEND_REQUIRED_CASE_MISSING:'+name)
        print('M7_POSTGRES_BACKEND_103_TESTS=PASS',flush=True)
    finally:
        if started:
            done=subprocess.run(prefix+['down','--remove-orphans'],cwd=cand,capture_output=True,text=True,timeout=100)
            (cand/'m7-video-test-cleanup.log').write_text('CLEANUP_EXIT='+str(done.returncode)+'\n')
            if done.returncode:fail('TEST_DB_CLEANUP_NOT_PROVEN')
    print('M7_VIDEO_AND_VIEWER_TESTS_PASS_NO_DEPLOYMENT',flush=True)


def main():
    p=argparse.ArgumentParser()
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument('--precheck',action='store_true')
    x.add_argument('--prepare-and-test',action='store_true')
    args=p.parse_args()
    record=precheck()
    output=render_source(record)
    if args.precheck:
        print('M7_PRECHECK_ONLY_NO_MUTATION=YES',flush=True)
    else:
        candidate=prepare(record,output)
        full_tests(candidate)

if __name__=='__main__':
    try:main()
    except (SourceStop,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,subprocess.TimeoutExpired) as e:
        print(str(e),file=sys.stderr,flush=True)
        sys.exit(2)
