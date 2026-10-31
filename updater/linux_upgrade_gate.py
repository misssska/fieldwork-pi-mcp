"""M14 Linux MCP update intent, admission and local authorization protocol.

PURE IN-MEMORY POLICY. No network, shell, filesystem writes or deployment.
A remote MCP caller may propose a hash-pinned candidate; only a *separate*
local approver holding a secret unavailable to the MCP process may authorize
that exact proposal. This module cannot supply operator presence or
privilege isolation by itself; OS separation remains an installation gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets

HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
HOST_ID = re.compile(r"[a-z][a-z0-9-]{2,47}\Z")
MODULE = re.compile(r"[a-z][a-z0-9_]{0,63}\.py\Z")
MAX_FILES = 12
MAX_PROPOSAL_AGE = 3600
MAX_FUTURE_SKEW = 30
MAX_APPROVAL_AGE = 180
DOMAIN = "LINUX_MCP_UPDATE_V1"
BIND = DOMAIN.encode("ascii")
REQUIRED = frozenset({
    "protocol", "host_id", "commit_sha", "issued_at", "expires_at", "files",
})
FILE_KEYS = frozenset({"name", "old_sha256", "new_sha256", "action"})
AUTH_KEYS = frozenset({
    "protocol", "host_id", "plan_sha256", "expires_at", "nonce", "mac",
})


class UpgradeDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise UpgradeDenied(code)


def canon(obj: object) -> bytes:
    try:
        result = json.dumps(
            obj, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
            allow_nan=False,
        ).encode("ascii")
    except (ValueError, TypeError, OverflowError) as exc:
        raise UpgradeDenied("UPGRADE_JSON_INVALID") from exc
    require(len(result) <= 16384, "UPGRADE_REQUEST_TOO_LARGE")
    return result


@dataclass(frozen=True)
class HostPolicy:
    """Construct exclusively from locally-owned, trusted configuration."""
    host_id: str
    allowed_modules: frozenset[str]
    locked_modules: frozenset[str] = frozenset()
    max_age_seconds: int = MAX_PROPOSAL_AGE

    def __post_init__(self) -> None:
        require(type(self.host_id) is str and
                HOST_ID.fullmatch(self.host_id) is not None,
                "POLICY_HOST_INVALID")
        require(type(self.allowed_modules) is frozenset and
                0 < len(self.allowed_modules) <= 30 and
                all(type(x) is str and MODULE.fullmatch(x)
                    for x in self.allowed_modules),
                "POLICY_MODULES_INVALID")
        require(type(self.locked_modules) is frozenset and
                self.locked_modules <= self.allowed_modules,
                "POLICY_LOCK_INVALID")
        require(type(self.max_age_seconds) is int and
                1 <= self.max_age_seconds <= MAX_PROPOSAL_AGE,
                "POLICY_AGE_INVALID")


@dataclass(frozen=True)
class ValidatedPlan:
    host_id: str
    commit_sha: str
    plan_sha256: str
    issued_at: int
    expires_at: int
    files: tuple[dict, ...]
    scope: str = "private_mcp_owned_files_only"


def _integer(value: object) -> bool:
    return type(value) is int and 0 <= value <= 4102444800


def validate_plan(request: object, policy: HostPolicy,
                  active_hashes: dict[str, str | None], now: int) -> ValidatedPlan:
    require(type(now) is int and 0 <= now <= 4102444800,
            "CLOCK_INVALID")
    require(type(request) is dict and
            frozenset(request) == REQUIRED, "PLAN_FIELDS_DENIED")
    require(request["protocol"] == 1 and
            type(request["protocol"]) is int, "PLAN_PROTOCOL_DENIED")
    require(type(request["host_id"]) is str and
            request["host_id"] == policy.host_id,
            "PLAN_HOST_MISMATCH")
    require(type(request["commit_sha"]) is str and
            HEX40.fullmatch(request["commit_sha"]) is not None,
            "PLAN_IMMUTABLE_COMMIT_REQUIRED")
    issued, expires = request["issued_at"], request["expires_at"]
    require(_integer(issued) and _integer(expires) and
            issued <= now + MAX_FUTURE_SKEW and issued <= now and
            now < expires <= issued + policy.max_age_seconds,
            "PLAN_EXPIRED_OR_CLOCK_INVALID")
    files = request["files"]
    require(type(files) is list and 1 <= len(files) <= MAX_FILES,
            "PLAN_FILE_COUNT_DENIED")
    require(type(active_hashes) is dict and
            all(type(x) is str and
                (v is None or (type(v) is str and HEX64.fullmatch(v)))
                for x, v in active_hashes.items()),
            "ACTIVE_HASHES_INVALID")
    normalized = []
    seen = set()
    for part in files:
        require(type(part) is dict and
                frozenset(part) == FILE_KEYS, "PLAN_FILE_SCHEMA_DENIED")
        name = part["name"]
        require(type(name) is str and
                MODULE.fullmatch(name) is not None and
                name in policy.allowed_modules and
                name not in policy.locked_modules and
                name not in seen, "PLAN_FILE_NOT_ALLOWED")
        seen.add(name)
        old, new, action = (
            part["old_sha256"], part["new_sha256"], part["action"]
        )
        require(type(new) is str and HEX64.fullmatch(new) is not None,
                "PLAN_NEW_SHA256_INVALID")
        require(action in {"replace", "create"} and
                type(action) is str, "PLAN_FILE_ACTION_DENIED")
        if action == "replace":
            require(type(old) is str and HEX64.fullmatch(old) is not None and
                    active_hashes.get(name) == old and old != new,
                    "PLAN_ACTIVE_SOURCE_MISMATCH")
        else:
            require(old is None and name in active_hashes and
                    active_hashes[name] is None, "PLAN_CREATE_NOT_EMPTY")
        normalized.append({
            "name": name, "action": action,
            "old_sha256": old, "new_sha256": new,
        })
    require([x["name"] for x in normalized] ==
            sorted(x["name"] for x in normalized),
            "PLAN_FILES_NOT_CANONICALLY_ORDERED")
    digest = hashlib.sha256(BIND + b"\0" + canon(request)).hexdigest()
    return ValidatedPlan(
        host_id=policy.host_id,
        commit_sha=request["commit_sha"],
        plan_sha256=digest,
        issued_at=issued,
        expires_at=expires,
        files=tuple(normalized),
    )


def approval_display(plan: ValidatedPlan) -> dict:
    """Display only an exact fingerprint, no raw source or secrets."""
    return {
        "status": "LOCAL_REVIEW_REQUIRED",
        "host_id": plan.host_id,
        "commit_sha": plan.commit_sha,
        "plan_sha256": plan.plan_sha256,
        "expires_at": plan.expires_at,
        "target_modules": [x["name"] for x in plan.files],
        "approval_hint": "Local trusted operator must review exact diff; "
                         "remote MCP cannot approve",
        "activation_authorized": False,
    }


def _message(auth_fields: dict) -> bytes:
    return BIND + b"\0APPROVAL\0" + canon(auth_fields)


def issue_local_approval(plan: ValidatedPlan, *, local_secret: bytes,
                         operator_present: bool, now: int) -> dict:
    """Local approver ONLY. Never register this function as an MCP tool.

    Requires an OS-isolated 32-byte local secret inaccessible to remote MCP.
    The operator_present flag is supplied by the local trusted UI, not MCP.
    This in-memory primitive alone DOES NOT verify physical operator presence.
    """
    require(operator_present is True, "LOCAL_APPROVAL_NOT_GIVEN")
    require(type(local_secret) is bytes and len(local_secret) >= 32,
            "LOCAL_APPROVAL_KEY_INVALID")
    require(type(now) is int and plan.issued_at <= now < plan.expires_at,
            "LOCAL_APPROVAL_EXPIRED")
    claim = {
        "protocol": 1,
        "host_id": plan.host_id,
        "plan_sha256": plan.plan_sha256,
        "expires_at": min(now + MAX_APPROVAL_AGE, plan.expires_at),
        "nonce": secrets.token_hex(16),
    }
    claim["mac"] = hmac.new(local_secret, _message(claim),
                            hashlib.sha256).hexdigest()
    return claim


def verify_local_approval(plan: ValidatedPlan, approval: object,
                          *, local_secret: bytes, now: int,
                          spent_nonces: frozenset[str]) -> str:
    """Cryptographic verification only. Durable replay store is separate."""
    require(type(approval) is dict and
            frozenset(approval) == AUTH_KEYS, "APPROVAL_SCHEMA_DENIED")
    require(type(local_secret) is bytes and len(local_secret) >= 32,
            "APPROVAL_KEY_INVALID")
    require(type(now) is int and 0 <= now <= 4102444800,
            "APPROVAL_CLOCK_INVALID")
    require(type(spent_nonces) is frozenset and
            all(type(x) is str for x in spent_nonces),
            "APPROVAL_NONCE_STORE_INVALID")
    require(type(approval["protocol"]) is int and
            approval["protocol"] == 1 and
            type(approval["host_id"]) is str and
            approval["host_id"] == plan.host_id and
            type(approval["plan_sha256"]) is str and
            approval["plan_sha256"] == plan.plan_sha256,
            "APPROVAL_PLAN_MISMATCH")
    nonce, mac, expiry = (
        approval["nonce"], approval["mac"], approval["expires_at"]
    )
    require(type(nonce) is str and
            re.fullmatch(r"[0-9a-f]{32}\Z", nonce) is not None and
            type(mac) is str and HEX64.fullmatch(mac) is not None,
            "APPROVAL_NONCE_OR_MAC_INVALID")
    require(_integer(expiry) and
            now < expiry <= plan.expires_at and
            expiry <= now + MAX_APPROVAL_AGE,
            "APPROVAL_EXPIRED_OR_CLOCK_INVALID")
    require(nonce not in spent_nonces, "APPROVAL_REPLAY_DENIED")
    claim = {k: v for k, v in approval.items() if k != "mac"}
    expected = hmac.new(local_secret, _message(claim),
                        hashlib.sha256).hexdigest()
    require(hmac.compare_digest(mac, expected), "APPROVAL_MAC_DENIED")
    return nonce
