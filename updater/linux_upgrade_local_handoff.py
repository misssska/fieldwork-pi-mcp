"""M14 strictly LOCAL operator-to-installer signed approval handoff.

Never expose as a remote MCP handler or HTTP route. Two separate trusted
local principals require a configured, audited IPC boundary in production;
this stand-alone Python bridge only joins the review UI with the existing
offline transaction code for isolated test environments.

The installer must independently validate release publisher/trust, fetch
only immutable source bytes and implement real service restart + health.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

if __package__:
    from . import linux_upgrade_gate as gate
    from . import linux_upgrade_local_transaction as local
else:
    import linux_upgrade_gate as gate
    import linux_upgrade_local_transaction as local


class HandoffDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise HandoffDenied(code)


def read_exact_ticket(root: Path, plan_sha256: str) -> dict:
    """Read immutable, local-only approval for one independently known plan."""
    local.directory(root)
    require(type(plan_sha256) is str and
            gate.HEX64.fullmatch(plan_sha256) is not None,
            "HANDOFF_PLAN_SHA_DENIED")
    file = root / (plan_sha256 + ".json")
    require(file.is_file() and not file.is_symlink(),
            "HANDOFF_NOT_REGULAR_OR_SYMLINK")
    state = file.stat()
    require(state.st_uid == os.geteuid() and
            stat.S_IMODE(state.st_mode) == 0o600 and
            0 < state.st_size <= 4096,
            "HANDOFF_FILE_MODE_SIZE_DENIED")
    fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(4097)
    except OSError as exc:
        raise HandoffDenied("HANDOFF_READ_FAILED") from exc
    require(len(data) == state.st_size and len(data) <= 4096,
            "HANDOFF_CHANGED_ON_READ")
    try:
        ticket = json.loads(data.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise HandoffDenied("HANDOFF_BAD_JSON") from exc
    require(gate.canon(ticket) == data, "HANDOFF_NOT_CANONICAL")
    require(type(ticket) is dict and
            set(ticket) == gate.AUTH_KEYS and
            ticket["plan_sha256"] == plan_sha256,
            "HANDOFF_PLAN_MISMATCH")
    return ticket


def apply_one_reviewed_plan(request: dict, policy: gate.HostPolicy, *,
                            install_root: Path, state_root: Path,
                            handoff_root: Path,
                            source_bytes: dict[str, bytes],
                            local_secret: bytes, now: int,
                            health_check) -> dict:
    """Local-only, externally trusted executor. Never call from HTTP.

    source_bytes, policy, secret, and dirs must be supplied by local trusted
    configuration; user-controlled request paths / code URLs never accepted.
    """
    require(os.geteuid() != 0, "HANDOFF_ROOT_DENIED")
    local.directory(install_root)
    local.directory(state_root)
    local.directory(handoff_root)
    require(len({install_root.resolve(), state_root.resolve(),
                 handoff_root.resolve()}) == 3,
            "HANDOFF_DIRECTORY_OVERLAP_DENIED")
    active = local._active(install_root, policy)
    plan = gate.validate_plan(request, policy, active, now)
    ticket = read_exact_ticket(handoff_root, plan.plan_sha256)
    # Verify independently before entering the atomic local transaction.
    spent = state_root / "spent"
    local.directory(spent)
    gate.verify_local_approval(
        plan, ticket, local_secret=local_secret, now=now,
        spent_nonces=frozenset(x.name for x in spent.iterdir())
    )
    result = local.apply_approved(
        request, policy, install_root=install_root,
        state_root=state_root, source_bytes=source_bytes,
        approval=ticket, local_secret=local_secret, now=now,
        health_check=health_check,
    )
    return {
        "status": "LOCAL_APPROVED_HANDOFF_APPLIED",
        "host_id": result["host_id"],
        "plan_sha256": result["plan_sha256"],
        "modules": result["changed_modules"],
        "production_modified": False,
        "approval_ticket_disclosed_remotely": False,
        "real_service_restart_performed": False,
    }
