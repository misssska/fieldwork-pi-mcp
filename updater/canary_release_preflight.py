"""Single fail-closed boundary: verified MCP transfer -> pinned Git base plan.

This is the canonical **read-only release preflight** to replace disconnected
transport/ZIP/base checks. Retains the transfer lock until all verifications
complete, so retirement cannot race the source read. It never installs source,
runs untrusted code, starts Docker, alters /opt/fieldwork or claims deploy.
"""
from __future__ import annotations

from . import artifact_inbox as inbox
from . import canary_archive_qualifier as qualifier
from . import canary_git_base as base


def preflight_transfer(transfer_id: str) -> dict:
    inbox._valid_id(transfer_id)
    root = inbox._transfer(transfer_id)
    lock_fd = inbox._lock(root)
    try:
        record = inbox._record(root)
        path, received, state = inbox._content_state(root, record)
        qualifier.require(state == "VERIFIED" and received == record["size"],
                          "RELEASE_TRANSFER_NOT_VERIFIED")
        archive = inbox._owned_file(path, max_size=qualifier.MAX_ARCHIVE)
        report = base.preflight(archive, record["sha256"])
        result = {
            **report.receipt,
            "status": "RELEASE_PREFLIGHT_PASS_NOT_TESTED_NOT_STAGED",
            "transfer_id": transfer_id,
            "release_verification": "SHA256_ARCHIVE_MANIFEST_AND_PINNED_GIT_BASE",
            "stage_written": False,
            "tests_run": False,
            "deployment_authorized": False,
            "production_modified": False,
        }
        return result
    finally:
        import os
        os.close(lock_fd)
