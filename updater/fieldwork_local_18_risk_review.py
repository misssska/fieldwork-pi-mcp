#!/usr/bin/env python3
"""Read-only, sealed 18-location syntactic review of one exact FieldWork ZIP.

Reports no source line, token, password, secret length or value. Never uploads.
No result grants GitHub-import approval. Requires unchanged pinned triage/auditor.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import zipfile

ARCHIVE_SHA = '6ed1902f0c7df48ef61841f5dafe2a2d04463ce7168e276decc42d7a2c0e8195'
TRIAGE_SHA = '5867394ce296227619eb1bc864905bb622bddbf7c7f625d6cdbc3ec49be20b76'
AUDITOR_SHA = '86a1e4dc8edf86e41ea39e57f78ccd31e26864c8d70cbe7b0775f421a530ad4e'
EXPECTED = {
    '.github/workflows/backend-tests.yml': (19, 33, 35),
    'docker-compose.e2e.yml': (9, 24, 26),
    'docker-compose.test.yml': (9, 25, 27),
    'server/app/models.py': (16,),
    'server/scripts/init_db.py': (21,),
    'server/scripts/rotate_admin_password.py': (25, 26, 27, 50, 51, 52, 83),
}

class ReviewBlocked(Exception):
    pass


def checked_sha(path: Path, digest: str, kind: str) -> None:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ReviewBlocked(kind + '_PATH_DENIED')
    if not 0 < path.stat().st_size < 50 * 1024 * 1024:
        raise ReviewBlocked(kind + '_SIZE_DENIED')
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ReviewBlocked(kind + '_SHA256_MISMATCH')


def import_checked(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ReviewBlocked('IMPORT_UNAVAILABLE')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def yaml_shape(line: str) -> str:
    # Do not return or interpolate any content from `line`.
    if ':' not in line:
        return 'yaml_unrecognized_review'
    rhs = line.split(':', 1)[1].strip()
    if not rhs:
        return 'yaml_empty_value_review'
    if '${' in rhs or '{{' in rhs:
        return 'yaml_variable_template_review'
    if rhs.startswith(('[', '{')):
        return 'yaml_structured_expression_review'
    if rhs.startswith(('*', '&')):
        return 'yaml_alias_review'
    # Both quoted and unquoted static values require human review.
    return 'yaml_inline_value_review'


def python_shape(tree: ast.AST, lineno: int) -> str:
    # Only inspect node structure, never ast.unparse/dump or constant values.
    matching = []
    for node in ast.walk(tree):
        if getattr(node, 'lineno', None) != lineno:
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.keyword)):
            matching.append(node)
    if not matching:
        return 'python_unrecognized_expression_review'
    field = next((n for n in matching if isinstance(n, ast.AnnAssign)), None)
    if field is not None:
        return 'python_annotated_field_definition_review'
    candidate = next((n for n in matching if isinstance(n, ast.keyword)), None)
    if candidate is None:
        candidate = next(iter(matching))
    rhs = getattr(candidate, 'value', None)
    if rhs is None:
        return 'python_unrecognized_expression_review'
    if isinstance(rhs, (ast.Constant, ast.JoinedStr)):
        return 'python_direct_literal_review'
    if isinstance(rhs, (ast.Name, ast.Attribute, ast.Subscript)):
        return 'python_runtime_reference_review'
    if isinstance(rhs, ast.Call):
        return 'python_function_result_review'
    return 'python_computed_expression_review'


def review(archive: Path, triage_path: Path, auditor_path: Path) -> dict:
    checked_sha(archive, ARCHIVE_SHA, 'ARCHIVE')
    checked_sha(triage_path, TRIAGE_SHA, 'TRIAGE')
    checked_sha(auditor_path, AUDITOR_SHA, 'AUDITOR')
    triage = import_checked(triage_path, 'fieldwork_pinned_triage_18')
    triage_result = triage.triage(archive, auditor_path)
    if (triage_result.get('status') != 'LOCAL_ASSIGNMENT_TRIAGE_COMPLETE'
            or triage_result.get('findings_count') != 34
            or triage_result.get('ready_to_upload') is not False
            or triage_result.get('sensitive_values_emitted') is not False):
        raise ReviewBlocked('TRIAGE_RECEIPT_DRIFT')
    unknown = {(x['file'], x['line']) for x in triage_result['findings']
               if x['category'] == 'expression_or_unknown_assignment_review'}
    expected = {(p, n) for p, linenos in EXPECTED.items() for n in linenos}
    if len(unknown) != 18 or unknown != expected:
        raise ReviewBlocked('EXACT_18_FINDINGS_DRIFT')
    rows=[]
    with zipfile.ZipFile(archive, 'r') as z:
        for filename, numbers in EXPECTED.items():
            src = z.read(filename)
            lines = src.decode('utf-8', errors='strict').splitlines()
            if filename.endswith('.py'):
                try:
                    tree = ast.parse(src, filename='<private-python-source>')
                except (SyntaxError, ValueError):
                    raise ReviewBlocked('PYTHON_SYNTAX_REVIEW_BLOCKED') from None
            else:
                tree = None
            for lineno in numbers:
                if lineno <= 0 or lineno > len(lines):
                    raise ReviewBlocked('SOURCE_LINE_DRIFT')
                category = (python_shape(tree, lineno) if tree is not None
                            else yaml_shape(lines[lineno-1]))
                rows.append({'file': filename, 'line': lineno, 'syntax_class': category,
                             'review_required': True})
    counts={}
    for row in rows:
        counts[row['syntax_class']]=counts.get(row['syntax_class'],0)+1
    return {'status': 'LOCAL_18_SYNTAX_REVIEW_COMPLETE', 'archive_sha256': ARCHIVE_SHA,
            'findings_examined':len(rows), 'categories':dict(sorted(counts.items())),
            'findings':rows, 'secret_values_emitted':False,
            'ready_to_upload':False, 'manual_secret_and_license_review_required':True,
            'git_push_performed':False, 'production_modified':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--triage',type=Path,required=True)
    p.add_argument('--auditor',type=Path,required=True)
    args=p.parse_args()
    try:
        result=review(args.archive,args.triage,args.auditor)
    except Exception as e:
        code = str(e) if isinstance(e,ReviewBlocked) else 'REVIEW_CANNOT_BE_VERIFIED'
        print(json.dumps({'status':'BLOCKED','reason':code,'ready_to_upload':False}))
        raise SystemExit(2) from None
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == '__main__':
    main()
