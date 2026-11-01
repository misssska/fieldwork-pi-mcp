#!/usr/bin/env python3
"""Local-admin-only: verify M6+R9 inert Pi inbox ZIP and prepare/test isolated M6 source.

Never changes production /opt/fieldwork, running M5 R8, 18090 gateway,
legacy stage 18081, original R8 source, or permanent databases.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile

ARCHIVE_SHA = '7e4404d406b96ca8c4f0b303906e33904df88f465257d776880d3ca563e56feb'
ARCHIVE_SIZE = 20087
TRANSFER_ID = '7e4404d406b96ca8c4f0b303906e3390'
ROOT_PREFIX = 'FieldWork_M6_R9/'
STATE = Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
BUNDLE_PATH = STATE/('.m6-r9-inbox-'+ARCHIVE_SHA[:16])
BASE = STATE/'parity-m5.Krm2sA3i'
TEST_PROJECT = 'fieldwork-parity-m6-integrated-tests'
EXPECTED_FRONT_FILES=17
EXPECTED_FRONT_TESTS=107
EXPECTED_BACK_TESTS=95
MAX_FILE = 320000


def deny(code):
 raise RuntimeError('M6_R9_STOP:'+code)

def hash_file(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
 return h.hexdigest()

def locate():
 found=[]
 for root in (Path.home()/'.local/state',Path.home()/'.local/share'):
  if root.is_symlink() or not root.is_dir():continue
  for folder,dirs,files in os.walk(root,followlinks=False):
   dirs[:]=[x for x in dirs if x not in ('node_modules','.git','.venv','__pycache__')
           and not (Path(folder)/x).is_symlink()]
   for name in files:
    p=Path(folder)/name
    try:
     if p.is_symlink() or not p.is_file() or p.stat().st_size!=ARCHIVE_SIZE:continue
     if hash_file(p)==ARCHIVE_SHA:found.append(p)
    except OSError:continue
    if len(found)>1:deny('DUPLICATE_EXACT_ARCHIVES')
 if len(found)!=1:deny('EXACT_VERIFIED_INBOX_ARCHIVE_NOT_FOUND')
 return found[0]

def check_bundle(archive):
 with zipfile.ZipFile(archive) as z:
  infos=z.infolist()
  names=[i.filename for i in infos]
  if len(infos)!=11 or len(set(names))!=len(names):deny('ZIP_ENTRY_COUNT_OR_DUPLICATION')
  if any(not n.startswith(ROOT_PREFIX) for n in names):deny('ZIP_PREFIX')
  for info in infos:
   part=info.filename.removeprefix(ROOT_PREFIX)
   pieces=PurePosixPath(part).parts
   mode=info.external_attr>>16
   if (not pieces or '.' in pieces or '..' in pieces or part.startswith('/')
       or '\\' in part or part.endswith('/') or info.file_size>MAX_FILE
       or stat.S_IFMT(mode) not in (0,stat.S_IFREG)):
    deny('ZIP_ENTRY_UNSAFE')
  md='FieldWork_M6_R9/MANIFEST.json'
  if md not in names:deny('MANIFEST_MISSING')
  obj=json.loads(z.read(md))
  if obj.get('kind')!='fieldwork-m6-r9-isolated-overlay-v1':deny('MANIFEST_SCHEMA')
  expected=obj.get('sha256')
  manifest_file_names={n[len(ROOT_PREFIX+'bundle/'):] for n in names if n.startswith(ROOT_PREFIX+'bundle/')}
  if set(expected)!=manifest_file_names or len(expected)!=8:deny('MANIFEST_MEMBER_SET')
  for name,h in expected.items():
   if not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h):deny('MANIFEST_DIGEST_INVALID')
   if hashlib.sha256(z.read(ROOT_PREFIX+'bundle/'+name)).hexdigest()!=h:deny('MANIFEST_SHA_DRIFT:'+name)
  if 'FieldWork_M6_R9/integrate.py' not in names:deny('INTEGRATOR_MISSING')
  if 'FieldWork_M6_R9/tests/test_integrate.py' not in names:deny('TESTS_MISSING')
 return True

def extract_bundle(archive):
 if BUNDLE_PATH.exists() or BUNDLE_PATH.is_symlink():
  if BUNDLE_PATH.is_symlink() or not BUNDLE_PATH.is_dir():deny('BUNDLE_PATH_DRIFT')
  base=BUNDLE_PATH/'FieldWork_M6_R9'
  for path in (base/'integrate.py',base/'MANIFEST.json',base/'bundle/account_api.py'):
   if path.is_symlink() or not path.is_file():deny('EXTRACTED_BUNDLE_INVALID')
  # Check every expected file against source ZIP again.
  with zipfile.ZipFile(archive) as z:
   for inf in z.infolist():
    rel=inf.filename.removeprefix(ROOT_PREFIX)
    local=base/rel
    if local.is_symlink() or not local.is_file() or local.read_bytes()!=z.read(inf):
     deny('EXISTING_BUNDLE_TAMPERED:'+rel)
  return base
 tmp=Path(tempfile.mkdtemp(prefix='.m6-inbox-preparing-',dir=STATE))
 try:
  target=tmp/'FieldWork_M6_R9'
  target.mkdir(mode=0o700)
  with zipfile.ZipFile(archive) as z:
   for inf in z.infolist():
    rel=inf.filename.removeprefix(ROOT_PREFIX)
    dest=target/rel
    dest.parent.mkdir(parents=True,exist_ok=True)
    with z.open(inf) as src, dest.open('xb') as out:shutil.copyfileobj(src,out)
    dest.chmod(0o600)
  tmp.rename(BUNDLE_PATH)
  return BUNDLE_PATH/'FieldWork_M6_R9'
 except BaseException:
  shutil.rmtree(tmp,ignore_errors=True)
  raise

def cmd(argv,**kwargs):
 return subprocess.run(argv,check=True,text=True,**kwargs)

def check_test_compose(candidate):
 env=os.environ.copy()
 cfg=subprocess.check_output(['docker','compose','-p',TEST_PROJECT,
                              '-f','docker-compose.m4-test-v4.yml','config','--format','json'],
                             cwd=candidate,env=env,text=True,timeout=30)
 conf=json.loads(cfg)
 sv=conf['services']
 if set(sv)!={'test-db','backend-tests'}:deny('UNEXPECTED_TEST_COMPOSE_SERVICES')
 if any(v.get('external') for v in conf.get('networks',{}).values()):deny('EXTERNAL_TEST_NETWORK')
 if any(v.get('external') for v in conf.get('volumes',{}).values()):deny('EXTERNAL_TEST_VOLUME')
 for s in sv.values():
  if s.get('privileged') or s.get('network_mode') or s.get('ports') or s.get('volumes') or s.get('devices') or s.get('pid')=='host':
   deny('TEST_SERVICE_NOT_ISOLATED')
 db=sv['test-db']
 if 'tmpfs' not in db or db.get('volumes'):deny('TEST_DB_NOT_EPHEMERAL')
 runner=sv['backend-tests']
 envs=runner.get('environment') or {}
 if envs.get('FIELDWORK_TESTING')!='1':deny('TEST_MODE_NOT_ENABLED')
 if 'DATABASE_URL' in envs:deny('INHERITED_DB_URL_NOT_ISOLATED')
 url=envs.get('FIELDWORK_TEST_DATABASE_URL')
 if not isinstance(url,str):deny('TEST_DB_URL_MISSING')
 parsed=urlsplit(url)
 if not parsed.scheme.startswith('postgresql') or parsed.hostname!='test-db' or parsed.port!=5432:
  deny('TEST_DB_HOST_INVALID')
 print('M6_R9_ISOLATED_POSTGRES_COMPOSE=PASS',flush=True)

def full_tests(candidate):
 check_test_compose(candidate)
 existing=subprocess.check_output(['docker','ps','-aq','--filter',f'label=com.docker.compose.project={TEST_PROJECT}'],text=True,timeout=30)
 if existing.strip():deny('TEST_PROJECT_ALREADY_EXISTS')
 # No production mounts, no host Docker socket in test containers.
 dockerfile=candidate/'Dockerfile.m6-frontend-test'
 if dockerfile.exists() or dockerfile.is_symlink():deny('TEST_DOCKERFILE_ALREADY_EXISTS')
 dockerfile.write_text('FROM node:22.16-alpine\nWORKDIR /app\nCOPY frontend/package.json frontend/package-lock.json ./\nRUN npm ci\nCOPY frontend/ ./\n')
 try:
  log=candidate/'m6-frontend-test.log'
  build=candidate/'m6-frontend-build.log'
  with build.open('w') as out:
   cmd(['docker','build','--progress=plain','-t','fieldwork-frontend-gate:parity-m6-r9',
        '-f',dockerfile.name,'.'],cwd=candidate,stdout=out,stderr=subprocess.STDOUT)
  with log.open('w') as out:
   cmd(['docker','run','--rm','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
        'fieldwork-frontend-gate:parity-m6-r9','sh','-lc',
        'npm run typecheck && npm run lint && npm test'],cwd=candidate,stdout=out,stderr=subprocess.STDOUT)
  report=log.read_text()
  if not re.search(r'Test Files\s+17 passed \(17\)',report) or not re.search(r'Tests\s+107 passed \(107\)',report):
   deny('FRONTEND_EXACT_TEST_COUNT_NOT_VERIFIED')
  print('M6_R9_FULL_FRONTEND_17_FILES_107_TESTS_PASS',flush=True)
  db_log=candidate/'m6-backend-db.log'
  tests_log=candidate/'m6-backend-test.log'
  try:
   with db_log.open('w') as out:
    cmd(['docker','compose','-p',TEST_PROJECT,'-f','docker-compose.m4-test-v4.yml',
         'up','-d','--wait','--wait-timeout','120','test-db'],cwd=candidate,stdout=out,stderr=subprocess.STDOUT)
   with tests_log.open('w') as out:
    cmd(['docker','compose','-p',TEST_PROJECT,'-f','docker-compose.m4-test-v4.yml',
         'run','--rm','--build','-e','PYTHONPATH=/app','backend-tests',
         'python','-m','pytest','-v','tests'],cwd=candidate,stdout=out,stderr=subprocess.STDOUT)
   text=tests_log.read_text()
   if not re.search(r'\b95 passed\b',text):deny('BACKEND_TEST_COUNT_NOT_VERIFIED')
   for case in ('test_admin_provisions_new_worker_without_project_access',
                'test_duplicate_and_bad_password_rejected',
                'test_non_admin_cannot_enumerate_or_create',
                'test_viewer_can_read_but_cannot_post'):
    if not re.search(r'^tests/test_\S+::'+case+r'\s+PASSED',text,re.MULTILINE):
     deny('REQUIRED_BACKEND_CASE_NOT_PASS:'+case)
   print('M6_R9_FULL_BACKEND_95_TESTS_PASS',flush=True)
  finally:
   cmd(['docker','compose','-p',TEST_PROJECT,'-f','docker-compose.m4-test-v4.yml',
        'down','--remove-orphans'],cwd=candidate,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 finally:
  pass

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 mode=ap.add_mutually_exclusive_group(required=True)
 mode.add_argument('--precheck',action='store_true')
 mode.add_argument('--prepare-and-test',action='store_true')
 args=ap.parse_args()
 if os.geteuid()==0:deny('ROOT_INVOCATION_DENIED')
 if STATE.is_symlink() or not STATE.is_dir():deny('STATE_DIRECTORY_INVALID')
 arc=locate()
 check_bundle(arc)
 print('M6_R9_EXACT_INBOX_SHA256=PASS',flush=True)
 if args.precheck:
  print('M6_R9_TRANSFER_VERIFIED_NO_HOST_WRITES=YES');return
 package=extract_bundle(arc)
 result=subprocess.run([sys.executable,'-B',str(package/'integrate.py'),'--prepare'],
                       cwd=package,check=False,text=True,capture_output=True,timeout=180)
 if result.returncode:
  # Only print the integrator's bounded machine-readable STOP code, not unrestricted logs.
  for line in result.stderr.splitlines():
   if line.startswith('STOP: ') or line.startswith('M6_PREPARE_FAILED_CANDIDATE_WILL_REQUIRE_REVIEW='):
    print(line[:260],file=sys.stderr,flush=True)
  deny('INTEGRATOR_PREPARE_FAILED_EXIT_'+str(result.returncode))
 for line in result.stdout.splitlines():
  if line.startswith(('M6_R8_SOURCE_PINS_','M6_R9_PATCH_ANCHORS=','M6_R9_CANDIDATE_SOURCE_INTEGRATED=')):
   print(line,flush=True)
 candidates=[line.split('=',1)[1] for line in result.stdout.splitlines()
             if line.startswith('M6_FINAL_CANDIDATE_PATH=')]
 if len(candidates)!=1:deny('EXACT_NEW_CANDIDATE_NOT_REPORTED')
 candidate=Path(candidates[0])
 if (candidate.parent!=STATE or not candidate.name.startswith('parity-m6.') or
         not candidate.is_dir() or candidate.is_symlink()):
  deny('NEW_CANDIDATE_ORIGIN_INVALID')
 receipt=candidate/'.m6-r9-source-receipt.json'
 if receipt.is_symlink() or not receipt.is_file():deny('CANDIDATE_RECEIPT_MISSING')
 record=json.loads(receipt.read_text())
 if record.get('candidate') != str(STATE/('.parity-m6-preparing.'+candidate.name.split('parity-m6.')[-1])):
  deny('CANDIDATE_RECEIPT_ORIGIN_INVALID')
 print('M6_R9_SOURCE_CANDIDATE='+str(candidate),flush=True)
 full_tests(candidate)
 print('M6_R9_CANDIDATE_TESTS_PASS_NOT_DEPLOYED',flush=True)
 print('GATEWAY_18090_R8_UNCHANGED',flush=True)

if __name__=='__main__':
 try:main()
 except (RuntimeError,OSError,ValueError,KeyError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
  print('STOP: '+str(exc),file=sys.stderr);sys.exit(2)
