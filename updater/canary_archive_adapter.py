"""Strict MCP adapter for validating finalized FieldWork canary source archives.

This adapter never imports archive code, patches a checkout or starts Docker.
"""
from __future__ import annotations

import re

if __package__:
    from . import canary_archive_qualifier as qualifier
else:
    import canary_archive_qualifier as qualifier

HEX32 = re.compile(r"[0-9a-f]{32}\Z")


def qualify(args: object) -> dict:
    if type(args) is not dict or set(args) != {"transfer_id"}:
        raise qualifier.QualificationDenied("ARGUMENTS_SCHEMA_DENIED")
    transfer_id = args["transfer_id"]
    if type(transfer_id) is not str or HEX32.fullmatch(transfer_id) is None:
        raise qualifier.QualificationDenied("TRANSFER_ID_INVALID")
    return qualifier.qualify_transfer(transfer_id)
