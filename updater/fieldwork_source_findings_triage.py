#!/usr/bin/env python3
"""Read-only, no-secret-output triage of one pinned local FieldWork source ZIP.

Run only after the exact SHA/manifest verification performed by the companion
fieldwork_private_archive_audit.py. This report is never publication approval.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import zipfile

AUDITOR_SHA256 = '86a1e4dc8edf86e41ea39e57f78ccd31e26864c8d70cbe7b0775f421a530ad4e'
ARCHIVE_SHA256 = '6ed1902f0c7df48ef61841f5dafe2a2d04463ce7168e276decc42d7a2c0e8195'
EXPECTED_FINDINGS = 34
HUMAN_REVIEW_REQUIRED = True

class TriageDenied(ValueError):
    pass

def classify(name: str, line: bytes, match: re.Match[bytes]) -> str:
    # No line/regex match value may ever leave this function.
    low = line.lower()
    if b'${' in line or b'${{' in line:
        return 'environment_template_review'
    if any(token in low for token in (b'os.environ', b'os.getenv(', b'getenv(', b'settings.', b'getpass(', b'get_secret(')):
        return 'runtime_or_environment_reference_review'
    if name.startswith('server/tests/') or name.endswith('.test.py'):
        return 'test_fixture_assignment_review'
    # Hard-coded strings in production code are higher priority and stay blocked.
    if re.search(rb'(?:[:=]\s*["\x27])', line):
        return 'possible_literal_assignment_review'
    return 'expression_or_unknown_assignment_review'

def triage(archive: Path, auditor_path: Path) -> dict:
    if not (archive.is_absolute() and archive.is_file() and not archive.is_symlink()
            and auditor_path.is_absolute() and auditor_path.is_file()
            and not auditor_path.is_symlink()):
        raise TriageDenied('INPUT_PATH_DENIED')
    if hashlib.sha256(auditor_path.read_bytes()).hexdigest() != AUDITOR_SHA256:
        raise TriageDenied('AUDITOR_SHA256_MISMATCH')
    if not (0 < archive.stat().st_size <= 50*1024*1024):
        raise TriageDenied('ARCHIVE_SIZE_DENIED')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise TriageDenied('ARCHIVE_SHA256_MISMATCH')
    spec = importlib.util.spec_from_file_location('trusted_fieldwork_archive_audit', auditor_path)
    if spec is None or spec.loader is None:
        raise TriageDenied('AUDITOR_IMPORT_DENIED')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit(archive)
    if not (report['status'] == 'SOURCE_STRUCTURE_AND_SHA_PASS'
            and report['files'] == 107
            and report['findings_count'] == EXPECTED_FINDINGS
            and not report['findings_truncated']
            and set(x['rule'] for x in report['findings']) == {'suspicious_assignment'}):
        raise TriageDenied('AUDIT_RECEIPT_DRIFT')
    expected = {(x['file'], x['line']) for x in report['findings']}
    if len(expected) != EXPECTED_FINDINGS:
        raise TriageDenied('DUPLICATE_OR_AMBIGUOUS_FINDING')
    rows=[]
    with zipfile.ZipFile(archive) as z:
        pattern = module.SECRET_PATTERNS['suspicious_assignment']
        for name in sorted({x['file'] for x in report['findings']}):
            data=z.read(name)
            for match in pattern.finditer(data):
                if module.PLACEHOLDER.search(match.group(0)):
                    continue
                lineno=module.line_no(data,match.start())
                if (name,lineno) not in expected:
                    raise TriageDenied('FINDING_LOCATION_MISMATCH')
                line=data.splitlines()[lineno-1]
                rows.append({'file': name, 'line': lineno,
                             'category': classify(name,line,match),
                             'review_required': True})
    if len(rows) != EXPECTED_FINDINGS or {(x['file'],x['line']) for x in rows} != expected:
        raise TriageDenied('FINDING_SET_MISMATCH')
    counts={}
    for x in rows:
        counts[x['category']]=counts.get(x['category'],0)+1
    return {'status':'LOCAL_ASSIGNMENT_TRIAGE_COMPLETE',
            'archive_sha256':ARCHIVE_SHA256,'findings_count':EXPECTED_FINDINGS,
            'categories':dict(sorted(counts.items())), 'findings':rows,
            'sensitive_values_emitted':False,'human_review_required':True,
            'ready_to_upload':False,'git_push_performed':False,
            'production_modified':False}

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive',type=Path,required=True)
    ap.add_argument('--auditor',type=Path,required=True)
    args=ap.parse_args()
    try:
        result=triage(args.archive,args.auditor)
    except (TriageDenied, OSError, zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        # Do not render any exception repr (which might contain content).
        code=str(exc) if isinstance(exc,TriageDenied) else 'TRIAGE_BLOCKED'
        print(json.dumps({'status':'BLOCKED','reason':code,'ready_to_upload':False}))
        raise SystemExit(2) from None
    print(json.dumps(result,sort_keys=True,indent=2))
if __name__ == '__main__':
    main()
