"""One-time locally approved FieldWork MCP adapter installer with rollback.

Scope: current admin-owned v0.6.1 MCP Python files and ONE existing systemd
unit. No /opt/fieldwork, production Docker, DB, new tunnel, arbitrary shell.
Downloads are pinned to an immutable 40-hex Git commit. Command defaults to
preflight and DOES NOT install unless --activate and typed local confirmation.
Activation is always an operator action, never an MCP tool.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SOURCE_SHA = "7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04"
OWNER_REPO = "misssska/fieldwork-pi-mcp"
UNIT = "fieldwork-pi-tunnel.service"
MCP_REL = ".local/share/fieldwork-pi-mcp/v0.6.1"
STATE_REL = ".local/state/fieldwork-pi-mcp/one-time-artifact-activation"
FILES = ("artifact_inbox.py", "artifact_inbox_adapter.py")
MODULES = FILES + ("artifact_inbox_overlay.py",)
HASH = re.compile(r"[a-f0-9]{40}\Z")
MAX_BYTES = 1_000_000


class Stop(RuntimeError):
    pass


def require(yes: bool, reason: str) -> None:
    if not yes:
        raise Stop(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def owned(path: Path, maximum: int = MAX_BYTES) -> bytes:
    require(path.is_file() and not path.is_symlink(), "SOURCE_UNSAFE")
    st = path.stat()
    require(st.st_uid == os.geteuid(), "SOURCE_OWNER_MISMATCH")
    require(not (stat.S_IMODE(st.st_mode) & 0o077), "SOURCE_PERMISSIONS_TOO_OPEN")
    require(0 < st.st_size <= maximum, "SOURCE_SIZE_DENIED")
    return path.read_bytes()


def directory(path: Path, *, create: bool = False) -> None:
    require(not path.is_symlink(), "DIRECTORY_SYMLINK_DENIED")
    if create and not path.exists():
        path.mkdir(mode=0o700)
    require(path.is_dir(), "DIRECTORY_MISSING")
    st = path.stat()
    require(st.st_uid == os.geteuid() and not (st.st_mode & 0o022),
            "DIRECTORY_PERMISSIONS_DENIED")


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(target: Path, contents: bytes, *, exclusive: bool = False) -> None:
    require(not target.is_symlink(), "TARGET_SYMLINK_DENIED")
    require(not exclusive or not target.exists(), "TARGET_ALREADY_EXISTS")
    fd, name = tempfile.mkstemp(prefix=".mcp-update-", dir=target.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())
        temp.chmod(0o600)
        if exclusive:
            # No overwrite even if another process created it meanwhile.
            os.link(temp, target, follow_symlinks=False)
            temp.unlink()
        else:
            os.replace(temp, target)
        fsync_dir(target.parent)
    finally:
        if temp.exists():
            temp.unlink()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise Stop("DOWNLOAD_REDIRECT_DENIED")


def retrieve(commit: str, filename: str) -> bytes:
    require(HASH.fullmatch(commit) is not None and filename in MODULES,
            "DOWNLOAD_SOURCE_NOT_PINNED")
    url = f"https://raw.githubusercontent.com/{OWNER_REPO}/{commit}/updater/{filename}"
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "fieldwork-local-activation/1"})
    with opener.open(request, timeout=20) as response:
        require(response.status == 200, "DOWNLOAD_HTTP_STATUS_DENIED")
        raw = response.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, "DOWNLOAD_SIZE_DENIED")
    try:
        ast.parse(raw.decode("utf-8"), filename=filename)
    except (UnicodeError, SyntaxError) as exc:
        raise Stop("DOWNLOAD_PYTHON_INVALID:" + filename) from exc
    return raw


def compile_candidate(current: bytes, overlay: bytes) -> bytes:
    """Apply the reviewed exact-anchor source transformation in memory.

    The downloaded overlay module is NOT executed. These constants must match
    the versioned, reviewed overlay before the candidate is built.
    """
    require(sha(current) == SOURCE_SHA, "INSTALLED_MCP_SHA_DRIFT")
    try:
        text = current.decode("utf-8")
        ast.parse(text)
        patch = overlay.decode("utf-8")
        ast.parse(patch)
    except (UnicodeError, SyntaxError) as exc:
        raise Stop("MCP_OR_OVERLAY_INVALID") from exc
    import_anchor = "import stage_manager\n"
    import_add = import_anchor + "import artifact_inbox_adapter\n"
    tools_anchor = '''    ("fieldwork_stage_full_test", "Run all backend tests including admin rotation using separate stage-only test Docker project", {
        "proposal_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, stage_manager.full_test),
'''
    tools_added = '''    ("fieldwork_artifact_begin", "Reserve one exact SHA256-pinned inert canary upload; never deploy", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "size": {"type": "integer", "minimum": 1, "maximum": 33554432},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    }, artifact_inbox_adapter.begin),
    ("fieldwork_artifact_append", "Append ordered bounded base64 bytes; no execution", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "offset": {"type": "integer", "minimum": 0, "maximum": 33554432},
        "chunk_base64": {"type": "string", "minLength": 1, "maxLength": 44000}
    }, artifact_inbox_adapter.append),
    ("fieldwork_artifact_status", "Read inert upload receipt", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, artifact_inbox_adapter.status),
    ("fieldwork_artifact_finalize", "Verify complete artifact SHA256; never deploy", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, artifact_inbox_adapter.finalize),
'''
    audit_old = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start"'
    audit_new = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start", "fieldwork_artifact_begin", "fieldwork_artifact_append", "fieldwork_artifact_status", "fieldwork_artifact_finalize"'
    # Bound our implementation to the released overlay's exact source constants:
    require('IMPORT_OLD = "import stage_manager\\n"' in patch and
            'IMPORT_NEW = IMPORT_OLD + "import artifact_inbox_adapter\\n"' in patch,
            "RELEASE_IMPORT_ANCHORS_DIFFER")
    require(tools_anchor in patch and tools_added in patch,
            "RELEASE_TOOL_ANCHORS_DIFFER")
    require(audit_old in patch and audit_new in patch, "RELEASE_AUDIT_ANCHORS_DIFFER")
    require("artifact_inbox_adapter" not in text and "fieldwork_artifact_begin" not in text,
            "ALREADY_ACTIVATED_OR_PARTIAL")
    for old, new in ((import_anchor, import_add),
                     (tools_anchor, tools_anchor + tools_added),
                     (audit_old, audit_new)):
        require(text.count(old) == 1, "INSTALLED_SOURCE_ANCHOR_DRIFT")
        text = text.replace(old, new, 1)
    ast.parse(text)
    return text.encode("utf-8")


def service(operation: str) -> bool:
    require(operation in ("is-active", "restart"), "SERVICE_ACTION_DENIED")
    cmd = ["systemctl", "is-active", UNIT] if operation == "is-active" else [
        "sudo", "-n", "systemctl", "restart", UNIT]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ready() -> bool:
    # The existing tunnel-client listens only on the local loopback address.
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:18080/readyz")
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def paths(home: Path) -> tuple[Path, Path]:
    require(os.geteuid() != 0 and home == Path.home() and
            home.is_absolute() and not home.is_symlink(), "OWNER_OR_HOME_DENIED")
    root = home
    directory(root)
    for name in MCP_REL.split("/"):
        root = root / name
        directory(root)
    state = home
    for name in STATE_REL.split("/"):
        state = state / name
        directory(state, create=True)
    require(not (stat.S_IMODE(state.stat().st_mode) & 0o077), "STATE_NOT_PRIVATE")
    return root, state


def lock(state: Path) -> int:
    target = state / "activation.lock"
    require(not target.is_symlink(), "LOCK_SYMLINK")
    fd = os.open(target, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    st = os.fstat(fd)
    require(st.st_uid == os.geteuid() and not (stat.S_IMODE(st.st_mode) & 0o077),
            "LOCK_PERMISSIONS")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def prepare(commit: str, root: Path) -> tuple[bytes, dict[str, bytes]]:
    current = owned(root / "fieldwork_mcp.py")
    require(sha(current) == SOURCE_SHA, "SOURCE_SHA_MISMATCH")
    require(all(not (root / name).exists() and not (root / name).is_symlink()
                for name in FILES), "MODULES_ALREADY_INSTALLED")
    require(service("is-active"), "TUNNEL_NOT_RUNNING")
    modules = {name: retrieve(commit, name) for name in MODULES}
    candidate = compile_candidate(current, modules["artifact_inbox_overlay.py"])
    return candidate, modules


def activate(commit: str, root: Path, state: Path) -> None:
    require(not (state / "receipt.json").exists(), "PREVIOUS_ACTIVATION_PRESENT")
    candidate, modules = prepare(commit, root)
    print("SOURCE_PREFLIGHT_PASS", flush=True)
    print("CANDIDATE_SHA256=" + sha(candidate), flush=True)
    print("TUNNEL_UNIT=" + UNIT, flush=True)
    print("SCOPE=MCP_FILES_ONLY", flush=True)
    confirmation = input("A folytatáshoz írd be: AKTIVALOM: ").strip()
    require(confirmation == "AKTIVALOM", "LOCAL_APPROVAL_NOT_GIVEN")
    # A separate SSH process is the controller. The tunnel is not the controller.
    require(service("is-active"), "TUNNEL_DIED_BEFORE_ACTIVATION")
    require(sha(owned(root / "fieldwork_mcp.py")) == SOURCE_SHA, "SOURCE_CHANGED_BEFORE_WRITE")
    backup = state / "original-fieldwork_mcp.py"
    write_atomic(backup, owned(root / "fieldwork_mcp.py"), exclusive=True)
    receipt = {"schema": 1, "commit": commit, "state": "PREPARED",
               "source_sha256": SOURCE_SHA, "candidate_sha256": sha(candidate),
               "module_sha256": {f: sha(modules[f]) for f in FILES}}
    write_atomic(state / "receipt.json", json.dumps(receipt, sort_keys=True).encode(), exclusive=True)
    try:
        for name in FILES:
            write_atomic(root / name, modules[name], exclusive=True)
        write_atomic(root / "fieldwork_mcp.py", candidate)
        receipt["state"] = "APPLIED_PENDING_HEALTH"
        write_atomic(state / "receipt.json", json.dumps(receipt, sort_keys=True).encode())
        require(service("restart"), "TUNNEL_RESTART_FAILED")
        for _ in range(12):
            if service("is-active") and ready():
                receipt["state"] = "TUNNEL_READY_MCP_DISCOVERY_PENDING"
                write_atomic(state / "receipt.json", json.dumps(receipt, sort_keys=True).encode())
                print("ACTIVATION_TUNNEL_READY_MCP_DISCOVERY_PENDING", flush=True)
                print("CHECK_NEW_MCP_TOOLS_FROM_CHATGPT_BEFORE_DECLARING_PASS", flush=True)
                return
            time.sleep(2)
        raise Stop("TUNNEL_HEALTH_NOT_RECOVERED")
    except Exception:
        print("ACTIVATION_FAILED_BEGIN_ROLLBACK", flush=True)
        rollback(root, state)
        raise


def rollback(root: Path, state: Path) -> None:
    receipt = json.loads(owned(state / "receipt.json", 32_768))
    require(type(receipt) is dict and receipt.get("source_sha256") == SOURCE_SHA,
            "ROLLBACK_RECEIPT_INVALID")
    original = owned(state / "original-fieldwork_mcp.py")
    require(sha(original) == SOURCE_SHA, "BACKUP_SHA_MISMATCH")
    current = owned(root / "fieldwork_mcp.py")
    require(sha(current) in (SOURCE_SHA, receipt["candidate_sha256"]),
            "UNEXPECTED_MCP_CHANGE_NO_OVERWRITE")
    for name, digest in receipt["module_sha256"].items():
        path = root / name
        if path.exists() or path.is_symlink():
            require(sha(owned(path)) == digest, "UNEXPECTED_MODULE_CHANGE:" + name)
    write_atomic(root / "fieldwork_mcp.py", original)
    for name in FILES:
        path = root / name
        if path.exists():
            path.unlink()
    fsync_dir(root)
    receipt["state"] = "ROLLED_BACK"
    write_atomic(state / "receipt.json", json.dumps(receipt, sort_keys=True).encode())
    require(service("restart"), "ROLLBACK_TUNNEL_RESTART_FAILED")
    print("MCP_SOURCE_ROLLED_BACK=" + SOURCE_SHA, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        require(HASH.fullmatch(args.commit) is not None, "COMMIT_PIN_REQUIRED")
        root, state = paths(Path.home())
        fd = lock(state)
        try:
            if args.rollback:
                rollback(root, state)
            elif args.activate:
                activate(args.commit, root, state)
            else:
                candidate, modules = prepare(args.commit, root)
                print(json.dumps({"status": "DRY_RUN_PASS_NOT_INSTALLED",
                                  "source_sha256": SOURCE_SHA,
                                  "candidate_sha256": sha(candidate),
                                  "modules": {name: sha(data) for name, data in modules.items()},
                                  "activation_authorized": False,
                                  "production_modified": False}, sort_keys=True))
            return 0
        finally:
            os.close(fd)
    except (Stop, OSError, ValueError, urllib.error.URLError, BlockingIOError) as exc:
        print("ACTIVATION_STOP=" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
