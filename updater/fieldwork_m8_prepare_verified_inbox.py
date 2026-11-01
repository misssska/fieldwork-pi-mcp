#!/usr/bin/env python3
"""SHA-pinned M8 private Pi inbox loader and native tests – NO DEPLOYMENT."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, stat, subprocess, sys, tempfile, zipfile
from pathlib import Path, PurePosixPath

SHA='cbd2607f1b72d3cf464cb0b1a3e18502a92b0ebcbf8ab088369c44d5a4449a09'
BYTES=16792
TRANSFER='cbd2607f1b72d3cf464cb0b1a3e18502'
STATE=Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
DEST=STATE/('.m8-auth-inbox-'+SHA[:16])
PREFIX='FieldWork_M8/'
FILES={'MANIFEST.json','m8_candidate.py','m8_security_overlay.py','test_security_m8.py',
       'test_m8_overlay.py','team_api.py','test_team_m4.py','README_HU.md'}


def fail(code):raise RuntimeError('M8_INBOX_STOP:'+code)
def file_sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for data in iter(lambda:f.read(65536),b''):h.update(data)
 return h.hexdigest()


def locate_exact():
 found=[]
 for parent in (Path.home()/'.local/state',Path.home()/'.local/share'):
  if parent.is_symlink() or not parent.is_dir():continue
  for folder,dirs,names in os.walk(parent,followlinks=False):
   dirs[:]=[d for d in dirs if d not in ('.venv','.git','node_modules','__pycache__') and not (Path(folder)/d).is_symlink()]
   for name in names:
    p=Path(folder)/name
    try:
     if p.is_symlink() or p.stat().st_size!=BYTES:continue
     if file_sha(p)==SHA:found.append(p)
    except OSError:continue
    if len(found)>1:fail('MULTIPLE_MATCHING_ARCHIVES')
 if len(found)!=1:fail('EXACT_M8_TRANSFER_ARCHIVE_NOT_FOUND')
 return found[0]


def verify_zip(p):
 with zipfile.ZipFile(p) as z:
  entries=z.infolist()
  if len(entries)!=len(FILES) or set(i.filename for i in entries)!={PREFIX+x for x in FILES}:
   fail('ZIP_ENTRY_SET_INVALID')
  for i in entries:
   rel=i.filename[len(PREFIX):]
   if (not rel or len(PurePosixPath(rel).parts)!=1 or '\\' in rel or rel.startswith(('/', '.'))
       or i.is_dir() or i.file_size>100000 or i.compress_size>100000
       or stat.S_IFMT(i.external_attr>>16) not in (0,stat.S_IFREG)):
    fail('ZIP_ENTRY_UNSAFE')
  m=json.loads(z.read(PREFIX+'MANIFEST.json'))
  if m.get('kind')!='fieldwork-m8-authz-sync-isolated-v1' or m.get('not_deployed') is not True:
   fail('M8_MANIFEST_TYPE_DRIFT')
  pins=m.get('sha256')
  if not isinstance(pins,dict) or set(pins)!=FILES-{'MANIFEST.json'}:fail('M8_MANIFEST_FILE_SET')
  for name,sha in pins.items():
   if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):fail('M8_MANIFEST_BAD_HASH')
   if hashlib.sha256(z.read(PREFIX+name)).hexdigest()!=sha:fail('M8_MEMBER_HASH_DRIFT:'+name)
 print('M8_INERT_ARCHIVE_AND_MANIFEST_SHA256=PASS',flush=True)


def extract(p):
 if not STATE.is_dir() or STATE.is_symlink() or STATE.stat().st_uid!=os.geteuid():fail('STATE_UNOWNED')
 if DEST.exists() or DEST.is_symlink():
  if DEST.is_symlink() or not DEST.is_dir():fail('PREVIOUS_EXTRACT_UNSAFE')
  with zipfile.ZipFile(p) as z:
   for name in FILES:
    f=DEST/name
    if f.is_symlink() or not f.is_file() or f.read_bytes()!=z.read(PREFIX+name):
     fail('PREVIOUS_EXTRACT_DRIFT:'+name)
  return DEST
 tmp=Path(tempfile.mkdtemp(prefix='.m8-extract-',dir=STATE))
 try:
  with zipfile.ZipFile(p) as z:
   for name in sorted(FILES):
    with (tmp/name).open('xb') as out:out.write(z.read(PREFIX+name))
    (tmp/name).chmod(0o600)
  tmp.rename(DEST)
  return DEST
 except Exception:
  shutil.rmtree(tmp,ignore_errors=True);raise


def main():
 p=argparse.ArgumentParser()
 a=p.add_mutually_exclusive_group(required=True)
 a.add_argument('--precheck',action='store_true')
 a.add_argument('--prepare-and-test',action='store_true')
 args=p.parse_args()
 if os.geteuid()==0:fail('ROOT_NOT_ALLOWED')
 archive=locate_exact();verify_zip(archive)
 if args.precheck:
  print('M8_PRECHECK_ONLY_NO_SOURCE_WRITES=YES',flush=True);return
 src=extract(archive)
 result=subprocess.run([sys.executable,'-B',str(src/'m8_candidate.py'),'--prepare-and-test'],cwd=src)
 if result.returncode:fail('M8_NATIVE_PREPARATION_OR_TEST_FAILED_EXIT_'+str(result.returncode))
 print('M8_SOURCE_AND_NATIVE_RBAC_TESTS_PASS_NOT_DEPLOYED',flush=True)

if __name__=='__main__':
 try:main()
 except (RuntimeError,OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
  print(str(exc),file=sys.stderr,flush=True);sys.exit(2)
