"""Fail-closed in-memory MCP extension for static canary archive qualification.

The existing four artifact transport tools remain unchanged. This extension
adds a fifth *read-only* qualification endpoint, never deployment.
It must be locally activated only after exact source SHA verification.
"""
from __future__ import annotations
import ast

IMPORT_OLD = "import artifact_inbox_adapter\n"
IMPORT_NEW = IMPORT_OLD + "import canary_archive_qualifier\nimport canary_archive_adapter\n"

TOOLS_OLD = '''    ("fieldwork_artifact_finalize", "Verify complete artifact SHA256; never deploy", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, artifact_inbox_adapter.finalize),
'''
TOOLS_NEW = TOOLS_OLD + '''    ("fieldwork_artifact_qualify", "Statically validate verified source ZIP manifest, allowlisted paths and SHA256; never execute", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, canary_archive_adapter.qualify),
'''
ANNOTATION_OLD = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start", "fieldwork_artifact_begin", "fieldwork_artifact_append", "fieldwork_artifact_status", "fieldwork_artifact_finalize"'
ANNOTATION_NEW = ANNOTATION_OLD + ', "fieldwork_artifact_qualify"'


class SourceDrift(ValueError):
    pass


def overlay(original: bytes) -> bytes:
    if type(original) is not bytes or not 0 < len(original) <= 1_000_000:
        raise SourceDrift("MCP_SOURCE_INVALID")
    try:
        source = original.decode("utf-8")
        ast.parse(source)
    except (UnicodeError, SyntaxError) as exc:
        raise SourceDrift("MCP_SOURCE_INVALID") from exc
    if "fieldwork_artifact_qualify" in source or "import canary_archive_adapter" in source:
        raise SourceDrift("ALREADY_PATCHED_OR_PARTIAL")
    for old, new in ((IMPORT_OLD, IMPORT_NEW),
                     (TOOLS_OLD, TOOLS_NEW),
                     (ANNOTATION_OLD, ANNOTATION_NEW)):
        if source.count(old) != 1:
            raise SourceDrift("INTEGRATION_ANCHOR_DRIFT")
        source = source.replace(old, new, 1)
    ast.parse(source)
    return source.encode("utf-8")
