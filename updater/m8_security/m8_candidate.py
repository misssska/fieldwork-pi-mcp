#!/usr/bin/env python3
"""M8 source-only apply and native full test, in NEW private Pi candidate.
Not a deployer. Never writes live M6/M7, stable DEV, production, email or user DB.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit
from m8_security_overlay import PATCHERS, apply, digest, PatchStop

STATE=Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
M7=STATE/'parity-m7-video.7bc9a74m'
RECEIPT='m7-video-source-receipt.json'
EXPECTED_ORIGINAL={
 'server/app/team_api.py':'cf1db461dd8c4fec2b055bf4c72837d50bcefd79f8b83559431d85c06e6eabe8',
 'server/tests/test_team_m4.py':'49139da653c5486a3463ed762271f144c79bd8b825352610d1e9b782cd1ac254',
 'frontend/src/App.tsx':'42357ef218e4ca976cf0c9a0a9b4ca0d7dc0b0e1447925ab2b97b5d896c1425b',
 'frontend/src/components/Projects.tsx':'53a9baa041fa756d69050e5fbe1c724f61d4797605e6a0c76a89c7f171880d6c',
}
TESTS={'server/tests/test_security_m8.py':'test_security_m8.py'}
TEST_PROJECT='fieldwork-parity-m8-authz-fulltest'
TEST_COMPOSE='docker-compose.m4-test-v4.yml'


def stop(code):raise PatchStop('M8_STOP:'+code)
def clean_dir(p):return p.is_dir() and not p.is_symlink() and p.stat().st_uid==os.geteuid() and p.resolve()==p
def regular(p):return p.is_file() and not p.is_symlink()
def filehash(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(65536),b''):h.update(c)
 return h.hexdigest()


def safe_precheck():
 if os.geteuid()==0:stop('ROOT_NOT_ALLOWED')
 if not all(clean_dir(p) for p in (STATE,M7,M7/'server',M7/'frontend')):stop('UNSAFE_PRIVATE_SOURCE_DIR')
 if M7.parent!=STATE or M7.name!='parity-m7-video.7bc9a74m':stop('UNKNOWN_PARENT')
 if (M7/'.env').exists() or (M7/'.env').is_symlink():stop('LIVE_ENV_FILE_IN_SOURCE')
 receipt=M7/RECEIPT
 if not regular(receipt):stop('M7_RECEIPT_MISSING')
 data=json.loads(receipt.read_text())
 if (data.get('type')!='fieldwork-m7-video-role-isolated-candidate-v1'
    or data.get('source_m6')!=str(STATE/'parity-m6._sdfbhky')
    or data.get('not_deployed') is not True
    or data.get('mode')!='prepare-and-test'
    or data.get('frontend_expected')!=112 or data.get('backend_expected')!=103
    or data.get('r8_and_18090_modified') is not False or data.get('gmail_modified') is not False):
  stop('M7_RECEIPT_POLICY_INVALID')
 pins=data.get('changed_files_sha256')
 if not isinstance(pins,dict) or len(pins)!=15:stop('M7_SOURCE_SET_DRIFT')
 for rel,want in pins.items():
  if (not re.fullmatch('[A-Za-z0-9_./-]{4,160}',rel) or '..' in Path(rel).parts
      or not re.fullmatch('[0-9a-f]{64}',str(want))):stop('M7_RECEIPT_INVALID_PATH_OR_SHA')
  p=M7/rel
  if not regular(p) or filehash(p)!=want:stop('M7_SOURCE_HASH_DRIFT:'+rel)
 for rel,want in EXPECTED_ORIGINAL.items():
  p=M7/rel
  if not regular(p) or filehash(p)!=want:stop('M7_UNMODIFIED_SOURCE_DRIFT:'+rel)
 for rel in PATCHERS:
  if not regular(M7/rel):stop('M8_PATCH_SOURCE_NOT_REGULAR:'+rel)
 for rel in TESTS:
  if (M7/rel).exists() or (M7/rel).is_symlink():stop('M8_NEW_FILE_EXISTS_IN_M7:'+rel)
 if not regular(M7/TEST_COMPOSE):stop('ISOLATED_COMPOSE_MISSING')
 for name,patt in [('m7-video-frontend-test.log',r'Tests\s+112 passed \(112\)'),
                   ('m7-video-backend-test.log',r'\b103 passed\b'),
                   ('m7-video-test-cleanup.log',r'CLEANUP_EXIT=0')]:
  f=M7/name
  if not regular(f) or f.stat().st_size>30_000_000 or not re.search(patt,f.read_text(errors='replace')):
   stop('M7_NATIVE_RECEIPT_MISSING:'+name)
 print('M8_VERIFIED_M7_215_NATIVE_AND_SOURCE_PINS=PASS',flush=True)
 return data


def prepare_overlay():
 bundle=Path(__file__).resolve().parent
 out={}
 for rel in PATCHERS:
  raw=(M7/rel).read_bytes()
  out[rel]=apply(rel,raw)
 for rel,src in TESTS.items():
  if not regular(bundle/src):stop('M8_TEST_MODULE_MISSING')
  out[rel]=(bundle/src).read_bytes()
 for rel,data in out.items():
  if not rel.startswith(('server/app/','server/tests/','frontend/src/')) or b'\0' in data:
   stop('OUTPUT_SCOPE_INVALID:'+rel)
  if len(data)>1_500_000:stop('OUTPUT_TOO_LARGE:'+rel)
 print('M8_RBAC_AND_SYNC_PATCH_PLAN_7_FILES=PASS',flush=True)
 return out


def make_candidate(out):
 target=Path(tempfile.mkdtemp(prefix='.m8-auth-preparing-',dir=STATE))
 try:
  target.rmdir()
  shutil.copytree(M7,target,symlinks=True,ignore=shutil.ignore_patterns('node_modules','.git','.venv'))
  for rel,data in sorted(out.items()):
   path=target/rel
   if path.is_symlink() or path.parent.is_symlink():stop('M8_TARGET_SYMLINK:'+rel)
   path.parent.mkdir(parents=True,exist_ok=True)
   path.write_bytes(data)
   if filehash(path)!=digest(data):stop('M8_POST_WRITE_SHA:'+rel)
  receipt={'type':'fieldwork-m8-permissions-sync-isolated-v1',
           'source_m7':str(M7),'not_deployed':True,
           'source_files_sha256':{r:digest(b) for r,b in sorted(out.items())},
           'expected_frontend_tests':112,'expected_backend_tests':109,
           'production_modified':False,'stable_18090_modified':False,
           'original_m6_user_data_modified':False}
  (target/'m8-security-source-receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True))
  final=STATE/('parity-m8-authz.'+target.name.rsplit('-',1)[-1])
  if final.exists() or final.is_symlink():stop('M8_FINAL_CANDIDATE_EXISTS')
  target.rename(final)
  print('M8_ISOLATED_SOURCE='+str(final),flush=True)
  return final
 except Exception:
  print('M8_PREPARE_ORPHAN_REVIEW_PATH='+str(target),file=sys.stderr,flush=True)
  raise


def run(cand,args,log_name,timeout=1500):
 p=cand/log_name
 if p.exists() or p.is_symlink():stop('M8_LOG_ALREADY_EXISTS:'+log_name)
 with p.open('x') as out:
  q=subprocess.run(args,cwd=cand,stdout=out,stderr=subprocess.STDOUT,timeout=timeout)
 if q.returncode:stop('M8_COMMAND_FAILED_'+log_name+':'+str(q.returncode))
 return p.read_text(errors='replace')


def guarded_compose(cand):
 prefix=['docker','compose','-p',TEST_PROJECT,'-f',TEST_COMPOSE]
 v=json.loads(subprocess.check_output(prefix+['config','--format','json'],cwd=cand,text=True,timeout=35))
 services=v.get('services',{})
 if set(services)!={'test-db','backend-tests'}:stop('M8_TEST_SERVICE_SET_INVALID')
 if any(x.get('external') for x in v.get('networks',{}).values()):stop('M8_EXTERNAL_NETWORK')
 if any(x.get('external') for x in v.get('volumes',{}).values()):stop('M8_EXTERNAL_VOLUME')
 for item in services.values():
  if any(item.get(k) for k in ('privileged','network_mode','ports','volumes','devices','pid','ipc')):stop('M8_HOST_INTEGRATION')
 db=services['test-db']
 if not db.get('tmpfs') or db.get('volumes'):stop('M8_DB_NOT_EPHEMERAL')
 env=services['backend-tests'].get('environment') or {}
 url=urlsplit(env.get('FIELDWORK_TEST_DATABASE_URL',''))
 if env.get('FIELDWORK_TESTING')!='1' or url.hostname!='test-db' or url.port!=5432 or 'DATABASE_URL' in env:
  stop('M8_DB_NOT_ISOLATED')
 pr=subprocess.run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+TEST_PROJECT],capture_output=True,text=True,timeout=35)
 if pr.returncode or pr.stdout.strip():stop('M8_TEST_PROJECT_ALREADY_EXISTS')
 print('M8_PRIVATE_POSTGRES_TEST_PROJECT=PASS',flush=True)
 return prefix


def full_tests(cand):
 prefix=guarded_compose(cand)
 run(cand,['docker','build','-f','Dockerfile.m6-frontend-test','-t','fieldwork-frontend-gate:parity-m8-authz','.'],'m8-frontend-build.log')
 front=run(cand,['docker','run','--rm','--network','none','--cap-drop','ALL',
                 '--security-opt','no-new-privileges','fieldwork-frontend-gate:parity-m8-authz',
                 'sh','-lc','npm run typecheck && npm run lint && npm test'],'m8-frontend-test.log',1200)
 if not re.search(r'Test Files\s+19 passed \(19\)',front) or not re.search(r'Tests\s+112 passed \(112\)',front):
  stop('M8_FRONTEND_PASS_COUNT_INVALID')
 print('M8_FRONTEND_TYPESCRIPT_LINT_112_TESTS=PASS',flush=True)
 started=False
 try:
  started=True
  run(cand,prefix+['up','-d','--wait','--wait-timeout','120','test-db'],'m8-postgres-up.log',300)
  back=run(cand,prefix+['run','--rm','--build','-e','PYTHONPATH=/app',
                        'backend-tests','python','-m','pytest','-v','tests'],'m8-backend-test.log',1500)
  if not re.search(r'\b109 passed\b',back):stop('M8_BACKEND_PASS_COUNT_INVALID')
  for name in ('test_viewer_cannot_create_root_project_or_child_task_or_comment',
               'test_editor_cannot_create_root_but_can_create_writable_child',
               'test_admin_recovers_preexisting_private_project_without_rewriting_owner',
               'test_scope_detects_membership_grant_role_change_revoke',
               'test_nonmember_cannot_read_members_or_modify_any_parent',
               'test_inactive_system_admin_is_not_allowed_by_role_flag'):
   if not re.search(r'^tests/test_security_m8.py::'+re.escape(name)+r'\s+PASSED',back,re.M):
    stop('M8_CRITICAL_SECURITY_TEST_NOT_PASS:'+name)
  print('M8_POSTGRES_109_TESTS_CRITICAL_RBAC=PASS',flush=True)
 finally:
  if started:
   q=subprocess.run(prefix+['down','--remove-orphans'],cwd=cand,capture_output=True,text=True,timeout=110)
   (cand/'m8-backend-cleanup.log').write_text('CLEANUP_EXIT='+str(q.returncode)+'\n')
   if q.returncode:stop('M8_ISOLATED_DB_CLEANUP_FAILED')
 print('M8_221_NATIVE_TESTS_PASS_NO_DEPLOYMENT',flush=True)


def main():
 p=argparse.ArgumentParser(description=__doc__)
 opt=p.add_mutually_exclusive_group(required=True)
 opt.add_argument('--precheck',action='store_true')
 opt.add_argument('--prepare-and-test',action='store_true')
 a=p.parse_args()
 safe_precheck()
 out=prepare_overlay()
 if a.precheck:
  print('M8_PRECHECK_READ_ONLY_NOT_DEPLOYED=YES',flush=True)
  return
 cand=make_candidate(out)
 full_tests(cand)

if __name__=='__main__':
 try:main()
 except (PatchStop,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
  print(str(exc),file=sys.stderr,flush=True);sys.exit(2)
