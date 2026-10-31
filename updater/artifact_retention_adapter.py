"""Exact-argument MCP adapter to retire one already-verified transfer.

Explicit per-transfer SHA256 confirmation; no general file deletion, no shell,
no production access, no automatic removal of pending uploads.
"""
from __future__ import annotations

if __package__:
    from . import artifact_retention as retention
    from . import artifact_inbox as inbox
else:
    import artifact_retention as retention
    import artifact_inbox as inbox


def retire(args: object) -> dict:
    if type(args) is not dict or set(args) != {
        "transfer_id", "sha256", "approval"
    }:
        raise inbox.InboxDenied("RETIRE_ARGUMENTS_SCHEMA_DENIED")
    transfer_id, hashed, approval = (args["transfer_id"], args["sha256"],
                                    args["approval"])
    inbox._valid_id(transfer_id)
    if type(hashed) is not str or inbox.HEX64.fullmatch(hashed) is None:
        raise inbox.InboxDenied("RETIRE_HASH_DENIED")
    if approval != retention.APPROVAL:
        raise inbox.InboxDenied("RETIRE_APPROVAL_REQUIRED")
    return retention.retire(transfer_id, hashed, approval)
