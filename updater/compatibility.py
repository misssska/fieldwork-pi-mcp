"""Read-only compatibility check for the installed FieldWork Pi MCP.

Never prints source code, credentials, or file contents.
No network, shell, write, service restart or production access.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

DEFAULT_SOURCE = Path.home() / ".local/share/fieldwork-pi-mcp/v0.6.1/fieldwork_mcp.py"
BASELINE_SHA256 = "b504460dc1477898dc048dc990e7fd432ba880926f9f063904cd6a9b085e5948"
OBSERVED_PI_SHA256 = "7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04"
REQUIRED_NAMES = ("fieldwork_stage_test_request", "fieldwork_stage_test_status")


def inspect(path: Path) -> dict:
    # This command is diagnostic only. Do not read other paths.
    if path.is_symlink() or not path.is_file():
        return {"status": "BLOCKED", "reason": "MISSING_OR_SYMLINK"}
    data = path.read_bytes()
    if len(data) > 2_000_000:
        return {"status": "BLOCKED", "reason": "SOURCE_TOO_LARGE"}
    digest = hashlib.sha256(data).hexdigest()
    try:
        source = data.decode("utf-8")
        ast.parse(source, filename="fieldwork_mcp.py")
    except (UnicodeError, SyntaxError):
        return {"status": "BLOCKED", "reason": "SOURCE_NOT_VALID_PYTHON",
                "installed_sha256": digest}
    # Exact names only; this does not claim that the tools are registered or callable.
    presence = {name: name in source for name in REQUIRED_NAMES}
    if digest == BASELINE_SHA256:
        status = "KNOWN_BUNDLE_BASELINE"
    elif digest == OBSERVED_PI_SHA256:
        status = "KNOWN_PI_HASH_SOURCE_NOT_REVIEWED"
    else:
        status = "UNREVIEWED_INSTALLED_SOURCE"
    return {"status": status, "installed_sha256": digest,
            "async_tool_name_presence": presence,
            "safe_to_overwrite": False,
            "next_step": "REVIEW_ACTUAL_SOURCE_BEFORE_INSTALL"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = inspect(DEFAULT_SOURCE)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "KNOWN_BUNDLE_BASELINE" else 2


if __name__ == "__main__":
    sys.exit(main())
