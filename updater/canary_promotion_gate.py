"""Fail-closed preflight for switching a fixed-origin DEV gateway.

Policy only. MUST be called with *locally measured* probe data by a separately
authorized on-Pi deployment adapter. Untrusted remote JSON is not evidence.
No Docker, networking, file writes, service reload or automatic rollback.
"""
from __future__ import annotations

from . import stable_dev_gateway as gateway

EXPECTED_PROBE_KEYS = frozenset({
    "project", "host", "port", "health_http_status", "health_json_status",
    "api_smoke", "authorization_smoke", "migration_gate", "tests_verified",
    "gateway_port_exclusive", "previous_route_backed_up", "network_scope",
})

class PromotionDenied(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise PromotionDenied(reason)


def review(candidate: dict, current: dict, observed: dict) -> dict:
    """Reject regressions and origin/session mismatches before any route switch."""
    try:
        plan = gateway.plan_switch(candidate, current)
    except (gateway.GatewayDenied, ValueError, TypeError) as exc:
        raise PromotionDenied("RELEASE_RECEIPT_DENIED") from exc
    _require(plan["same_auth_identity"], "JWT_IDENTITY_DRIFT")
    _require(plan["same_database_identity"], "DATABASE_IDENTITY_DRIFT")
    _require(type(observed) is dict and set(observed) == EXPECTED_PROBE_KEYS,
             "OBSERVATION_SCHEMA_INVALID")
    _require(observed["project"] == plan["target_project"],
             "PROBE_PROJECT_MISMATCH")
    _require(observed["host"] == gateway.GATEWAY_HOST and
             type(observed["port"]) is int and
             observed["port"] == plan["target_port"], "PROBE_TARGET_MISMATCH")
    _require(type(observed["health_http_status"]) is int and
             observed["health_http_status"] == 200 and
             observed["health_json_status"] == "ok", "HEALTH_NOT_VERIFIED")
    for key in ("api_smoke", "authorization_smoke", "migration_gate",
                "tests_verified", "gateway_port_exclusive",
                "previous_route_backed_up"):
        _require(observed[key] is True, "GATE_NOT_PASSED:" + key)
    _require(observed["network_scope"] == "LAN_ONLY", "PUBLIC_GATEWAY_DENIED")
    # A PASS is a review gate, *not* deployment authorization.
    return {
        "status": "PRE_PROMOTION_REVIEW_PASS_NOT_APPLIED",
        "stable_origin": plan["stable_origin"],
        "target_project": plan["target_project"],
        "target_port": plan["target_port"],
        "nginx_config_sha256": plan["nginx_config_sha256"],
        "authentication_continuity_proven": False,
        "promotion_authorized": False,
        "route_modified": False,
        "production_modified": False,
    }
