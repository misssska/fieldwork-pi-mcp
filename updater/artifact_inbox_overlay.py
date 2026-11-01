"""Fail-closed, in-memory adapter overlay against the base v0.6.1 MCP.

This source transformation is NOT an installer. It does not read or write an
installed MCP; caller must pin the currently installed SHA256, pass integration
and negative tests, obtain local approval and retain rollback evidence.
"""
from __future__ import annotations

import ast

IMPORT_OLD = "import stage_manager\n"
IMPORT_NEW = IMPORT_OLD + "import artifact_inbox_adapter\n"
TOOLS_OLD = '''    ("fieldwork_stage_full_test", "Run all backend tests including admin rotation using separate stage-only test Docker project", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_manager.full_test),
'''
TOOLS_NEW = TOOLS_OLD + '''    ("fieldwork_artifact_begin", "Reserve one exact SHA256-pinned inert canary upload; never deploy", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "size": {"type": "integer", "minimum": 1, "maximum": 33554432},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    }, artifact_inbox_adapter.begin),
    ("fieldwork_artifact_append", "Append ordered bounded base64 bytes; no execution", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "offset": {"type": "integer", "minimum": 0, "maximum": 33554432},
        "chunk_base64": {"type": "string", "minLength": 1, "maxLength": 44000}
    }, artifact_inbox_adapter.append),
    ("fieldwork_artifact_status", "Read inert upload receipt", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, artifact_inbox_adapter.status),
    ("fieldwork_artifact_finalize", "Verify complete artifact SHA256; never deploy", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, artifact_inbox_adapter.finalize),
'''
ANNOTATION_OLD = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start"'
ANNOTATION_NEW = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start", "fieldwork_artifact_begin", "fieldwork_artifact_append", "fieldwork_artifact_status", "fieldwork_artifact_finalize"'

class AdapterOverlayDenied(ValueError):
    pass


def overlay(original: bytes) -> bytes:
    if type(original) is not bytes or len(original) > 1_000_000:
        raise AdapterOverlayDenied("INVALID_SOURCE_BYTES")
    try:
        source = original.decode("utf-8")
        ast.parse(source)
    except (UnicodeError, SyntaxError) as exc:
        raise AdapterOverlayDenied("INVALID_SOURCE") from exc
    if "artifact_inbox_adapter" in source or "fieldwork_artifact_begin" in source:
        raise AdapterOverlayDenied("ALREADY_INSTALLED_OR_PARTIAL")
    for old, new in (
        (IMPORT_OLD, IMPORT_NEW),
        (TOOLS_OLD, TOOLS_NEW),
        (ANNOTATION_OLD, ANNOTATION_NEW),
    ):
        if source.count(old) != 1:
            raise AdapterOverlayDenied("ANCHOR_NOT_UNIQUE_OR_DRIFTED")
        source = source.replace(old, new, 1)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AdapterOverlayDenied("GENERATED_SOURCE_INVALID") from exc
    # Existence of four exact tool registration strings is a second safety check.
    actual = {node.value for node in ast.walk(tree)
              if isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value.startswith("fieldwork_artifact_")}
    if actual != {"fieldwork_artifact_begin", "fieldwork_artifact_append",
                  "fieldwork_artifact_status", "fieldwork_artifact_finalize"}:
        raise AdapterOverlayDenied("TOOL_REGISTRATION_MISMATCH")
    return source.encode("utf-8")
