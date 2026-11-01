#!/usr/bin/env python3
"""Exact FieldWork M5 candidate backend log metadata, never prints source/log values."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

CANDIDATE = 'parity-m5.kTQUQUdP'
REQUIRED = frozenset({
    'test_photo_comment_persists_and_does_not_pollute_task_comments',
    'test_photo_comment_unauthenticated_and_cross_project_access',
    'test_viewer_can_read_but_cannot_post',
    'test_invalid_and_conflicting_comments_rejected',
    'test_deleted_photo_and_task_are_inaccessible',
})
STRIP_ANSI = re.compile(r'\x1b\[[0-9;]*m')
STATUS = ('PASSED','FAILED','ERROR','SKIPPED','XFAIL','XPASS')
STATUS_RE = re.compile(r'(?m)^\s*(?:tests|server/tests)/[^\s:]+\.py::\S+\s+(PASSED|FAILED|ERROR|SKIPPED|XPASS|XFAIL)\b')
TEST_RE = re.compile(r'(?m)^\s*(?:tests|server/tests)/test_photo_comments_m5\.py::([a-zA-Z][a-zA-Z_0-9]*)\s+(PASSED|FAILED|ERROR|SKIPPED|XPASS|XFAIL)\b')
COLLECT_RE = re.compile(r'(?m)^collected\s+(\d+)\s+items?\b')
SUMMARY_STRICT = re.compile(r'^=+\s+(\d+) passed(?:, \d+ warnings?)? in [0-9.]+s\s+=+$')
SUMMARY_WIDE = re.compile(r'^=+\s+(.{1,220}?)\s+=+$')
COUNT_TOKEN = re.compile(r'(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|warnings?|deselected)\b')

class Denied(Exception): pass

def diagnose(logpath: Path) -> dict:
    if not logpath.is_absolute() or logpath.name != 'm5-backend-test.log' or logpath.is_symlink():
        raise Denied('EXACT_LOG_PATH_REQUIRED')
    home = Path.home()
    base = home / '.local/state/fieldwork-pi-mcp-v03/stage-v06' / CANDIDATE
    if base.is_symlink() or not base.is_dir() or logpath.parent != base or base.resolve() != base:
        raise Denied('UNEXPECTED_CANDIDATE_OR_SYMLINK')
    if not logpath.is_file() or not (0 < logpath.stat().st_size <= 12_000_000):
        raise Denied('LOG_MISSING_OR_OVERSIZE')
    raw = logpath.read_bytes()
    if b'\x00' in raw:
        raise Denied('BINARY_LOG')
    try:
        data = STRIP_ANSI.sub('',raw.decode('utf-8')).replace('\r\n','\n')
    except UnicodeDecodeError:
        raise Denied('NON_UTF8_LOG') from None
    allrows = Counter(STATUS_RE.findall(data))
    m5rows = TEST_RE.findall(data)
    m5statuses = {name: status for name,status in m5rows if name in REQUIRED}
    tokens = Counter()
    strict = []
    summary_candidates = 0
    for line in data.splitlines():
        s=line.strip()
        if SUMMARY_STRICT.fullmatch(s):
            strict.append(int(SUMMARY_STRICT.fullmatch(s).group(1)))
        m=SUMMARY_WIDE.fullmatch(s)
        if m and COUNT_TOKEN.search(m.group(1)):
            summary_candidates+=1
            for count,word in COUNT_TOKEN.findall(m.group(1)):
                tokens[word]+=int(count)
    collected = [int(x) for x in COLLECT_RE.findall(data)]
    return {
        'status':'M5R7_BACKEND_LOG_STRUCTURAL_DIAGNOSTIC',
        'candidate':CANDIDATE,
        'log_bytes':len(raw),
        'log_sha256':hashlib.sha256(raw).hexdigest(),
        'pytest_session_banner_seen': 'test session starts' in data,
        'collected_counts':collected[:4],
        'recognized_verbose_test_rows':dict(sorted(allrows.items())),
        'recognized_m5_test_rows':len(m5rows),
        'required_m5_test_statuses':{n:m5statuses.get(n,'NOT_SEEN') for n in sorted(REQUIRED)},
        'strict_success_summary_counts':strict,
        'generic_summary_lines_with_numeric_test_counts':summary_candidates,
        'generic_summary_numeric_tokens':dict(sorted(tokens.items())),
        'raw_log_or_secret_content_emitted':False,
        'backend_verified':False,
        'release_authorized':False,
        'production_modified':False,
    }

def main():
    p=Path.home()/'.local/state/fieldwork-pi-mcp-v03/stage-v06'/CANDIDATE/'m5-backend-test.log'
    try:
        print(json.dumps(diagnose(p),indent=2,sort_keys=True,ensure_ascii=False))
    except (Denied,OSError) as e:
        print(json.dumps({'status':'BLOCKED','reason':str(e) if isinstance(e,Denied) else 'READ_FAILED','backend_verified':False,'release_authorized':False}))
        raise SystemExit(2)

if __name__=='__main__':
    main()
