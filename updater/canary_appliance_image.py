"""Pure, fail-closed validation of a locally built canary test appliance.

Call with bytes obtained from the exact local 'docker image inspect' operation.
This module NEVER invokes Docker, creates files or grants execution permission.
A verified image ID and matching source dependencies are still only
an operator preflight, not local approval or an MCP activation.
"""
from __future__ import annotations

import json
import re

from . import canary_archive_qualifier as q
from . import canary_test_runner as runner

RAW_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
LABELS = {
    "profile": "org.fieldwork.appliance.profile",
    "frontend_lock_sha256": "org.fieldwork.appliance.frontend-lock-sha256",
    "backend_requirements_sha256":
        "org.fieldwork.appliance.backend-requirements-sha256",
    "backend_dev_requirements_sha256":
        "org.fieldwork.appliance.backend-dev-requirements-sha256",
    "production_access": "org.fieldwork.appliance.production-access",
    "scope": "org.fieldwork.appliance.scope",
}
MAX_INSPECT = 256 * 1024
ARCHES = frozenset({"arm64", "amd64"})


def qualify(inspect_bytes: bytes, *, expected_image_id: str,
            dependency_sha256: dict[str, str],
            architecture: str = "arm64") -> dict:
    """Validate a Docker image ID, architecture and pinned build labels.

    Only an exact image ID is accepted: a local build has no RepoDigest
    until uploaded to a registry. Do not invent a registry digest.
    """
    q.require(type(expected_image_id) is str and
              RAW_IMAGE.fullmatch(expected_image_id) is not None,
              "APPLIANCE_RAW_IMAGE_ID_REQUIRED")
    q.require(type(architecture) is str and architecture in ARCHES,
              "APPLIANCE_ARCHITECTURE_NOT_ALLOWED")
    q.require(type(inspect_bytes) is bytes and
              0 < len(inspect_bytes) <= MAX_INSPECT,
              "APPLIANCE_INSPECT_SIZE_DENIED")
    q.require(type(dependency_sha256) is dict and
              set(dependency_sha256) == set(runner.DEPENDENCY_FILES),
              "APPLIANCE_DEPENDENCY_SCHEMA_DENIED")
    for digest in dependency_sha256.values():
        q.require(type(digest) is str and
                  q.HEX64.fullmatch(digest) is not None,
                  "APPLIANCE_DEPENDENCY_DIGEST_INVALID")
    try:
        payload = json.loads(inspect_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise q.QualificationDenied("APPLIANCE_INSPECT_INVALID") from exc
    q.require(type(payload) is list and len(payload) == 1 and
              type(payload[0]) is dict, "APPLIANCE_INSPECT_SCHEMA_DENIED")
    record = payload[0]
    q.require(record.get("Id") == expected_image_id,
              "APPLIANCE_IMAGE_ID_DRIFT")
    q.require(record.get("Architecture") == architecture and
              record.get("Os") == "linux",
              "APPLIANCE_PLATFORM_MISMATCH")
    config = record.get("Config")
    q.require(type(config) is dict and
              type(config.get("Labels")) is dict,
              "APPLIANCE_LABELS_MISSING")
    labels = config["Labels"]
    q.require(labels.get(LABELS["profile"]) == runner.PROFILE and
              labels.get(LABELS["production_access"]) == "denied" and
              labels.get(LABELS["scope"]) == "isolated-test-only",
              "APPLIANCE_BUILD_PROFILE_DENIED")
    for name in runner.DEPENDENCY_FILES:
        q.require(labels.get(LABELS[name]) == dependency_sha256[name],
                  "APPLIANCE_SOURCE_DEPENDENCY_DRIFT")
    return {
        "status": "APPLIANCE_IMAGE_PREFLIGHT_PASS_NOT_APPROVED",
        "image_id": expected_image_id,
        "platform": "linux/" + architecture,
        "profile": runner.PROFILE,
        "source_dependencies_match": True,
        "five_suites_executed": False,
        "local_approval_granted": False,
        "mcp_activation_authorized": False,
        "canary_start_authorized": False,
        "production_modified": False,
    }
