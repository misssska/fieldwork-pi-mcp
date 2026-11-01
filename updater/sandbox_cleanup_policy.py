"""M11: fail-closed sandbox cleanup verification policy (pure/offline).

This module deliberately does not call Docker and cannot replace the active
Pi v0.6.1 cleanup logic without first reviewing the exact installed source,
r._run semantics, local approval, independent tests and rollback.

A nonzero docker inspect return code alone does NOT prove that a container is
absent (daemon may be unreachable, permission denied, etc.).
"""
from __future__ import annotations

from collections.abc import Sequence

OBSERVED = frozenset({"PRESENT", "ABSENT", "QUERY_ERROR"})
MAX_OBSERVATIONS = 8
REQUIRED_CONSECUTIVE_ABSENT = 2


class CleanupDecisionDenied(ValueError):
    pass


def decide_container_absence(*, remove_attempted: bool,
                             remove_exit_code: int | None,
                             observations: Sequence[str],
                             docker_timeout: bool) -> dict:
    """Classify already gathered, trusted inventory probes.

    Never infers the historical Docker command result from current absence.
    This only says whether two independent successful exact-name readbacks
    at a later instant observed no container.
    """
    if (type(remove_attempted) is not bool or
            type(docker_timeout) is not bool or
            type(remove_exit_code) not in (int, type(None)) or
            isinstance(remove_exit_code, bool)):
        raise CleanupDecisionDenied("CLEANUP_INPUT_SCHEMA_DENIED")
    if remove_exit_code is not None and not 0 <= remove_exit_code <= 255:
        raise CleanupDecisionDenied("CLEANUP_EXIT_CODE_INVALID")
    if not remove_attempted and remove_exit_code is not None:
        raise CleanupDecisionDenied("CLEANUP_REMOVE_EVIDENCE_CONTRADICTORY")
    if (not isinstance(observations, (list, tuple)) or
            not 0 <= len(observations) <= MAX_OBSERVATIONS or
            any(type(v) is not str or v not in OBSERVED
                for v in observations)):
        raise CleanupDecisionDenied("CLEANUP_PROBE_SCHEMA_DENIED")

    # Any Docker daemon/probe error is uncertainty: fail closed
    # even when a later query happens to claim an empty inventory.
    unknown = "QUERY_ERROR" in observations
    # Only successful exact-name, independent inventory queries may supply
    # ABSENT; a nonzero docker inspect is never an ABSENT observation.
    absent_twice = len(observations) >= REQUIRED_CONSECUTIVE_ABSENT and (
        tuple(observations[-2:]) == ("ABSENT", "ABSENT")
    )
    verified_current_absence = (
        remove_attempted and not unknown and absent_twice
    )
    return {
        "status": (
            "CURRENT_CONTAINER_ABSENCE_VERIFIED"
            if verified_current_absence
            else "CLEANUP_VERIFICATION_INCOMPLETE"
        ),
        "remove_attempted": remove_attempted,
        "remove_exit_code_observed": remove_exit_code is not None,
        "remove_success_observed": remove_exit_code == 0,
        "docker_run_timed_out": docker_timeout,
        "exact_name_absent_probes": sum(x == "ABSENT" for x in observations),
        "exact_name_present_seen": "PRESENT" in observations,
        "docker_probe_error_seen": unknown,
        "current_container_absence_verified": bool(verified_current_absence),
        # Success of a later probe NEVER rewrites the original failed
        # run receipt, and does not authorize a follow-on full backend test.
        "historical_cleanup_receipt_resolved": False,
        "sandbox_test_retry_authorized": False,
        "container_removal_authorized": False,
        "mcp_activation_authorized": False,
        "production_modified": False,
    }
