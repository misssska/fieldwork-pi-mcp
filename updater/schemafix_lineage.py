"""Offline, read-only provenance audit of original v0.6.1 -> Schemafix-r1 -> lifecycle.

Input is exact trusted release bytes, NEVER installed Pi/production paths.
Does not unpack archives, execute supplied Python, invoke Docker/systemd,
install anything or grant activation. Safe to run in an isolated workspace.
"""
from __future__ import annotations

import ast
import hashlib

from updater import async_overlay
from experimental import lifecycle_overlay

BASE_SHA = 'b504460dc1477898dc048dc990e7fd432ba880926f9f063904cd6a9b085e5948'
SCHEMAFIX_SHA = '7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04'
ASYNC_R2_SHA = '5729060acf8b833523921954f232558db5c853aa87fb366e7f4c1488cd38f33f'
LIFECYCLE_SCHEMAFIX_SHA = 'b9d449ba2802b2f13e8e09252cdcf593007f3aeadfebe06010fa01ac2f5a62a5'
MAX_SOURCE = 1_000_000

OLD_REQUIRED = (
    '            required = [k for k in props if k in '
    '("path", "service", "patch", "expected_sha256", "proposal_id", "run_id")]\n'
)
NEW_REQUIRED = OLD_REQUIRED + (
    '            if name == "fieldwork_sandbox_runtime_test":\n'
    '                required.append("suite")\n'
    '            elif name == "fieldwork_sandbox_command":\n'
    '                required.extend(["command", "with_test_db"])\n'
)
OLD_INPUT_SCHEMA = (
    '                                          "required": required + (["suite"] '
    'if name == "fieldwork_sandbox_runtime_test" else (["run_id", "command", '
    '"with_test_db"] if name == "fieldwork_sandbox_command" else (["run_id"] '
    'if name == "fieldwork_sandbox_command_status" else []))), '
    '"additionalProperties": False},\n'
)
NEW_INPUT_SCHEMA = (
    '                                          "required": required, '
    '"additionalProperties": False},\n'
)
EXPECTED_TOOLS = frozenset((
    'fieldwork_stage_test_request', 'fieldwork_stage_test_status',
    'fieldwork_stage_start_request', 'fieldwork_stage_start_status',
    'fieldwork_stage_inspect',
))


class LineageBlocked(ValueError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise LineageBlocked(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_source(value: bytes) -> str:
    require(type(value) is bytes and 0 < len(value) <= MAX_SOURCE,
            'SOURCE_SIZE_OR_TYPE_DENIED')
    try:
        result = value.decode('utf-8')
        ast.parse(result)
    except (UnicodeError, SyntaxError) as exc:
        raise LineageBlocked('SOURCE_INVALID_PYTHON') from exc
    return result


def exact_schemafix(base: bytes, schemafix: bytes) -> bool:
    """Prove that Schemafix-r1 changes exactly the two expected spans."""
    source = _safe_source(base)
    _safe_source(schemafix)
    for old, new in ((OLD_REQUIRED, NEW_REQUIRED),
                     (OLD_INPUT_SCHEMA, NEW_INPUT_SCHEMA)):
        require(source.count(old) == 1, 'SCHEMAFIX_ANCHOR_MISMATCH')
        source = source.replace(old, new, 1)
    require(source.encode('utf-8') == schemafix,
            'SCHEMAFIX_UNEXPECTED_DIFFERENCES')
    return True


def audit(*, base: bytes, schemafix: bytes, async_r2: bytes) -> dict:
    """Return an attestation only. No candidate bytes, secrets or deployment."""
    _safe_source(base)
    _safe_source(schemafix)
    _safe_source(async_r2)
    require(sha(base) == BASE_SHA, 'BASE_HASH_MISMATCH')
    require(sha(schemafix) == SCHEMAFIX_SHA, 'SCHEMAFIX_HASH_MISMATCH')
    require(sha(async_r2) == ASYNC_R2_SHA, 'ASYNC_R2_HASH_MISMATCH')
    exact_schemafix(base, schemafix)
    try:
        verified_r2 = async_overlay.overlay(base)
        require(verified_r2 == async_r2, 'BASE_ASYNC_R2_MISMATCH')
        candidate = lifecycle_overlay.overlay(async_overlay.overlay(schemafix))
    except (ValueError, SyntaxError) as exc:
        raise LineageBlocked('LIFECYCLE_OVERLAY_BLOCKED') from exc
    require(sha(candidate) == LIFECYCLE_SCHEMAFIX_SHA,
            'LIFECYCLE_SCHEMAFIX_HASH_MISMATCH')
    tree = ast.parse(candidate.decode('utf-8'))
    names = [node.elts[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Tuple) and node.elts and
             isinstance(node.elts[0], ast.Constant) and
             type(node.elts[0].value) is str and
             node.elts[0].value in EXPECTED_TOOLS]
    require(len(names) == len(EXPECTED_TOOLS) and set(names) == EXPECTED_TOOLS,
            'LIFECYCLE_TOOL_INVENTORY_DENIED')
    return {
        'status': 'OFFLINE_SCHEMAFIX_LINEAGE_PASS',
        'base_sha256': BASE_SHA,
        'schemafix_sha256': SCHEMAFIX_SHA,
        'async_r2_sha256': ASYNC_R2_SHA,
        'schemafix_lifecycle_candidate_sha256': LIFECYCLE_SCHEMAFIX_SHA,
        'new_tool_names': sorted(EXPECTED_TOOLS),
        'installed_pi_hash_verified_now': False,
        'on_pi_tests_run': False,
        'activation_authorized': False,
        'mcp_modified': False,
        'production_modified': False,
        'tunnel_restarted': False,
    }
