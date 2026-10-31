"""M14F sandbox ownership attestation and non-mutating cleanup preflight.

Provenance is a signed *local helper* creation receipt, not merely an object
name, a Compose project, or untrusted Docker labels. This policy does not
issue Docker commands, create/remove objects, or authorize cleanup itself.

Existing M12 sandbox resources do NOT satisfy this new protocol and cannot
be retrospectively classified as safe to remove. Local trusted helper and
independent approval/replay ledger remain deployment prerequisites.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

DOMAIN = b"LINUX_MCP_SANDBOX_OWNERSHIP_V1"
HOST = "fieldwork-pi"
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_SECONDS = 3600
MAX_BLOB = 8192
LABELS = ("org.fieldwork.sandbox.run",
          "org.fieldwork.sandbox.proposal",
          "org.fieldwork.sandbox.role")


class SandboxDenied(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SandboxDenied(reason)


def canon(value: object) -> bytes:
    try:
        result = json.dumps(value, sort_keys=True,
                            separators=(",", ":"), ensure_ascii=True,
                            allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError) as exc:
        raise SandboxDenied("SANDBOX_JSON_DENIED") from exc
    require(len(result) <= MAX_BLOB, "SANDBOX_MANIFEST_TOO_LARGE")
    return result


def expected_resources(run_id: str, *, with_db: bool) -> list[dict]:
    require(type(run_id) is str and HEX32.fullmatch(run_id) is not None and
            type(with_db) is bool, "SANDBOX_ID_OR_MODE_DENIED")
    prefix = "fieldwork-sandbox-" + run_id
    rows = []
    if with_db:
        rows += [
            {"kind": "network", "role": "net", "name": prefix + "-net"},
            {"kind": "container", "role": "db", "name": prefix + "-db"},
        ]
    rows.append({"kind": "container", "role": "test",
                 "name": prefix + "-test"})
    return rows


def _validate_manifest(manifest: object, *, now: int) -> list[dict]:
    require(type(manifest) is dict and
            set(manifest) == {
                "protocol", "host_id", "run_id", "proposal_id",
                "with_db", "issued_at", "expires_at", "resources"
            }, "SANDBOX_MANIFEST_SCHEMA_DENIED")
    require(type(manifest["protocol"]) is int and
            manifest["protocol"] == 1 and
            manifest["host_id"] == HOST and
            type(manifest["proposal_id"]) is str and
            HEX32.fullmatch(manifest["proposal_id"]) is not None,
            "SANDBOX_MANIFEST_HOST_OR_PROPOSAL_DENIED")
    issued = manifest["issued_at"]
    expires = manifest["expires_at"]
    require(type(now) is int and type(issued) is int and
            type(expires) is int and
            0 <= issued <= now < expires <= issued + MAX_SECONDS and
            expires <= 4102444800,
            "SANDBOX_MANIFEST_TIME_DENIED")
    expected = expected_resources(
        manifest["run_id"], with_db=manifest["with_db"])
    resources = manifest["resources"]
    require(type(resources) is list and
            len(resources) == len(expected),
            "SANDBOX_MANIFEST_RESOURCES_DENIED")
    seen = set()
    normalized = []
    for template, row in zip(expected, resources):
        require(type(row) is dict and
                set(row) == {"kind", "role", "name", "id", "labels"} and
                all(row.get(k) == template[k] for k in ("kind", "role", "name")) and
                type(row["id"]) is str and
                HEX64.fullmatch(row["id"]) is not None and
                row["id"] not in seen,
                "SANDBOX_RESOURCE_IDENTITY_DENIED")
        seen.add(row["id"])
        labels = {
            LABELS[0]: manifest["run_id"],
            LABELS[1]: manifest["proposal_id"],
            LABELS[2]: row["role"],
        }
        require(type(row["labels"]) is dict and
                row["labels"] == labels,
                "SANDBOX_RESOURCE_LABELS_DENIED")
        normalized.append(row)
    return normalized


def sign_creation(manifest: dict, *, local_secret: bytes,
                  local_helper_created: bool, now: int) -> dict:
    """ONLY independently trusted local helper after actual Docker create.

    A remote MCP must never have access to this function's secret or helper
    process. The flag is supplied by trusted local executor, NOT a remote
    request parameter. This module alone is not proof of that OS boundary.
    """
    require(local_helper_created is True,
            "SANDBOX_LOCAL_CREATION_REQUIRED")
    require(type(local_secret) is bytes and len(local_secret) >= 32,
            "SANDBOX_SIGNING_SECRET_DENIED")
    _validate_manifest(manifest, now=now)
    digest = hmac.new(local_secret, DOMAIN + b"\0" + canon(manifest),
                      hashlib.sha256).hexdigest()
    return {"manifest": manifest, "mac": digest}


def cleanup_preflight(attestation: object, *, observations: object,
                      local_secret: bytes, now: int) -> dict:
    """Check exact live IDs/ownership; returns NO deletion authorization."""
    require(type(attestation) is dict and
            set(attestation) == {"manifest", "mac"},
            "SANDBOX_ATTESTATION_SCHEMA_DENIED")
    require(type(local_secret) is bytes and len(local_secret) >= 32 and
            type(attestation["mac"]) is str and
            HEX64.fullmatch(attestation["mac"]) is not None,
            "SANDBOX_ATTESTATION_MAC_SCHEMA_DENIED")
    manifest = attestation["manifest"]
    rows = _validate_manifest(manifest, now=now)
    expected_mac = hmac.new(
        local_secret, DOMAIN + b"\0" + canon(manifest),
        hashlib.sha256,
    ).hexdigest()
    require(hmac.compare_digest(attestation["mac"], expected_mac),
            "SANDBOX_ATTESTATION_MAC_DENIED")
    require(type(observations) is list and len(observations) == len(rows),
            "SANDBOX_OBSERVATION_COUNT_DENIED")
    for index, row in enumerate(rows):
        observed = observations[index]
        require(type(observed) is dict and
                set(observed) == {"kind", "role", "name", "id",
                                  "labels", "state", "network_container_ids"},
                "SANDBOX_OBSERVATION_SCHEMA_DENIED")
        require(all(observed[k] == row[k]
                    for k in ("kind", "role", "name", "id", "labels")),
                "SANDBOX_OBSERVED_OWNER_MISMATCH")
        allowed_states = (
            {"created", "running", "exited"} if row["kind"] == "container"
            else {"existing"}
        )
        require(type(observed["state"]) is str and
                observed["state"] in allowed_states,
                "SANDBOX_OBSERVED_STATE_DENIED")
        attached = observed["network_container_ids"]
        require(type(attached) is list and
                all(type(cid) is str and HEX64.fullmatch(cid)
                    for cid in attached) and
                len(attached) == len(set(attached)),
                "SANDBOX_NETWORK_ENDPOINT_SCHEMA_DENIED")
        if row["kind"] == "network":
            owned_containers = {
                x["id"] for x in rows if x["kind"] == "container"
            }
            require(set(attached) <= owned_containers,
                    "SANDBOX_FOREIGN_NETWORK_ENDPOINT_DENIED")
        else:
            require(not attached,
                    "SANDBOX_UNEXPECTED_CONTAINER_ENDPOINTS")
    return {
        "status": "SANDBOX_OWNER_PROVENANCE_PREFLIGHT_PASS",
        "host_id": manifest["host_id"],
        "run_id": manifest["run_id"],
        "proposal_id": manifest["proposal_id"],
        "resource_count": len(rows),
        "creation_receipt_verified": True,
        "exact_live_ownership_claims_match": True,
        "docker_command_executed": False,
        "cleanup_authorized": False,
        "container_removal_authorized": False,
        "historical_cleanup_receipt_resolved": False,
        "production_modified": False,
    }
