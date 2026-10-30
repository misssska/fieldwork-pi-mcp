"""Read-only, non-secret host preflight for a one-time FieldWork Pi MCP activation.

Run locally as the current MCP owner. The probe never fetches, installs,
restarts, modifies or exposes the MCP source or environment variables.
It returns only source fingerprints and a few non-sensitive invariants.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

MCP_REL = Path(".local/share/fieldwork-pi-mcp/v0.6.1")
MAIN = "fieldwork_mcp.py"
EXTENSIONS = ("stage_async.py", "stage_inspect.py", "stage_start_async.py",
              "artifact_inbox.py", "artifact_inbox_adapter.py")
MAX_SOURCE = 1_000_000
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class PreflightDenied(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PreflightDenied(code)


def _directory(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink(), "DIRECTORY_MISSING_OR_SYMLINK")
    st = path.stat()
    require(st.st_uid == os.geteuid() and not (stat.S_IMODE(st.st_mode) & 0o022),
            "DIRECTORY_PERMISSIONS_DENIED")


def _main_bytes(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), "MCP_MAIN_MISSING_OR_SYMLINK")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & 0o022), "MCP_MAIN_PERMISSIONS_DENIED")
    require(0 < st.st_size <= MAX_SOURCE, "MCP_MAIN_SIZE_DENIED")
    data = path.read_bytes()
    require(len(data) == st.st_size, "MCP_MAIN_CHANGED_DURING_READ")
    try:
        ast.parse(data.decode("utf-8"), filename=MAIN)
    except (UnicodeError, SyntaxError) as exc:
        raise PreflightDenied("MCP_MAIN_PYTHON_INVALID") from exc
    return data


def inspect(home: Path, expected_source_sha256: str) -> dict:
    """Inspect fixed user-home source only; does not modify the host."""
    require(os.geteuid() != 0, "ROOT_DENIED")
    require(type(expected_source_sha256) is str and
            HEX64.fullmatch(expected_source_sha256) is not None,
            "SOURCE_PIN_REQUIRED")
    require(home.is_absolute() and not home.is_symlink(), "HOME_INVALID")
    root = home
    _directory(root)
    for part in MCP_REL.parts:
        root = root / part
        _directory(root)
    data = _main_bytes(root / MAIN)
    actual = hashlib.sha256(data).hexdigest()
    extension_states: dict[str, str] = {}
    for name in EXTENSIONS:
        file = root / name
        if file.is_symlink():
            extension_states[name] = "SYMLINK_UNSAFE"
        elif file.exists():
            extension_states[name] = "PRESENT"
        else:
            extension_states[name] = "ABSENT"
    clean_extension_state = all(state == "ABSENT" for state in extension_states.values())
    matches = actual == expected_source_sha256
    # No enabling action; a clean source alone is still insufficient for activation.
    return {
        "status": "SOURCE_PREFLIGHT_MATCH" if matches and clean_extension_state
                  else "SOURCE_PREFLIGHT_REVIEW_REQUIRED",
        "mcp_version_path": "v0.6.1",
        "source_sha256": actual,
        "source_matches_reviewed_pin": matches,
        "source_ast_valid": True,
        "module_states": extension_states,
        "source_qualification_possible": matches and clean_extension_state,
        "activation_authorized": False,
        "mcp_modified": False,
        "production_modified": False,
        "tunnel_restarted": False,
    }


def tunnel_active() -> str:
    """Read a fixed systemd unit's state. Suppress raw diagnostics/credentials."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "fieldwork-pi-tunnel.service"],
            capture_output=True, text=True, timeout=4, check=False,
        )
        return "ACTIVE" if result.returncode == 0 and result.stdout.strip() == "active" else "NOT_ACTIVE"
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def main() -> int:
    # This standalone command is intentionally read-only and uses only stdlib.
    expected = "7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04"
    try:
        result = inspect(Path.home(), expected)
        result["tunnel_status"] = tunnel_active()
    except (PreflightDenied, OSError) as exc:
        print(json.dumps({"status": "SOURCE_PREFLIGHT_DENIED",
                          "reason": str(exc), "activation_authorized": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["source_qualification_possible"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
