"""Bounded MCP argument adapter for inert FieldWork canary artifact upload.

NOT a deployed MCP tool, installer, shell or source-code executor.
The actual MCP must undergo separately locally approved activation.
"""
from __future__ import annotations

import re
from typing import Any

from updater import artifact_inbox as inbox

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_B64 = 44_000  # at most ~32 KiB of decoded bytes per MCP call


def _arguments(value: object, names: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != names:
        raise inbox.InboxDenied("ARGUMENTS_SCHEMA_DENIED")
    return value


def _tid(value: object) -> str:
    if type(value) is not str or HEX32.fullmatch(value) is None:
        raise inbox.InboxDenied("TRANSFER_ID_INVALID")
    return value


def begin(args: object) -> dict:
    a = _arguments(args, {"transfer_id", "size", "sha256"})
    transfer_id = _tid(a["transfer_id"])
    if type(a["size"]) is not int or not 0 < a["size"] <= inbox.MAX_ARTIFACT:
        raise inbox.InboxDenied("SIZE_INVALID")
    h = a["sha256"]
    if type(h) is not str or HEX64.fullmatch(h) is None:
        raise inbox.InboxDenied("SHA256_INVALID")
    return inbox.begin(transfer_id, a["size"], h)


def append(args: object) -> dict:
    a = _arguments(args, {"transfer_id", "offset", "chunk_base64"})
    transfer_id = _tid(a["transfer_id"])
    if type(a["offset"]) is not int or not 0 <= a["offset"] <= inbox.MAX_ARTIFACT:
        raise inbox.InboxDenied("OFFSET_INVALID")
    payload = a["chunk_base64"]
    if type(payload) is not str or not 0 < len(payload) <= MAX_B64:
        raise inbox.InboxDenied("CHUNK_LENGTH_DENIED")
    return inbox.append(transfer_id, a["offset"], payload)


def status(args: object) -> dict:
    a = _arguments(args, {"transfer_id"})
    return inbox.status(_tid(a["transfer_id"]))


def finalize(args: object) -> dict:
    a = _arguments(args, {"transfer_id"})
    return inbox.finalize(_tid(a["transfer_id"]))
