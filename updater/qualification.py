"""Fail-closed, read-only qualification of a staged Async Stage MCP update.

Does not install, restart services, alter the MCP, or touch /opt/fieldwork.
All paths are fixed under the current user's home directory.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __package__:
    from .async_overlay import SourceDriftError, overlay
else:
    from async_overlay import SourceDriftError, overlay

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HOME = Path.home()
STAGING = HOME / ".local/state/fieldwork-pi-mcp/update-staging"
MCP = HOME / ".local/share/fieldwork-pi-mcp/v0.6.1"
REQUIRED = ("stage_async.py", "async_overlay.py")
MAX_SOURCE = 1_000_000


class QualificationError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise QualificationError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def owned_bytes(path: Path, limit: int) -> bytes:
    require(path.is_file() and not path.is_symlink(), "FILE_MISSING_OR_SYMLINK")
    st = path.stat()
    require(st.st_uid == os.getuid(), "FILE_NOT_OWNED")
    require(not (st.st_mode & 0o022), "FILE_WRITABLE_BY_OTHERS")
    require(st.st_size <= limit, "FILE_TOO_LARGE")
    return path.read_bytes()


def safe_directory(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink(), "DIRECTORY_MISSING_OR_SYMLINK")
    st = path.stat()
    require(st.st_uid == os.getuid(), "DIRECTORY_NOT_OWNED")
    require(not (st.st_mode & 0o022), "DIRECTORY_WRITABLE_BY_OTHERS")


def qualify(commit: str, manifest_hash: str, expected_installed_hash: str) -> dict:
    require(os.geteuid() != 0, "ROOT_DENIED")
    require(HEX40.fullmatch(commit) is not None, "COMMIT_SHA_REQUIRED")
    require(HEX64.fullmatch(manifest_hash) is not None, "MANIFEST_SHA_REQUIRED")
    require(HEX64.fullmatch(expected_installed_hash) is not None, "INSTALLED_SHA_REQUIRED")
    safe_directory(STAGING)
    safe_directory(MCP)
    stage = STAGING / (commit + "-" + manifest_hash[:12])
    safe_directory(stage)
    receipt = json.loads(owned_bytes(stage / "receipt.json", 8192))
    require(type(receipt) is dict and set(receipt) == {
        "commit", "manifest_sha256", "files", "status"
    }, "STAGE_RECEIPT_SCHEMA_DENIED")
    require(receipt["status"] == "STAGED_NOT_INSTALLED", "STAGE_NOT_READY")
    require(receipt["commit"] == commit and receipt["manifest_sha256"] == manifest_hash,
            "STAGE_RECEIPT_MISMATCH")
    require(type(receipt["files"]) is list and set(receipt["files"]) == set(REQUIRED)
            and len(receipt["files"]) == len(REQUIRED), "STAGE_FILE_LIST_DENIED")
    main = owned_bytes(MCP / "fieldwork_mcp.py", MAX_SOURCE)
    installed_hash = digest(main)
    require(installed_hash == expected_installed_hash, "INSTALLED_SOURCE_DRIFT")
    # Never silently accept an existing/partially applied extension.
    require(not (MCP / "stage_async.py").exists()
            and not (MCP / "stage_async.py").is_symlink(), "ASYNC_ALREADY_PRESENT")
    extension = owned_bytes(stage / "stage_async.py", MAX_SOURCE)
    overlay_bytes = owned_bytes(stage / "async_overlay.py", MAX_SOURCE)
    # The reviewed overlay implementation must be the one that produced the candidate.
    reference = owned_bytes(Path(__file__).with_name("async_overlay.py"), MAX_SOURCE)
    require(digest(overlay_bytes) == digest(reference), "OVERLAY_IMPLEMENTATION_DRIFT")
    try:
        ast.parse(extension.decode("utf-8"), filename="stage_async.py")
        candidate = overlay(main)
    except (UnicodeError, SyntaxError, SourceDriftError) as exc:
        raise QualificationError("CANDIDATE_INCOMPATIBLE:" + type(exc).__name__) from exc
    # Verify candidate is a strict extension of the installed file, not a full replacement.
    require(len(candidate) > len(main) and candidate != main, "CANDIDATE_NOT_EXTENDED")
    return {
        "status": "STATIC_QUALIFICATION_PASS",
        "commit": commit,
        "release_manifest_sha256": manifest_hash,
        "installed_source_sha256": installed_hash,
        "candidate_source_sha256": digest(candidate),
        "stage_async_sha256": digest(extension),
        "overlay_sha256": digest(overlay_bytes),
        "tool_names_expected": ["fieldwork_stage_test_request", "fieldwork_stage_test_status"],
        "unit_tests_run": False,
        "runtime_tests_run": False,
        "activation_authorized": False,
        "production_modified": False,
        "mcp_modified": False,
        "tunnel_restarted": False,
        "next_step": "ISOLATED_TEST_AND_EXPLICIT_LOCAL_APPROVAL_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-installed-sha256", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(qualify(args.commit, args.manifest_sha256,
                                 args.expected_installed_sha256), sort_keys=True))
        return 0
    except (QualificationError, OSError, ValueError, KeyError, TypeError) as exc:
        print("QUALIFICATION_FAILED=" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
