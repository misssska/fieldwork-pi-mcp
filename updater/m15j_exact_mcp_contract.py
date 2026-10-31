"""M15-J1 exact 36-tool migration inventory and fail-closed cutover gate.

Static policy anchored to the ACTUAL installed FieldWork Pi MCP v0.6.1
tool catalog and source hashes. This module cannot run Docker, modify the Pi,
mint a key, create a service, or grant approvals. The replacement must
implement every required route, and independently re-attest that the remote
MCP UID has no direct host-root-equivalent privileges before cutover.

Do not interpret a passing inventory as privilege separation: this is a
compatibility contract, not a permission to activate M15-E.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# Exact tool catalog obtained from the connected live Pi MCP.
EXPECTED = (
    "fieldwork_status",
    "fieldwork_tree",
    "fieldwork_read_file",
    "fieldwork_git_status",
    "fieldwork_git_diff",
    "fieldwork_python_syntax",
    "fieldwork_compose_ps",
    "fieldwork_compose_logs",
    "fieldwork_api_health",
    "fieldwork_stage_patch",
    "fieldwork_sandbox_apply",
    "fieldwork_sandbox_read_file",
    "fieldwork_proposal_status",
    "fieldwork_sandbox_runtime_test",
    "fieldwork_sandbox_runtime_status",
    "fieldwork_sandbox_command",
    "fieldwork_sandbox_command_status",
    "fieldwork_stage_capabilities",
    "fieldwork_stage_prepare",
    "fieldwork_stage_full_test",
    "fieldwork_artifact_begin",
    "fieldwork_artifact_append",
    "fieldwork_artifact_status",
    "fieldwork_artifact_finalize",
    "fieldwork_artifact_qualify",
    "fieldwork_artifact_retire",
    "fieldwork_mcp_source_inventory",
    "fieldwork_mcp_source_review",
    "fieldwork_mcp_docker_inventory",
    "fieldwork_stage_start",
    "fieldwork_stage_status",
    "fieldwork_stage_smoke",
    "fieldwork_stage_stop",
    "fieldwork_stage_credentials",
    "fieldwork_stage_release_status",
    "fieldwork_stage_logs",
)

# No guessed permission from tool name: individually reviewed classes.
# Docker read operations must be through the future bounded RO proxy.
DOCKER_READ = frozenset({
    "fieldwork_compose_ps", "fieldwork_compose_logs",
    "fieldwork_mcp_docker_inventory", "fieldwork_stage_status",
    "fieldwork_stage_logs",
})
# Requires a future complete fixed-project Compose helper (build/up/test/down).
# M14-E existing-container start/stop alone is NOT sufficient.
STAGE_WRITE = frozenset({
    "fieldwork_stage_full_test", "fieldwork_stage_start",
    "fieldwork_stage_stop",
})
# Requires a future full sandbox helper (network, run, optional DB, cleanup).
SANDBOX_WRITE = frozenset({
    "fieldwork_sandbox_runtime_test", "fieldwork_sandbox_command",
})
# Local state/data functions; these MUST NOT gain Docker authority by accident.
NO_DOCKER = frozenset(EXPECTED) - DOCKER_READ - STAGE_WRITE - SANDBOX_WRITE

SOURCE_PIN = {
    "fieldwork_mcp.py": "ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532",
    "stage_manager.py": "0a04c40a00ccc940e50d590cf6b01f75c7a803dd228cb24b916fad44e046a7e6",
    "runtime_runner.py": "ae0387aed34768a7260cf01e6c1ff9d4620c506c37e7ae2a74706f661ee2db6c",
    "sandbox_command.py": "5a4a6ba775f7fd16d0660a654eb3ab8724659ff1ac72fd1427ed3c9eadb797f5",
}
REQUIRED_ROUTES = ("no_docker", "docker_read_proxy",
                   "stage_compose_helper", "sandbox_helper")
HEX = frozenset("0123456789abcdef")


class CompatibilityDenied(ValueError):
    pass


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise CompatibilityDenied(msg)


def route(tool: str) -> str:
    require(type(tool) is str and tool in EXPECTED,
            "M15J_UNKNOWN_OR_UNREVIEWED_MCP_TOOL")
    if tool in DOCKER_READ:
        return "docker_read_proxy"
    if tool in STAGE_WRITE:
        return "stage_compose_helper"
    if tool in SANDBOX_WRITE:
        return "sandbox_helper"
    return "no_docker"


def tool_manifest() -> dict:
    require(len(EXPECTED) == 36 and len(set(EXPECTED)) == 36 and
            len(DOCKER_READ | STAGE_WRITE | SANDBOX_WRITE | NO_DOCKER) == 36 and
            not (DOCKER_READ & STAGE_WRITE | DOCKER_READ & SANDBOX_WRITE |
                 STAGE_WRITE & SANDBOX_WRITE |
                 NO_DOCKER & (DOCKER_READ | STAGE_WRITE | SANDBOX_WRITE)),
            "M15J_UNSAFE_INTERNAL_POLICY")
    counts = {r: sum(route(n) == r for n in EXPECTED)
              for r in REQUIRED_ROUTES}
    return {
        "schema": "m15j-exact-v1",
        "mcp_version": "0.6.1",
        "source_pins": dict(SOURCE_PIN),
        "count": len(EXPECTED),
        "counts": counts,
        "tools": [{"name": name, "route": route(name)} for name in EXPECTED],
        "new_docker_helper_in_production": False,
        "legacy_mcp_docker_restrictions_changed": False,
        "cutover_authorized": False,
    }


def verify_live_inventory(names: object, observed_hashes: object) -> dict:
    """Only confirms exact tool names and source hashes, no runtime approval."""
    require(type(names) is list and all(type(x) is str for x in names) and
            len(names) == len(EXPECTED) and
            len(set(names)) == len(EXPECTED) and
            set(names) == set(EXPECTED),
            "M15J_LIVE_TOOL_CATALOG_DRIFT")
    require(type(observed_hashes) is dict and
            set(observed_hashes) == set(SOURCE_PIN) and
            all(type(v) is str and len(v) == 64 and set(v) <= HEX
                for v in observed_hashes.values()) and
            observed_hashes == SOURCE_PIN,
            "M15J_LIVE_SOURCE_BYTES_CHANGED")
    result = tool_manifest()
    return {"status": "M15J_EXACT_LEGACY_INVENTORY_PASS",
            "tool_count": result["count"], "routes": result["counts"],
            "legacy_compatibility_implemented": False,
            "privilege_separation_verified": False,
            "cutover_authorized": False}


def evaluate_shadow_cutover(
    *, live_names: object, live_hashes: object,
    route_receipts: object, remote_mcp_without_rootful_docker: object,
    independent_host_audit: object, operator_authentication: object,
) -> dict:
    """A hard release gate; never mutates or delegates privilege.

    Exactly one independently produced full 36-tool receipt per tool is
    necessary, with approved outcome & same route; callers cannot provide
    an open-ended/missing/duplicate receipt set. Additional checks are
    explicit but these booleans alone are NOT cryptographic evidence.
    This function never emits activation_authorized=true.
    """
    base = verify_live_inventory(live_names, live_hashes)
    require(type(route_receipts) is list and
            len(route_receipts) == len(EXPECTED),
            "M15J_SHADOW_RECEIPT_COUNT_DENIED")
    seen = set()
    for rec in route_receipts:
        require(type(rec) is dict and
                set(rec) == {"tool", "route", "outcome", "evidence_sha256"} and
                type(rec["tool"]) is str and rec["tool"] in EXPECTED and
                rec["tool"] not in seen and
                type(rec["route"]) is str and rec["route"] == route(rec["tool"]) and
                rec["outcome"] == "PASS" and
                type(rec["evidence_sha256"]) is str and
                len(rec["evidence_sha256"]) == 64 and
                set(rec["evidence_sha256"]) <= HEX,
                "M15J_INVALID_SHADOW_RECEIPT")
        seen.add(rec["tool"])
    require(seen == set(EXPECTED), "M15J_SHADOW_COVERAGE_INCOMPLETE")
    require(remote_mcp_without_rootful_docker is True and
            independent_host_audit is True and
            operator_authentication is True,
            "M15J_PRIVILEGE_AND_CONSENT_NOT_ATTESTED")
    return {
        "status": "M15J_SHADOW_CONTRACT_EVIDENCE_REVIEW_REQUIRED",
        "source_and_tool_catalog_match": True,
        "shadow_receipts_present": len(seen),
        "actual_host_privilege_verified_by_this_module": False,
        "operator_consent_verified_by_this_module": False,
        "cutover_authorized": False,
        "docker_group_revoke_authorized": False,
        "m15e_activation_authorized": False,
    }


if __name__ == "__main__":
    import sys
    require(sys.argv == [sys.argv[0]], "M15J_CLI_PARAMETERS_DENIED")
    print(json.dumps(tool_manifest(), sort_keys=True))
