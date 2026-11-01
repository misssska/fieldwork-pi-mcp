#!/usr/bin/env python3
"""FieldWork M8 verified local Pi inbox admission; never deploys.

Only a pinned, inert artifact already verified through Pi MCP is executed by
explicit local Linux admin approval, into a NEW private M7 source/test sandbox.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, stat, subprocess, sys, tempfile, zipfile
from pathlib import Path, PurePosixPath

SHA='a79d755cfdeff6dd6ab3aa7e45b27c2f45e9f52ad3787f03ada5c6be88219fce'
BYTES=23989
TRANSFER='a79d755cfdeff6dd6ab3aa7e45b27c2f'
STATE=Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
DEST=STATE/('.m8-editor-inbox-'+SHA[:16])
PREFIX='FieldWork_M8/'
FILES={'MANIFEST.json','README_HU.md','baseline_sources.zip','build.py',
       'm8_editor_overlay.py','m8_candidate.py','test_build.py',
       'test_m8_integration_static.py','test_editor_team_backend.py'}

def deny(code):
    raise RuntimeError('M8_INBOX_STOP:'+code)

def hash_file(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(65536),b''):h.update(c)
    return h.hexdigest()

def locate():
    found=[]
    for base in (Path.home()/'.local/state',Path.home()/'.local/share'):
        if base.is_symlink() or not base.is_dir():continue
        for path,dirs,files in os.walk(base,followlinks=False):
            dirs[:]=[x for x in dirs if x not in ('.git','node_modules','.venv','__pycache__') and not (Path(path)/x).is_symlink()]
            for name in files:
                f=Path(path)/name
                try:
                    if f.is_symlink() or f.stat().st_size!=BYTES:continue
                    if hash_file(f)==SHA:found.append(f)
                except OSError:pass
                if len(found)>1:deny('MULTIPLE_EXACT_ARCHIVES')
    if len(found)!=1:deny('EXACT_VERIFIED_ARCHIVE_NOT_FOUND')
    return found[0]

def verified_zip(file):
    with zipfile.ZipFile(file) as z:
        infos=z.infolist()
        if len(infos)!=len(FILES) or {i.filename for i in infos}!={PREFIX+n for n in FILES}:
            deny('ZIP_ENTRY_SET_INVALID')
        if any(info.file_size>64_000 or info.compress_size>64_000 for info in infos):
            deny('ZIP_FILE_SIZE_OVER_LIMIT')
        for info in infos:
            rel=info.filename[len(PREFIX):]
            if (not rel or len(PurePosixPath(rel).parts)!=1 or rel.startswith(('/', '.'))
                or '\\' in rel or info.is_dir() or stat.S_IFMT(info.external_attr>>16) not in (0,stat.S_IFREG)):
                deny('UNSAFE_ARCHIVE_ENTRY')
        md=json.loads(z.read(PREFIX+'MANIFEST.json'))
        if md.get('kind')!='fieldwork-m8-editor-team-scope-source-v1' or md.get('not_deployed') is not True:
            deny('MANIFEST_SCOPE_DRIFT')
        pins=md.get('sha256')
        if set(pins or {})!=FILES-{'MANIFEST.json'}:deny('MANIFEST_FILE_SET_DRIFT')
        for name,h in pins.items():
            if not re.fullmatch('[a-f0-9]{64}',h) or hashlib.sha256(z.read(PREFIX+name)).hexdigest()!=h:
                deny('BUNDLE_FILE_HASH_MISMATCH:'+name)
    print('M8_VERIFIED_MCP_INBOX_SHA256_AND_MANIFEST=PASS',flush=True)

def extract(file):
    if DEST.exists() or DEST.is_symlink():
        if not DEST.is_dir() or DEST.is_symlink():deny('EXTRACTED_BUNDLE_NOT_DIRECTORY')
        with zipfile.ZipFile(file) as z:
            for name in FILES:
                f=DEST/name
                if f.is_symlink() or not f.is_file() or f.read_bytes()!=z.read(PREFIX+name):
                    deny('EXTRACTED_BUNDLE_TAMPERED:'+name)
        return DEST
    if STATE.is_symlink() or not STATE.is_dir() or STATE.stat().st_uid!=os.geteuid():
        deny('UNSAFE_STAGE_ROOT')
    tmp=Path(tempfile.mkdtemp(prefix='.m7-inbox-',dir=STATE))
    try:
        with zipfile.ZipFile(file) as z:
            for name in sorted(FILES):
                out=tmp/name
                with out.open('xb') as w:w.write(z.read(PREFIX+name))
                out.chmod(0o600)
        tmp.rename(DEST)
        return DEST
    except Exception:
        shutil.rmtree(tmp,ignore_errors=True)
        raise

def main():
    ap=argparse.ArgumentParser()
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--precheck',action='store_true')
    mode.add_argument('--prepare-and-test',action='store_true')
    args=ap.parse_args()
    if os.geteuid()==0:deny('ROOT_NOT_ALLOWED')
    file=locate();verified_zip(file)
    if args.precheck:
        print('M8_PRECHECK_ONLY_NOT_EXECUTED=YES',flush=True);return
    bundle=extract(file)
    p=subprocess.run([sys.executable,'-B',str(bundle/'m8_candidate.py'),'--prepare-and-test'],cwd=bundle)
    if p.returncode:deny('M8_PREPARE_OR_NATIVE_TEST_FAILED_EXIT_'+str(p.returncode))
    print('M8_ISOLATED_SOURCE_AND_NATIVE_TESTS_PASS_NO_DEPLOYMENT',flush=True)

if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as e:
        print(str(e),file=sys.stderr,flush=True)
        sys.exit(2)
