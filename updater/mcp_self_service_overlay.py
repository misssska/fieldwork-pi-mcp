"""M12 deterministic, fail-closed transformations for one local MCP upgrade.

Pure bytes-in/bytes-out. Real Pi installed sources are pinned by SHA256.
No host filesystem, subprocess, systemd, network, or Docker operations.
"""
from __future__ import annotations

import ast
import hashlib

if __package__:
    from . import sandbox_cleanup_overlay
else:
    import sandbox_cleanup_overlay

EXPECTED_MCP_SHA256 = "e0e7cfb7b70c7f79845337b84bb47025beaad6d429377b64d1972db68c3fbc1a"
EXPECTED_SANDBOX_SHA256 = sandbox_cleanup_overlay.PINNED_ACTIVE_SANDBOX_SHA256
MAX_BYTES = 1_000_000

IMPORT_OLD = "import artifact_retention_adapter\n"
IMPORT_NEW = IMPORT_OLD + "import mcp_self_diagnostics\n"

TOOLS_OLD = '''    ("fieldwork_artifact_retire", "Explicitly release one SHA256-verified inert upload, preserving replay tombstone; never execute", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "approval": {"type": "string", "enum": ["RETIRE_VERIFIED_CANARY"]}
    }, artifact_retention_adapter.retire),
'''

TOOLS_NEW = TOOLS_OLD + '''    ("fieldwork_mcp_source_inventory", "List allowlisted installed MCP module SHA256 and public function names only", {
    }, mcp_self_diagnostics.source_inventory),
    ("fieldwork_mcp_source_review", "Read SHA-pinned installed MCP function AST with sensitive literals redacted", {
        "module": {"type": "string", "enum": ["sandbox_command.py", "runtime_runner.py", "fieldwork_mcp.py", "stage_manager.py", "stage_async.py", "stage_inspect.py", "stage_start_async.py"]},
        "function": {"type": "string", "pattern": "^[a-zA-Z_][a-zA-Z0-9_]{0,79}$"}
    }, mcp_self_diagnostics.source_review),
    ("fieldwork_mcp_docker_inventory", "Read bounded sanitized Docker host container state, never stop or remove", {
    }, mcp_self_diagnostics.docker_inventory),
'''

ANNOTATION_OLD = (
    '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start", '
    '"fieldwork_artifact_begin", "fieldwork_artifact_append", "fieldwork_artifact_status", '
    '"fieldwork_artifact_finalize", "fieldwork_artifact_qualify", "fieldwork_artifact_retire"'
)
ANNOTATION_NEW = ANNOTATION_OLD + (
    ', "fieldwork_mcp_source_inventory", "fieldwork_mcp_source_review", '
    '"fieldwork_mcp_docker_inventory"'
)

NAMES = frozenset({
    "fieldwork_mcp_source_inventory",
    "fieldwork_mcp_source_review",
    "fieldwork_mcp_docker_inventory",
})


class SelfServiceOverlayDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise SelfServiceOverlayDenied(code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ast_valid(data: bytes) -> None:
    try:
        ast.parse(data, filename="<candidate>")
    except (ValueError, SyntaxError, UnicodeError) as exc:
        raise SelfServiceOverlayDenied("CANDIDATE_SYNTAX_DENIED") from exc


def transform_mcp(source: bytes) -> bytes:
    require(type(source) is bytes and 0 < len(source) <= MAX_BYTES,
            "MCP_SOURCE_BOUNDS_DENIED")
    require(sha(source) == EXPECTED_MCP_SHA256, "MCP_SHA256_DRIFT")
    _ast_valid(source)
    try:
        text = source.decode("utf-8")
    except UnicodeError as exc:
        raise SelfServiceOverlayDenied("MCP_UTF8_INVALID") from exc
    for old, new in (
        (IMPORT_OLD, IMPORT_NEW),
        (TOOLS_OLD, TOOLS_NEW),
        (ANNOTATION_OLD, ANNOTATION_NEW),
    ):
        require(text.count(old) == 1, "MCP_ANCHOR_NOT_UNIQUE_OR_DRIFTED")
        text = text.replace(old, new, 1)
    result = text.encode("utf-8")
    _ast_valid(result)
    tree = ast.parse(result)
    names = [n.value for n in ast.walk(tree) if
             isinstance(n, ast.Constant) and
             type(n.value) is str and n.value in NAMES]
    # Active v0.6.1 contains both a tool registration and a separate
    # source-level allowlist of tool names. Each added name is therefore
    # present twice as an AST Constant. Synthetic wrappers with a combined
    # string literal for the allowlist have one AST occurrence instead.
    # Both shapes preserve exact source anchors and exactly three new
    # registrations; unexpected third appearances always fail closed.
    counts = {name: names.count(name) for name in NAMES}
    require(set(names) == NAMES and
            len(set(counts.values())) == 1 and
            next(iter(counts.values())) in (1, 2),
            "MCP_TOOL_REGISTER_AUDIT_COUNT_DENIED")
    return result


def build_mcp_and_cleanup(mcp_source: bytes, sandbox_source: bytes) -> dict:
    mcp = transform_mcp(mcp_source)
    require(type(sandbox_source) is bytes and
            sha(sandbox_source) == EXPECTED_SANDBOX_SHA256,
            "SANDBOX_SHA256_DRIFT")
    cleanup = sandbox_cleanup_overlay.build(sandbox_source)
    require(cleanup["activation_authorized"] is False and
            cleanup["mcp_modified"] is False,
            "CLEANUP_OVERLAY_UNEXPECTED_AUTHORIZATION")
    _ast_valid(cleanup["candidate_source"])
    return {
        "status": "M12_OFFLINE_CANDIDATE_ONLY",
        "old_mcp_sha256": sha(mcp_source),
        "new_mcp_sha256": sha(mcp),
        "old_sandbox_sha256": sha(sandbox_source),
        "new_sandbox_sha256": sha(cleanup["candidate_source"]),
        "mcp_bytes": mcp,
        "sandbox_bytes": cleanup["candidate_source"],
        "mcp_modified": False,
        "production_modified": False,
        "activation_authorized": False,
    }
