"""M13 read-only MCP tool insertion, exclusively onto the observed M12 SHA.

No installed code executes here: pin -> exact bytes anchors -> Python AST ->
verify exactly 2 direct named registrations -> candidate bytes, no writes.
Existing M12 diagnostics, sandbox cleanup, stage and production unchanged.
"""
from __future__ import annotations
import ast
import hashlib

EXPECTED_MAIN_SHA256 = "ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532"
MAX_SOURCE_BYTES = 1_000_000

OLD_IMPORT = "import mcp_self_diagnostics\n"
NEW_IMPORT = OLD_IMPORT + "import mcp_linux_telemetry\n"

OLD_TOOL = '''    ("fieldwork_mcp_docker_inventory", "Read bounded sanitized Docker host container state, never stop or remove", {
    }, mcp_self_diagnostics.docker_inventory),
'''

NEW_TOOLS = OLD_TOOL + '''    ("fieldwork_mcp_host_metrics", "Read Linux host /proc memory, swap, CPU interval and load without writes", {
    }, mcp_linux_telemetry.host_metrics),
    ("fieldwork_mcp_container_stats", "Read bounded CPU and memory metrics for running Docker containers without writes", {
    }, mcp_linux_telemetry.docker_stats),
'''

ADDED = {
    "fieldwork_mcp_host_metrics": "host_metrics",
    "fieldwork_mcp_container_stats": "docker_stats",
}


class M13OverlayDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise M13OverlayDenied(code)


def build(source: bytes) -> dict:
    require(type(source) is bytes and
            0 < len(source) <= MAX_SOURCE_BYTES, "M13_SOURCE_BOUNDS_DENIED")
    old_sha = hashlib.sha256(source).hexdigest()
    require(old_sha == EXPECTED_MAIN_SHA256,
            "M13_INSTALLED_M12_SHA256_MISMATCH")
    try:
        original = source.decode("utf-8")
        ast.parse(original)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        raise M13OverlayDenied("M13_SOURCE_SYNTAX_INVALID") from exc

    require(original.count(OLD_IMPORT) == 1 and
            original.count(OLD_TOOL) == 1,
            "M13_SOURCE_ANCHOR_DRIFT")
    require("import mcp_linux_telemetry" not in original and
            all(name not in original for name in ADDED),
            "M13_TOOLS_ALREADY_PRESENT")
    changed = original.replace(OLD_IMPORT, NEW_IMPORT, 1)
    changed = changed.replace(OLD_TOOL, NEW_TOOLS, 1)
    try:
        tree = ast.parse(changed)
        compile(tree, "fieldwork_mcp_m13_candidate.py", "exec")
    except (SyntaxError, ValueError, UnicodeError) as exc:
        raise M13OverlayDenied("M13_CANDIDATE_SYNTAX_INVALID") from exc

    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or len(node.elts) != 4:
            continue
        name, _, _, handler = node.elts
        if not isinstance(name, ast.Constant) or name.value not in ADDED:
            continue
        require(name.value not in found and
                isinstance(handler, ast.Attribute) and
                isinstance(handler.value, ast.Name) and
                handler.value.id == "mcp_linux_telemetry" and
                handler.attr == ADDED[name.value],
                "M13_HANDLER_REGISTRATION_UNEXPECTED")
        found[name.value] = handler.attr
    require(found == ADDED, "M13_HANDLER_REGISTRATION_INCOMPLETE")

    # This must not alter the existing tools' mutating-tool safety list.
    # The M13 new endpoints are deliberately read-only (not added to list
    # of mutating tools in rpc() readOnlyHint).
    require(changed.count(OLD_TOOL) == 1 and
            changed.count(OLD_IMPORT) == 1,
            "M13_OLD_TOOLS_CHANGED")
    return {
        "status": "M13_OFFLINE_CANDIDATE_ONLY",
        "old_sha256": old_sha,
        "new_sha256": hashlib.sha256(changed.encode("utf-8")).hexdigest(),
        "candidate_bytes": changed.encode("utf-8"),
        "new_tools": sorted(ADDED),
        "activation_authorized": False,
        "mcp_modified": False,
        "production_modified": False,
    }
