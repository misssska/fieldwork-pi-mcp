"""Fail-closed, in-memory extension of an already qualified async-stage MCP candidate.

This module does not install, restart, or modify the Pi. It refuses drifted
source and never accepts arbitrary command arguments.
"""
from __future__ import annotations

import ast

IMPORT_OLD = 'import stage_async\n'
IMPORT_NEW = IMPORT_OLD + 'import stage_inspect\nimport stage_start_async\n'

TOOLS_OLD = '''    ("fieldwork_stage_start", "Build and start fixed stage Docker project after full test PASS; no production access", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_manager.start),
    ("fieldwork_stage_status", "Read fixed stage Docker project status", {}, stage_manager.status),
'''
TOOLS_NEW = TOOLS_OLD + '''    ("fieldwork_stage_start_request", "Queue fixed stage-only Docker start in detached worker; never touches production", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_start_async.request),
    ("fieldwork_stage_start_status", "Read durable fixed stage-only start receipt", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_start_async.status),
    ("fieldwork_stage_inspect", "Inspect fixed stage Docker container states including stopped services; no raw logs", {}, stage_inspect.status),
'''

ANNOTATION_OLD = '"fieldwork_stage_test_request", "fieldwork_stage_start", "fieldwork_stage_stop"'
ANNOTATION_NEW = '"fieldwork_stage_test_request", "fieldwork_stage_start", "fieldwork_stage_start_request", "fieldwork_stage_stop"'

class SourceDriftError(ValueError):
    pass


def overlay(original: bytes) -> bytes:
    try:
        source = original.decode('utf-8')
        ast.parse(source)
    except (UnicodeError, SyntaxError) as exc:
        raise SourceDriftError('INVALID_CANDIDATE_SOURCE') from exc
    if any(name in source for name in ('fieldwork_stage_inspect', 'fieldwork_stage_start_request', 'import stage_inspect', 'import stage_start_async')):
        raise SourceDriftError('ALREADY_PATCHED_OR_PARTIAL')
    for old, new in ((IMPORT_OLD, IMPORT_NEW), (TOOLS_OLD, TOOLS_NEW), (ANNOTATION_OLD, ANNOTATION_NEW)):
        if source.count(old) != 1:
            raise SourceDriftError('INTEGRATION_ANCHOR_MISMATCH')
        source = source.replace(old, new, 1)
    ast.parse(source)
    return source.encode('utf-8')
