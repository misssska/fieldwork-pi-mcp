"""M12: ONE locally approved, immutable, rollback-safe FieldWork MCP extension.

Zero production access: changes ONLY two SHA-pinned admin-owned MCP Python
files and adds ONE read-only diagnostics module under ~/.local/share.
Restarts ONLY the existing fieldwork-pi-tunnel.service after local approval.
No new tunnel, container creation/removal, production DB or FieldWork writes.
No capability to self-upgrade or execute host shell via MCP after installation.

A GitHub-pinned, SHA256-verified launcher supplies an immutable commit id.
The installed sources MUST match the observed Pi hashes exactly.
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
import types
import urllib.error
import urllib.request

REPO = "misssska/fieldwork-pi-mcp"
ROOT = Path(".local/share/fieldwork-pi-mcp/v0.6.1")
STATE_ROOT = Path(".local/state/fieldwork-pi-mcp")
STATE_NAME = "m12-self-service-once"
UNIT = "fieldwork-pi-tunnel.service"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_DOWNLOAD = 200_000
MODULE_PINS = {
    "mcp_self_diagnostics.py":
        "38fa49a6233ff8f528852076d7a6e7c0a86d405e95145427fa74e98462b63885",
    "mcp_self_service_overlay.py":
        "4bf4ee041ddfe8b952d6c7bd5ebd8c195553bfba9f455b33b75fea0ad9071c4d",
    "sandbox_cleanup_overlay.py":
        "98d591d6d34e864f98b014361853f9bc180dbeb089e67542212d45ffe49f2a9a",
}
MAIN_PIN = "e0e7cfb7b70c7f79845337b84bb47025beaad6d429377b64d1972db68c3fbc1a"
RUNNER_PIN = "5255968dac5c0bb8ac3a94eb72f3131ea2081b683974d97db6bb9ddc3d432615"
CONSENT = "ENGEDÉLYEZEM_M12"


class ActivationStop(RuntimeError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ActivationStop(code)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_dir(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink(), "DIRECTORY_UNSAFE")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & 0o022),
            "DIRECTORY_OWNERSHIP_OR_PERMISSIONS")


def read_owned(path: Path, max_bytes: int = 1_000_000) -> bytes:
    require(path.is_file() and not path.is_symlink(), "FILE_UNSAFE")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & 0o077) and
            0 < st.st_size <= max_bytes, "FILE_OWNER_MODE_OR_SIZE")
    content = path.read_bytes()
    require(len(content) == st.st_size, "FILE_CHANGED_DURING_READ")
    return content


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path: Path, data: bytes, *, new: bool = False) -> None:
    require(not path.is_symlink() and (not new or not path.exists()),
            "TARGET_COLLISION_OR_SYMLINK")
    fd, tmp_name = tempfile.mkstemp(prefix=".m12-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o600)
        if new:
            os.link(tmp, path, follow_symlinks=False)
            tmp.unlink()
        else:
            os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ActivationStop("DOWNLOAD_REDIRECT_DENIED")


def get_pinned(commit: str, filename: str) -> bytes:
    require(HEX40.fullmatch(commit) is not None and
            filename in MODULE_PINS, "DOWNLOAD_SOURCE_NOT_ALLOWED")
    url = "https://raw.githubusercontent.com/" + REPO + "/" + commit + "/updater/" + filename
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "fieldwork-m12-local-once/1"})
    try:
        with opener.open(request, timeout=20) as response:
            require(response.status == 200, "DOWNLOAD_HTTP_STATUS")
            data = response.read(MAX_DOWNLOAD + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise ActivationStop("PINNED_DOWNLOAD_FAILED") from exc
    require(0 < len(data) <= MAX_DOWNLOAD and
            sha(data) == MODULE_PINS[filename],
            "DOWNLOADED_MODULE_HASH_MISMATCH")
    try:
        ast.parse(data)
    except (UnicodeError, SyntaxError) as exc:
        raise ActivationStop("DOWNLOADED_MODULE_SYNTAX_INVALID") from exc
    return data


def modules_from_pins(sources: dict[str, bytes]):
    # Both imported modules are matched to fixed SHA256 BEFORE execution.
    cleanup = types.ModuleType("sandbox_cleanup_overlay")
    exec(compile(sources["sandbox_cleanup_overlay.py"],
                 "sha256-pinned-sandbox-cleanup-overlay", "exec"),
         cleanup.__dict__)
    sys.modules["sandbox_cleanup_overlay"] = cleanup
    overlay = types.ModuleType("mcp_self_service_overlay")
    exec(compile(sources["mcp_self_service_overlay.py"],
                 "sha256-pinned-mcp-self-service-overlay", "exec"),
         overlay.__dict__)
    return overlay


def systemd(action: str) -> bool:
    require(action in {"is-active", "restart"},
            "SYSTEMD_ACTION_NOT_ALLOWED")
    command = (["systemctl", "is-active", UNIT] if action == "is-active" else
               ["sudo", "-n", "systemctl", "restart", UNIT])
    try:
        outcome = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=40, check=False,
        )
        return outcome.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ready() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/readyz",
                                    timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def record(state: Path, payload: dict, *, new: bool = False) -> None:
    atomic(state / "receipt.json",
           (json.dumps(payload, sort_keys=True) + "\n").encode(),
           new=new)


def restore(root: Path, state: Path, receipt: dict) -> None:
    previous_mcp = read_owned(state / "previous-fieldwork_mcp.py")
    previous_sandbox = read_owned(state / "previous-sandbox_command.py")
    require(sha(previous_mcp) == MAIN_PIN and
            sha(previous_sandbox) == RUNNER_PIN,
            "BACKUP_SOURCE_MISMATCH")
    # Never overwrite another process's unexpected concurrent MCP changes.
    current_mcp = read_owned(root / "fieldwork_mcp.py")
    current_sandbox = read_owned(root / "sandbox_command.py")
    require(sha(current_mcp) in {MAIN_PIN, receipt["new_mcp_sha256"]} and
            sha(current_sandbox) in
            {RUNNER_PIN, receipt["new_sandbox_sha256"]},
            "ROLLBACK_SOURCE_CHANGED")
    added = root / "mcp_self_diagnostics.py"
    if added.exists() or added.is_symlink():
        require(sha(read_owned(added)) ==
                MODULE_PINS["mcp_self_diagnostics.py"],
                "ROLLBACK_MODULE_CHANGED")
    atomic(root / "fieldwork_mcp.py", previous_mcp)
    atomic(root / "sandbox_command.py", previous_sandbox)
    if added.exists():
        added.unlink()
        fsync_dir(root)
    receipt["status"] = "ROLLED_BACK"
    record(state, receipt)
    require(systemd("restart"), "ROLLBACK_TUNNEL_RESTART_FAILED")


def execute_once(commit: str, *, confirm: bool) -> dict:
    require(os.geteuid() != 0, "ROOT_DENIED")
    require(type(commit) is str and HEX40.fullmatch(commit) is not None,
            "IMMUTABLE_COMMIT_REQUIRED")
    require(confirm is True, "EXPLICIT_ACTIVATION_REQUIRED")
    home = Path.home()
    require(home.is_absolute() and not home.is_symlink(), "HOME_UNSAFE")
    safe_dir(home)
    root = home
    for part in ROOT.parts:
        root = root / part
        safe_dir(root)
    parent = home
    for part in STATE_ROOT.parts:
        parent = parent / part
        safe_dir(parent)
    state = parent / STATE_NAME
    require(not state.exists() and not state.is_symlink(),
            "PREVIOUS_M12_ATTEMPT_EXISTS")
    require(systemd("is-active"), "TUNNEL_NOT_ACTIVE")

    main = read_owned(root / "fieldwork_mcp.py")
    sandbox = read_owned(root / "sandbox_command.py")
    require(sha(main) == MAIN_PIN and sha(sandbox) == RUNNER_PIN,
            "INSTALLED_MCP_VERSION_NOT_REVIEWED")
    require(not (root / "mcp_self_diagnostics.py").exists() and
            not (root / "mcp_self_diagnostics.py").is_symlink(),
            "DIAGNOSTICS_ALREADY_EXISTS")
    sources = {name: get_pinned(commit, name) for name in MODULE_PINS}
    patcher = modules_from_pins(sources)
    candidate = patcher.build_mcp_and_cleanup(main, sandbox)
    require(candidate["status"] == "M12_OFFLINE_CANDIDATE_ONLY" and
            candidate["activation_authorized"] is False,
            "CANDIDATE_POLICY_DENIED")
    digest_main = sha(candidate["mcp_bytes"])
    digest_sandbox = sha(candidate["sandbox_bytes"])
    # In-memory compile and module AST only; no application source runs here.
    for name, content in (
        ("fieldwork_mcp.py", candidate["mcp_bytes"]),
        ("sandbox_command.py", candidate["sandbox_bytes"]),
        ("mcp_self_diagnostics.py", sources["mcp_self_diagnostics.py"]),
    ):
        ast.parse(content, filename=name)
        compile(content, name, "exec")

    print("M12_PREFLIGHT_PASS", flush=True)
    print("OLD_MCP_SHA256=" + MAIN_PIN)
    print("NEW_MCP_SHA256=" + digest_main)
    print("NEW_SANDBOX_SHA256=" + digest_sandbox)
    print("SCOPE=MCP_SOURCE_AND_SANDBOX_ONLY_PRODUCTION_UNTOUCHED")
    answer = input("Egyszeri helyi jóváhagyás (" + CONSENT + "): ").strip()
    require(answer == CONSENT, "LOCAL_APPROVAL_DENIED")
    # Permission to restart existing unit is confirmed BEFORE any writes.
    try:
        require(subprocess.run(["sudo", "-v"], timeout=80,
                check=False).returncode == 0, "SUDO_NOT_APPROVED")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ActivationStop("SUDO_NOT_APPROVED") from exc
    require(systemd("is-active"), "TUNNEL_CHANGED_BEFORE_WRITE")
    require(sha(read_owned(root / "fieldwork_mcp.py")) == MAIN_PIN and
            sha(read_owned(root / "sandbox_command.py")) == RUNNER_PIN,
            "INSTALLED_SOURCE_CHANGED_AFTER_APPROVAL")

    # All writes after this point are limited to user-owned MCP + private
    # state directory; production /opt/fieldwork is never traversed.
    state.mkdir(mode=0o700)
    safe_dir(state)
    lock_file = state / "activation.lock"
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic(state / "previous-fieldwork_mcp.py", main, new=True)
        atomic(state / "previous-sandbox_command.py", sandbox, new=True)
        receipt = {
            "status": "BACKUP_READY",
            "immutable_commit": commit,
            "old_mcp_sha256": MAIN_PIN,
            "old_sandbox_sha256": RUNNER_PIN,
            "new_mcp_sha256": digest_main,
            "new_sandbox_sha256": digest_sandbox,
            "production_modified": False,
            "new_tunnel_created": False,
        }
        record(state, receipt, new=True)
        try:
            atomic(root / "mcp_self_diagnostics.py",
                   sources["mcp_self_diagnostics.py"], new=True)
            atomic(root / "sandbox_command.py", candidate["sandbox_bytes"])
            atomic(root / "fieldwork_mcp.py", candidate["mcp_bytes"])
            receipt["status"] = "FILES_WRITTEN"
            record(state, receipt)
            require(systemd("restart"), "TUNNEL_RESTART_FAILED")
            passed = False
            for _ in range(8):
                if systemd("is-active") and ready():
                    passed = True
                    break
                time.sleep(2)
            require(passed, "TUNNEL_NOT_READY_ROLLBACK_REQUIRED")
            receipt["status"] = "M12_READY_TOOL_DISCOVERY_PENDING"
            record(state, receipt)
            print("M12_ACTIVATED_READYZ_PASS_DISCOVERY_PENDING", flush=True)
            return receipt
        except Exception:
            print("M12_AUTOMATIC_ROLLBACK_BEGIN", flush=True)
            restore(root, state, receipt)
            print("M12_ROLLED_BACK", flush=True)
            raise
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    try:
        result = execute_once(args.commit, confirm=args.activate)
    except (ActivationStop, OSError, ValueError, EOFError) as exc:
        # The exact safe rejection code is needed to diagnose a Pi-only
        # source/AST drift without asking for raw source or credentials.
        # Suppress arbitrary exception details and paths.
        message = str(exc)
        reason = (message if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", message)
                  else type(exc).__name__)
        print("M12_STOP=" + reason, flush=True)
        return 2
    return 0 if result["status"] == "M12_READY_TOOL_DISCOVERY_PENDING" else 3


if __name__ == "__main__":
    raise SystemExit(main())
