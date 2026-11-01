#!/usr/bin/env python3
"""Read-only Pi M7 source pin/anchor inventory; never builds, writes or deploys."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

STATE = Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'
M6 = STATE/'parity-m6._sdfbhky'
BUNDLE = STATE/'.m7-video-inbox-5cdb3e58e5c6da62'
OVERLAY = BUNDLE/'video_overlay.py'
OVERLAY_SHA = '4aa0c67c0fe486194bcb0b8215bb32d0d9984378d1572051db3ebb3cfa918479'
SOURCE_RECEIPT = M6/'.m6-r9-source-receipt.json'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def deny(code):
    raise RuntimeError('M7_DIAG_STOP:'+code)


def regular(path):
    return path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(M6 if path.is_relative_to(M6) else BUNDLE)


def inspect():
    if os.geteuid()==0:deny('ROOT_DENIED')
    for p in (STATE,M6,BUNDLE):
        if not p.is_dir() or p.is_symlink() or p.stat().st_uid != os.geteuid():
            deny('EXPECTED_OWNER_OR_DIRECTORY_MISSING:'+p.name)
    if not regular(OVERLAY) or digest(OVERLAY)!=OVERLAY_SHA:deny('M7_UPLOADED_OVERLAY_SHA_DRIFT')
    if not regular(SOURCE_RECEIPT):deny('M6_RECEIPT_MISSING')
    receipt=json.loads(SOURCE_RECEIPT.read_text())
    if (receipt.get('status')!='M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED'
        or receipt.get('production_modified') is not False or len(receipt.get('modified',{}))!=11):
        deny('M6_RECEIPT_SCOPE_DRIFT')
    spec=importlib.util.spec_from_file_location('m7_diagnosis_overlay',OVERLAY)
    if not spec or not spec.loader:deny('MODULE_LOAD_FAIL')
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    results=[]
    for rel,want in sorted(m.SOURCE_PINS.items()):
        target=M6/rel
        if not regular(target):deny('EXPECTED_SOURCE_MISSING:'+rel)
        actual=digest(target)
        results.append({'file':rel,'expected':want,'actual':actual,'pin_ok':actual==want})
    patches=[]
    for rel in sorted(m.SOURCE_PATCHERS):
        target=M6/rel
        if not regular(target):deny('EXPECTED_PATCH_SOURCE_MISSING:'+rel)
        try:
            m.patch_existing(rel,target.read_bytes())  # deliberately skip SHA: patch in memory only
            status='PASS'
        except m.SourceStop as exc:
            status=str(exc)
        patches.append({'file':rel,'anchor':status})
    failures=[r for r in results if not r['pin_ok']]
    errors=[r for r in patches if r['anchor']!='PASS']
    print('M7_DIAG_READ_ONLY=YES')
    print(f'M7_SOURCE_PINS_MATCHED={len(results)-len(failures)}/{len(results)}')
    for r in results:
        print('PIN '+ ('PASS' if r['pin_ok'] else 'DIFF') +' '+r['file']+' '+r['actual'])
    print(f'M7_PATCH_ANCHORS_MATCHED={len(patches)-len(errors)}/{len(patches)}')
    for r in patches:print('ANCHOR '+r['file']+' '+r['anchor'])
    # A few known technical UI signatures only; no source excerpts, e-mails, passwords or tokens.
    if any(x['file']=='frontend/src/components/Documents.tsx' for x in failures+errors):
        p=(M6/'frontend/src/components/Documents.tsx').read_text(encoding='utf-8')
        for name,expr in [
            ('docs_allowed_types',r'ALLOWED_TYPES\s*=.*'),
            ('docs_import_viewer',r'import \{ DocumentViewer \}.*'),
            ('docs_label',r'[^\n]{0,50}PDF, JPEG, PNG[^\n]{0,80}'),
            ('docs_upload_box',r'<div className="upload-box document-upload"[^>]*>'),
            ('docs_file_accept',r'accept="[^\"]+"'),
        ]:
            matches=re.findall(expr,p)
            # display only count and SHA of normalized snippet, not possible sensitive content
            print('SIGNATURE '+name+' matches='+str(len(matches))+' digest='+hashlib.sha256('\n'.join(matches).encode()).hexdigest())
    print('M7_DIAG_SOURCE_ONLY_NO_DEPLOYMENT=YES')

if __name__=='__main__':
    try:
        ap=argparse.ArgumentParser()
        ap.add_argument('--report',action='store_true',required=True)
        ap.parse_args()
        inspect()
    except (RuntimeError,OSError,ValueError,KeyError,TypeError) as e:
        print(str(e),file=sys.stderr)
        sys.exit(2)
