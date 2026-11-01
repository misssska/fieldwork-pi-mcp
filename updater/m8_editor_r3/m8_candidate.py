#!/usr/bin/env python3
"""M8 editor visibility + search picker + scope-resync: Pi source-only candidate and native isolated tests.

NO deployment, no live DB migration, no active M7/M6/R8/prod modifications.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit
import build
from m8_editor_overlay import PATCHERS,sha

STATE=Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
M7=STATE/'parity-m7-video.7bc9a74m'
DOC=Path(__file__).resolve().parent
PROJECT='fieldwork-parity-m8-editor-fulltest'
COMPOSE='docker-compose.m4-test-v4.yml'
EXPECTED_FRONT=112
EXPECTED_BACK=109  # M7 103 + 6 new editor/scope tests
M7_MODIFIED_COUNT=15
EXTRA_TEST='server/tests/test_editor_team_m8.py'
M6=STATE/'parity-m6._sdfbhky'
M5=STATE/'parity-m5.Krm2sA3i'
APP_REL='frontend/src/App.tsx'
APP_INIT_ANCHOR='  // Az első snapshot egyszer fut; a további frissítéseket a felhasználó indítja.'
M8_MODIFIED=['server/app/team_api.py','server/app/account_api.py',
             'frontend/src/components/ReferenceTeam.tsx','frontend/src/components/TeamDirectory.ts',
             'server/app/main.py','frontend/src/App.tsx','frontend/src/api/fieldwork.ts']
M8_TEST_NAMES=[
 'test_owner_can_search_and_add_by_user_id',
 'test_unauthorized_candidate_directory_and_promotion_blocked',
 'test_global_editor_reads_all_but_cannot_mutate_unshared_project',
 'test_global_role_cannot_escalate_to_admin',
 'test_scope_changes_for_global_role_and_revocation',
 'test_membership_scope_grant_and_revoke_including_existing_records',
]

class GateStop(RuntimeError): pass

def fail(code):raise GateStop('M8_STOP:'+code)

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(128*1024),b''):h.update(block)
 return h.hexdigest()

def regular(p):return p.is_file() and not p.is_symlink()
def owned_dir(p):return p.is_dir() and not p.is_symlink() and p.resolve()==p and p.stat().st_uid==os.geteuid()

def verified_app_pin(m7_receipt):
 # Provenance-preserving alternative to the obsolete production App.tsx pin.
 # M6 copied M5 unchanged; M7 copied M6 unchanged. All three originals must
 # match byte-for-byte, and both source receipts must explicitly exclude App.
 if not all(owned_dir(x) for x in (M5,M6)):
  fail('M7_APP_ANCESTOR_DIRECTORY_UNSAFE')
 if m7_receipt.get('source_m6')!=str(M6) or APP_REL in m7_receipt.get('changed_files_sha256',{}):
  fail('M7_APP_ANCESTRY_RECEIPT_INVALID')
 mr=M6/'.m6-r9-source-receipt.json'
 if not regular(mr) or mr.stat().st_size>40000:fail('M6_APP_SOURCE_RECEIPT_MISSING')
 source_receipt=json.loads(mr.read_text())
 if (source_receipt.get('source')!=str(M5) or
     source_receipt.get('status')!='M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED' or
     source_receipt.get('production_modified') is not False or
     not isinstance(source_receipt.get('modified'),dict) or
     len(source_receipt['modified'])!=11 or APP_REL in source_receipt['modified']):
  fail('M6_APP_ANCESTRY_RECEIPT_INVALID')
 paths=(M5/APP_REL,M6/APP_REL,M7/APP_REL)
 if not all(regular(f) and f.stat().st_size<30000 for f in paths):fail('M7_APP_ANCESTRY_FILE_INVALID')
 digests=[digest(f) for f in paths]
 if len(set(digests))!=1:fail('M7_APP_ANCESTOR_SHA_DRIFT')
 code=paths[2].read_text(encoding='utf-8')
 if (code.count(APP_INIT_ANCHOR)!=1 or
     code.count("import { useAuth } from './auth/AuthContext'")!=1 or
     code.count('  useEffect(() => { void refresh(true).catch(() => undefined) }, [])')!=1):
  fail('M7_APP_CONTENT_ANCHOR_DRIFT')
 return digests[2]

def precheck():
 if os.geteuid()==0:fail('ROOT_DENIED')
 if not all(owned_dir(x) for x in (STATE,M7,M7/'server',M7/'frontend')):fail('M7_SOURCE_OWNER_OR_PATH_INVALID')
 if M7.parent != STATE or M7.name!='parity-m7-video.7bc9a74m':fail('M7_PATH_DRIFT')
 if not regular(M7/'m7-video-source-receipt.json'):fail('M7_SOURCE_RECEIPT_MISSING')
 receipt=json.loads((M7/'m7-video-source-receipt.json').read_text())
 if (receipt.get('type')!='fieldwork-m7-video-role-isolated-candidate-v1' or
     receipt.get('source_m6')!=str(STATE/'parity-m6._sdfbhky') or
     receipt.get('not_deployed') is not True or
     receipt.get('frontend_expected')!=112 or receipt.get('backend_expected')!=103):
  fail('M7_RECEIPT_FIELDS_DRIFT')
 outputs=receipt.get('changed_files_sha256')
 if not isinstance(outputs,dict) or len(outputs)!=M7_MODIFIED_COUNT:fail('M7_CHANGED_FILE_SET_DRIFT')
 for rel,wanted in outputs.items():
  if not isinstance(rel,str) or not rel.startswith(('server/','frontend/','nginx/')) or '..' in Path(rel).parts or not re.fullmatch('[0-9a-f]{64}',wanted):fail('M7_RECEIPT_UNSAFE')
  f=M7/rel
  if not regular(f) or digest(f)!=wanted:fail('M7_TESTED_SOURCE_DRIFT:'+rel)
 for n,needle in [('m7-video-frontend-test.log',r'Tests\s+112 passed \(112\)'),('m7-video-backend-test.log',r'\b103 passed\b')]:
  f=M7/n
  if not regular(f) or f.stat().st_size>18000000 or not re.search(needle,f.read_text(errors='replace')):fail('M7_FULL_TEST_PROOF_MISSING:'+n)
 for rel in ('server/app/team_api.py','server/app/account_api.py',
             'frontend/src/components/ReferenceTeam.tsx','frontend/src/components/TeamDirectory.ts'):
  source_name=Path(rel).name
  if not regular(M7/rel) or digest(M7/rel)!=build.PINS[source_name]:fail('M7_TEAM_SOURCE_PIN_DRIFT:'+rel)
 app_pin=verified_app_pin(receipt)
 print('M8_M5_M6_M7_APP_PROVENANCE_PIN=PASS',flush=True)
 for rel in ('server/app/main.py','frontend/src/api/fieldwork.ts'):
  if rel not in outputs:fail('M7_PATCHED_SOURCE_MISSING:'+rel)
 if (M7/EXTRA_TEST).exists() or (M7/EXTRA_TEST).is_symlink():fail('M8_TEST_ALREADY_IN_M7')
 for rel in ('build.py','baseline_sources.zip','m8_editor_overlay.py','test_editor_team_backend.py'):
  if not regular(DOC/rel):fail('M8_BUNDLE_MEMBER_MISSING:'+rel)
 print('M8_VERIFIED_M7_215_TESTS_AND_15_SOURCE_SHA=PASS',flush=True)
 return receipt

def render(receipt):
 app_pin=verified_app_pin(receipt)
 generated=build.generate()
 outputs={
  'server/app/team_api.py':generated['team_api.py'],
  'server/app/account_api.py':generated['account_api.py'],
  'frontend/src/components/ReferenceTeam.tsx':generated['ReferenceTeam.tsx'],
  'frontend/src/components/TeamDirectory.ts':generated['TeamDirectory.ts'],
 }
 for rel,patcher in PATCHERS.items():
  original=(M7/rel).read_bytes()
  if rel==APP_REL: expected=app_pin
  else:expected=receipt['changed_files_sha256'][rel]
  if sha(original)!=expected:fail('M8_INPUT_SHA_DRIFT:'+rel)
  outputs[rel]=patcher(original.decode('utf-8')).encode('utf-8')
 outputs[EXTRA_TEST]=(DOC/'test_editor_team_backend.py').read_bytes()
 if len(outputs)!=8 or set(outputs)!=set(M8_MODIFIED+[EXTRA_TEST]):fail('M8_OUTPUT_FILE_SET_DRIFT')
 for rel,data in outputs.items():
  if b'\x00' in data or len(data)>80000:fail('M8_OUTPUT_UNSAFE:'+rel)
 print('M8_EDITOR_TEAM_AND_SCOPE_PLAN_8_FILES=PASS',flush=True)
 return outputs

def prepare(outputs):
 tmp=Path(tempfile.mkdtemp(prefix='.m8-editor-preparing-',dir=STATE))
 if not owned_dir(tmp):fail('M8_TEMP_UNSAFE')
 try:
  tmp.rmdir()
  shutil.copytree(M7,tmp,symlinks=True,ignore=shutil.ignore_patterns('node_modules','.venv','.git'))
  for rel,data in sorted(outputs.items()):
   target=tmp/rel
   if target.exists() and target.is_symlink():fail('M8_TARGET_SYMLINK:'+rel)
   if target.parent.is_symlink():fail('M8_PARENT_SYMLINK:'+rel)
   target.parent.mkdir(parents=True,exist_ok=True)
   target.write_bytes(data)
   if digest(target)!=sha(data):fail('M8_AFTER_WRITE_DRIFT:'+rel)
  (tmp/'m8-editor-source-receipt.json').write_text(json.dumps({
   'type':'fieldwork-m8-editor-team-scope-source-v1','source_m7':str(M7),
   'not_deployed':True,'front_expected':EXPECTED_FRONT,'back_expected':EXPECTED_BACK,
   'modified_sha256':{k:sha(v) for k,v in sorted(outputs.items())},
   'active_canaries_targeted':False,'production_modified':False,
  },indent=2,sort_keys=True))
  final=STATE/('parity-m8-editor.'+tmp.name.rsplit('-',1)[-1])
  if final.exists() or final.is_symlink():fail('M8_TARGET_ALREADY_EXISTS')
  tmp.rename(final)
  print('M8_PREPARED_ISOLATED_SOURCE='+str(final),flush=True)
  return final
 except Exception:
  print('M8_PREPARE_STOP_ORPHAN_REQUIRES_REVIEW='+str(tmp),file=sys.stderr,flush=True)
  raise

def logged(cand,cmd,name,timeout=1800):
 log=cand/name
 if log.exists() or log.is_symlink():fail('M8_LOG_EXISTS:'+name)
 with log.open('x') as f:
  try:r=subprocess.run(cmd,cwd=cand,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
  except subprocess.TimeoutExpired:fail('M8_TEST_TIMEOUT:'+name)
  f.flush();os.fsync(f.fileno())
 if r.returncode:
  print('M8_FAILED_TEST_LOG='+str(log),flush=True)
  fail('M8_TEST_PROCESS_FAILED:'+name+':'+str(r.returncode))
 return log.read_text(errors='replace')

def compose_guard(cand):
 prefix=['docker','compose','-p',PROJECT,'-f',COMPOSE]
 p=subprocess.run(prefix+['config','--format','json'],cwd=cand,text=True,capture_output=True,timeout=30)
 if p.returncode:fail('M8_COMPOSE_CONFIG_ERROR')
 obj=json.loads(p.stdout)
 if obj.get('name')!=PROJECT or set(obj.get('services',{}))!={'test-db','backend-tests'}:fail('M8_COMPOSE_NAME_OR_SET')
 for c in obj['services'].values():
  if any(c.get(k) for k in ('ports','privileged','network_mode','volumes','devices','pid','ipc','cap_add','extra_hosts','container_name')):fail('M8_COMPOSE_UNSAFE_SERVICE')
 for kind in ('networks','volumes'):
  if any(v.get('external') for v in obj.get(kind,{}).values()):fail('M8_EXTERNAL_COMPOSE_RESOURCE')
 d=obj['services']['test-db'];r=obj['services']['backend-tests'];env=r.get('environment',{})
 u=urlsplit(env.get('FIELDWORK_TEST_DATABASE_URL',''))
 if not d.get('tmpfs') or d.get('volumes') or env.get('FIELDWORK_TESTING')!='1' or 'DATABASE_URL' in env or u.hostname!='test-db' or u.port!=5432:fail('M8_DATABASE_NOT_ISOLATED')
 p=subprocess.run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT],capture_output=True,text=True,timeout=30)
 if p.returncode or p.stdout.strip():fail('M8_TEST_COMPOSE_ALREADY_EXISTS')
 print('M8_ISOLATED_POSTGRES_FULL_TEST_GUARD=PASS',flush=True)
 return prefix

def full_tests(cand):
 prefix=compose_guard(cand)
 logged(cand,['docker','build','--progress=plain','-f','Dockerfile.m6-frontend-test',
             '-t','fieldwork-frontend-gate:parity-m8-editor','.'],'m8-editor-frontend-build.log')
 frontend=logged(cand,['docker','run','--rm','--network','none','--cap-drop','ALL',
                      '--security-opt','no-new-privileges','fieldwork-frontend-gate:parity-m8-editor',
                      'sh','-lc','npm run typecheck && npm run lint && npm test'],
                      'm8-editor-frontend-test.log',1200)
 if not re.search(r'Test Files\s+19 passed \(19\)',frontend) or not re.search(r'Tests\s+112 passed \(112\)',frontend):fail('M8_FRONTEND_EXACT_COUNT_NOT_PROVEN')
 print('M8_FRONTEND_TYPECHECK_ESLINT_112_TESTS=PASS',flush=True)
 started=False
 try:
  started=True
  logged(cand,prefix+['up','-d','--wait','--wait-timeout','120','test-db'],'m8-editor-db-up.log',360)
  backend=logged(cand,prefix+['run','--rm','--build','-e','PYTHONPATH=/app','backend-tests',
                     'python','-m','pytest','-v','tests'],'m8-editor-backend-test.log')
  if not re.search(r'\b109 passed\b',backend):fail('M8_BACKEND_EXACT_COUNT_NOT_PROVEN')
  for name in M8_TEST_NAMES:
   if not re.search(r'^tests/test_editor_team_m8.py::'+re.escape(name)+r'\s+PASSED',backend,re.M):fail('M8_REQUIRED_BACKEND_CASE_MISSING:'+name)
  print('M8_POSTGRES_BACKEND_109_TESTS=PASS',flush=True)
 finally:
  if started:
   done=subprocess.run(prefix+['down','--remove-orphans'],cwd=cand,text=True,capture_output=True,timeout=120)
   (cand/'m8-editor-test-cleanup.log').write_text('CLEANUP_EXIT='+str(done.returncode)+'\n')
   if done.returncode:fail('M8_POSTGRES_CLEANUP_FAILED')
 print('M8_EDITOR_VISIBILITY_TEAM_PICKER_SCOPE_SYNC_TESTS_PASS_NO_DEPLOYMENT',flush=True)

def main():
 p=argparse.ArgumentParser()
 group=p.add_mutually_exclusive_group(required=True)
 group.add_argument('--precheck',action='store_true')
 group.add_argument('--prepare-and-test',action='store_true')
 args=p.parse_args()
 r=precheck(); data=render(r)
 if args.precheck:print('M8_PRECHECK_ONLY_NO_DEPLOYMENT=YES',flush=True)
 else:
  cand=prepare(data)
  full_tests(cand)
  print('M8_FULL_NATIVE_TESTS_PASS_NOT_DEPLOYED=YES',flush=True)

if __name__=='__main__':
 try:main()
 except (GateStop,ValueError,KeyError,OSError,TypeError,subprocess.TimeoutExpired) as e:
  print('STOP: '+str(e),file=sys.stderr,flush=True)
  sys.exit(2)
