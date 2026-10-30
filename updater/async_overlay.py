"""Build a staged Async Stage MCP candidate without overwriting installed source.

This only transforms source bytes in memory; never installs or restarts anything.
Fails closed if integration anchors have drifted or tools already exist.
"""
import ast

IMPORT_OLD = 'import stage_manager\n'
IMPORT_NEW = 'import stage_manager\nimport stage_async\n'
TOOLS_OLD = '''    ("fieldwork_stage_full_test", "Run all backend tests including admin rotation using separate stage-only test Docker project", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_manager.full_test),
'''
TOOLS_NEW = TOOLS_OLD + '''    ("fieldwork_stage_test_request", "Start bounded full backend test in detached stage-only worker; returns immediately", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_async.request),
    ("fieldwork_stage_test_status", "Read durable detached stage-only test status", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_async.status),
'''
ANNOTATION_OLD = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start"'
ANNOTATION_NEW = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_test_request", "fieldwork_stage_start"'


class SourceDriftError(ValueError):
    pass


def overlay(original: bytes) -> bytes:
    try:
        source = original.decode('utf-8')
        ast.parse(source)
    except (UnicodeError, SyntaxError) as exc:
        raise SourceDriftError('INVALID_INSTALLED_SOURCE') from exc
    if 'fieldwork_stage_test_request' in source or 'import stage_async' in source:
        raise SourceDriftError('ALREADY_PATCHED_OR_PARTIAL')
    for old, new in ((IMPORT_OLD, IMPORT_NEW), (TOOLS_OLD, TOOLS_NEW), (ANNOTATION_OLD, ANNOTATION_NEW)):
        if source.count(old) != 1:
            raise SourceDriftError('INTEGRATION_ANCHOR_MISMATCH')
        source = source.replace(old, new, 1)
    ast.parse(source)
    return source.encode('utf-8')
