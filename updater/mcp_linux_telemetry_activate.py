"""M13 one-time Linux telemetry MCP activation with strict local approval.

Exact immutable Git commit + content SHA256 for all inputs; exact installed
M12 main SHA256 and two unique code anchors. Only admin-owned MCP source
in ~/.local/share/fieldwork-pi-mcp/v0.6.1 is changed. The fixed existing
fieldwork-pi-tunnel.service is the only restarted systemd unit.

No production path, Docker mutation, arbitrary commands, new tunnels, raw
host shell, or remote activation. A local operator must explicitly confirm.
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

PROJECT = "misssska/fieldwork-pi-mcp"
UNIT = "fieldwork-pi-tunnel.service"
INSTALL = Path(".local/share/fieldwork-pi-mcp/v0.6.1")
STATE = Path(".local/state/fieldwork-pi-mcp")
ATTEMPT = "m13-linux-telemetry-once"
M12_MAIN_SHA256 = "ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532"
CONSENT = "ENGEDÉLYEZEM_M13"
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
MODULE_PINS = {
    "linux_telemetry.py":
        "40de0c1807be2f25052b6433130c412dfafeffc83bbe5cd2d935c3e25d73652f",
    "mcp_linux_telemetry.py":
        "c7539b8abb0c0a9530441fe3c8f885dde406d21c764694c1d204362752dcff6b",
    "mcp_linux_telemetry_overlay.py":
        "8cc573ce7707e7e70744de94861ad95f5ac7e08f99203ea97020f4d7bdf240e7",
}
MAX_MODULE = 200_000


class M13Stop(RuntimeError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise M13Stop(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_dir(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink(), "M13_DIRECTORY_UNSAFE")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & 0o022),
            "M13_DIRECTORY_PERMISSIONS")


def owned(path: Path, max_size: int = 1_000_000) -> bytes:
    require(path.is_file() and not path.is_symlink(),
            "M13_SOURCE_MISSING_OR_SYMLINK")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & 0o077) and
            0 < st.st_size <= max_size, "M13_SOURCE_MODE_OR_SIZE")
    content = path.read_bytes()
    require(len(content) == st.st_size, "M13_SOURCE_READ_RACE")
    return content


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path: Path, data: bytes, *, create: bool = False) -> None:
    require(not path.is_symlink() and
            (not create or not path.exists()), "M13_TARGET_COLLISION")
    fd, tmp_name = tempfile.mkstemp(prefix=".m13-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        tmp.chmod(0o600)
        if create:
            os.link(tmp, path, follow_symlinks=False)
            tmp.unlink()
        else:
            os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise M13Stop("M13_DOWNLOAD_REDIRECT_DENIED")


def download(commit: str, name: str) -> bytes:
    require(type(commit) is str and COMMIT_RE.fullmatch(commit) is not None
            and name in MODULE_PINS, "M13_DOWNLOAD_TARGET_DENIED")
    url = ("https://raw.githubusercontent.com/" + PROJECT + "/" + commit
           + "/updater/" + name)
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={
        "User-Agent": "fieldwork-m13-exact-once/1"
    })
    try:
        with opener.open(req, timeout=20) as response:
            require(response.status == 200, "M13_HTTP_NOT_OK")
            data = response.read(MAX_MODULE + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise M13Stop("M13_PINNED_DOWNLOAD_FAILED") from exc
    require(0 < len(data) <= MAX_MODULE and
            sha(data) == MODULE_PINS[name], "M13_MODULE_SHA256_MISMATCH")
    try:
        ast.parse(data, filename=name)
        compile(data, name, "exec")
    except (SyntaxError, UnicodeError, ValueError) as exc:
        raise M13Stop("M13_MODULE_COMPILE_DENIED") from exc
    return data


def load_exact_overlay(source: bytes):
    require(sha(source) == MODULE_PINS["mcp_linux_telemetry_overlay.py"],
            "M13_OVERLAY_SOURCE_DRIFT")
    module = types.ModuleType("mcp_linux_telemetry_overlay")
    exec(compile(source, "m13-exact-overlay.py", "exec"), module.__dict__)
    return module


def service(action: str) -> bool:
    require(action in {"is-active", "restart"}, "M13_SERVICE_ACTION_DENIED")
    argv = (
        ["systemctl", "is-active", UNIT] if action == "is-active"
        else ["sudo", "-n", "systemctl", "restart", UNIT]
    )
    try:
        process = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=40, check=False,
            shell=False,
        )
        return process.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ready() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/readyz",
                                    timeout=3) as answer:
            return answer.status == 200
    except (OSError, urllib.error.URLError):
        return False


def receipt(state: Path, data: dict, *, create: bool = False) -> None:
    atomic(state / "receipt.json",
           (json.dumps(data, sort_keys=True) + "\n").encode(), create=create)


def rollback(install: Path, state: Path, data: dict) -> None:
    previous = owned(state / "previous-fieldwork_mcp.py")
    require(sha(previous) == M12_MAIN_SHA256, "M13_BACKUP_SHA256_DRIFT")
    active = owned(install / "fieldwork_mcp.py")
    require(sha(active) in {M12_MAIN_SHA256, data["new_mcp_sha256"]},
            "M13_ROLLBACK_SOURCE_CHANGED")
    for module in ("linux_telemetry.py", "mcp_linux_telemetry.py"):
        path = install / module
        if path.exists() or path.is_symlink():
            require(sha(owned(path)) == MODULE_PINS[module],
                    "M13_ROLLBACK_MODULE_CHANGED")
    atomic(install / "fieldwork_mcp.py", previous)
    for module in ("linux_telemetry.py", "mcp_linux_telemetry.py"):
        path = install / module
        if path.exists():
            path.unlink()
    sync_dir(install)
    data["status"] = "M13_ROLLED_BACK"
    receipt(state, data)
    require(service("restart"), "M13_ROLLBACK_SERVICE_FAILED")


def activate_once(commit: str, *, approved: bool) -> dict:
    require(os.geteuid() != 0, "M13_ROOT_DENIED")
    require(type(commit) is str and COMMIT_RE.fullmatch(commit) is not None,
            "M13_IMMUTABLE_COMMIT_REQUIRED")
    require(approved is True, "M13_ACTIVATION_FLAG_REQUIRED")
    home = Path.home()
    safe_dir(home)
    install = home
    for part in INSTALL.parts:
        install = install / part
        safe_dir(install)
    state_root = home
    for part in STATE.parts:
        state_root = state_root / part
        safe_dir(state_root)
    state = state_root / ATTEMPT
    require(not state.exists() and not state.is_symlink(),
            "M13_PREVIOUS_ATTEMPT_EXISTS")
    require(service("is-active"), "M13_EXISTING_TUNNEL_NOT_ACTIVE")
    current = owned(install / "fieldwork_mcp.py")
    require(sha(current) == M12_MAIN_SHA256,
            "M13_INSTALLED_MAIN_SHA256_NOT_REVIEWED")
    for file in ("linux_telemetry.py", "mcp_linux_telemetry.py"):
        path = install / file
        require(not path.exists() and not path.is_symlink(),
                "M13_EXTENSION_FILE_ALREADY_EXISTS")

    sources = {k: download(commit, k) for k in MODULE_PINS}
    overlay = load_exact_overlay(sources["mcp_linux_telemetry_overlay.py"])
    candidate = overlay.build(current)
    require(candidate["status"] == "M13_OFFLINE_CANDIDATE_ONLY"
            and candidate["activation_authorized"] is False,
            "M13_CANDIDATE_POLICY_DENIED")
    new_main = candidate["candidate_bytes"]
    new_sha = candidate["new_sha256"]
    ast.parse(new_main)
    compile(new_main, "m13-installed-main-candidate.py", "exec")

    print("M13_PREFLIGHT_PASS", flush=True)
    print("OLD_MAIN_SHA256=" + M12_MAIN_SHA256, flush=True)
    print("NEW_MAIN_SHA256=" + new_sha, flush=True)
    print("CHANGED=ONE_MCP_MAIN_AND_TWO_READONLY_MODULES", flush=True)
    print("PRODUCTION_AND_DOCKER_UNTOUCHED", flush=True)
    answer = input("Egyszeri helyi jóváhagyás (" + CONSENT + "): ").strip()
    require(answer == CONSENT, "M13_LOCAL_APPROVAL_DENIED")
    try:
        sudo = subprocess.run(["sudo", "-v"], timeout=80,
                              check=False, shell=False)
        require(sudo.returncode == 0, "M13_SUDO_NOT_APPROVED")
    except (OSError, subprocess.SubprocessError) as exc:
        raise M13Stop("M13_SUDO_NOT_APPROVED") from exc
    require(service("is-active"), "M13_TUNNEL_CHANGED_BEFORE_WRITE")
    require(sha(owned(install / "fieldwork_mcp.py")) == M12_MAIN_SHA256,
            "M13_INSTALLED_MAIN_CHANGED_BEFORE_WRITE")

    state.mkdir(mode=0o700)
    safe_dir(state)
    lock = os.open(state / "activation.lock",
                   os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                   0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic(state / "previous-fieldwork_mcp.py", current, create=True)
        data = {
            "status": "M13_BACKUP_READY",
            "immutable_commit": commit,
            "old_mcp_sha256": M12_MAIN_SHA256,
            "new_mcp_sha256": new_sha,
            "production_modified": False,
            "docker_modified": False,
            "new_tunnel_created": False,
        }
        receipt(state, data, create=True)
        try:
            atomic(install / "linux_telemetry.py",
                   sources["linux_telemetry.py"], create=True)
            atomic(install / "mcp_linux_telemetry.py",
                   sources["mcp_linux_telemetry.py"], create=True)
            atomic(install / "fieldwork_mcp.py", new_main)
            data["status"] = "M13_FILES_WRITTEN"
            receipt(state, data)
            require(service("restart"), "M13_TUNNEL_RESTART_FAILED")
            healthy = False
            for _ in range(8):
                if service("is-active") and ready():
                    healthy = True
                    break
                time.sleep(2)
            require(healthy, "M13_TUNNEL_NOT_READY")
            data["status"] = "M13_LOCAL_READY_DISCOVERY_PENDING"
            receipt(state, data)
            print("M13_LOCAL_READY_DISCOVERY_PENDING", flush=True)
            return data
        except Exception:
            print("M13_ROLLBACK_BEGIN", flush=True)
            rollback(install, state, data)
            print("M13_ROLLBACK_DONE", flush=True)
            raise
    finally:
        os.close(lock)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    try:
        data = activate_once(args.commit, approved=args.activate)
    except (M13Stop, OSError, ValueError, EOFError) as exc:
        message = str(exc)
        code = message if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", message) else type(exc).__name__
        print("M13_STOP=" + code, flush=True)
        return 2
    return 0 if data["status"] == "M13_LOCAL_READY_DISCOVERY_PENDING" else 3


if __name__ == "__main__":
    raise SystemExit(main())
