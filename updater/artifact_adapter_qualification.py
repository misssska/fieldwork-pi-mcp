"""Read-only qualification of an inert artifact MCP adapter candidate.

Supply bytes and exact, independently reviewed SHA256 pins. No network, disk
access, installation, shell, service stop, tunnel restart or dynamic import.
Even a PASS here is NOT activation approval.
"""
from __future__ import annotations

import ast
import hashlib
import re

from . import artifact_inbox_overlay as reference_overlay

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MODULES = frozenset({
    "artifact_inbox.py",
    "artifact_inbox_adapter.py",
    "artifact_inbox_overlay.py",
})
MAX_BYTES = 1_000_000


class QualificationDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise QualificationDenied(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def qualify(source: bytes, expected_source_sha256: str,
            modules: dict[str, bytes], expected_module_sha256: dict[str, str]) -> dict:
    require(type(source) is bytes and 0 < len(source) <= MAX_BYTES, "SOURCE_INVALID")
    require(type(expected_source_sha256) is str and
            HEX64.fullmatch(expected_source_sha256) is not None,
            "SOURCE_PIN_INVALID")
    require(sha(source) == expected_source_sha256, "SOURCE_HASH_DRIFT")
    require(type(modules) is dict and type(expected_module_sha256) is dict and
            set(modules) == MODULES and set(expected_module_sha256) == MODULES,
            "MODULE_SET_INVALID")
    for name in sorted(MODULES):
        content = modules[name]
        expected = expected_module_sha256[name]
        require(type(content) is bytes and 0 < len(content) <= MAX_BYTES,
                "MODULE_INVALID:" + name)
        require(type(expected) is str and HEX64.fullmatch(expected) is not None and
                sha(content) == expected, "MODULE_PIN_MISMATCH:" + name)
        try:
            ast.parse(content.decode("utf-8"), filename=name)
        except (SyntaxError, UnicodeError) as exc:
            raise QualificationDenied("MODULE_SYNTAX_INVALID:" + name) from exc

    # The only overlay allowed is the reviewed module in the running
    # qualification program. A caller cannot substitute another implementation.
    reference = open_overlay_reference_bytes()
    require(sha(modules["artifact_inbox_overlay.py"]) == sha(reference),
            "OVERLAY_IMPLEMENTATION_DRIFT")
    try:
        candidate = reference_overlay.overlay(source)
        ast.parse(candidate)
    except (ValueError, SyntaxError) as exc:
        raise QualificationDenied("INTEGRATION_ANCHOR_MISMATCH") from exc
    require(candidate != source, "NO_SOURCE_EXTENSION")
    return {
        "status": "STATIC_ARTIFACT_ADAPTER_QUALIFIED",
        "installed_source_sha256": sha(source),
        "candidate_source_sha256": sha(candidate),
        "module_sha256": {name: sha(modules[name]) for name in sorted(MODULES)},
        "tool_names": [
            "fieldwork_artifact_begin",
            "fieldwork_artifact_append",
            "fieldwork_artifact_status",
            "fieldwork_artifact_finalize",
        ],
        "runtime_tested": False,
        "activation_authorized": False,
        "mcp_modified": False,
        "tunnel_restarted": False,
        "production_modified": False,
    }


def open_overlay_reference_bytes() -> bytes:
    """Never read caller-supplied or arbitrary file paths."""
    from pathlib import Path
    return Path(reference_overlay.__file__).read_bytes()
