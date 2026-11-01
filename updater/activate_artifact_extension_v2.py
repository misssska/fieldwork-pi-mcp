"""Locally approved *second* FieldWork MCP extension, with exact rollback.

ONLY adds static canary ZIP qualification and verified-artifact retirement to
the four already functioning transport tools. NEVER stages, executes code,
starts Docker, deploys production, creates a new tunnel or changes stage data.

Run from an independent local operator shell; never run inside MCP process.
Before any write: installed source SHA, installed inbox SHA and adapter bytes
must match the exact previous release; new modules are pinned to ONE immutable
reviewed Git commit, compile/AST-checked. Local typed consent + sudo permission
precede all changes. Interrupted states fail closed and require recovery.
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

REPO = "misssska/fieldwork-pi-mcp"
PREVIOUS_COMMIT = "dde90680881d2eca4380bfb6c3a53383912e38a6"
SOURCE_PREVIOUS = "2c03f152c26052dcad5dbadf97f809f3f924cddb702b2a92b51a180f29e268b6"
MCP_REL = Path(".local/share/fieldwork-pi-mcp/v0.6.1")
STATE_REL = Path(".local/state/fieldwork-pi-mcp/one-time-artifact-extension-v2")
ADDED = ("canary_archive_qualifier.py", "canary_archive_adapter.py",
         "artifact_retention.py", "artifact_retention_adapter.py")
UPDATED = "artifact_inbox.py"
KEEP = "artifact_inbox_adapter.py"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
LIMIT = 1_000_000
UNIT = "fieldwork-pi-tunnel.service"

IMPORT_OLD = "import artifact_inbox_adapter\n"
IMPORT_NEW = IMPORT_OLD + ("import canary_archive_qualifier\n"
                            "import canary_archive_adapter\n"
                            "import artifact_retention\n"
                            "import artifact_retention_adapter\n")
TOOLS_OLD = '''    ("fieldwork_artifact_finalize", "Verify complete artifact SHA256; never deploy", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, artifact_inbox_adapter.finalize),
'''
TOOLS_NEW = TOOLS_OLD + '''    ("fieldwork_artifact_qualify", "Statically validate verified source ZIP manifest, allowlisted paths and SHA256; never execute", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    }, canary_archive_adapter.qualify),
    ("fieldwork_artifact_retire", "Explicitly release one SHA256-verified inert upload, preserving replay tombstone; never execute", {
        "transfer_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "approval": {"type": "string", "enum": ["RETIRE_VERIFIED_CANARY"]}
    }, artifact_retention_adapter.retire),
'''
ANNOTATION_OLD = '"fieldwork_stage_prepare", "fieldwork_stage_full_test", "fieldwork_stage_start", "fieldwork_artifact_begin", "fieldwork_artifact_append", "fieldwork_artifact_status", "fieldwork_artifact_finalize"'
ANNOTATION_NEW = ANNOTATION_OLD + ', "fieldwork_artifact_qualify", "fieldwork_artifact_retire"'


class Stop(Exception):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Stop(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def owned(path: Path, *, maximum: int = LIMIT) -> bytes:
    require(path.is_file() and not path.is_symlink(), "FILE_NOT_REGULAR")
    st = path.stat()
    require(st.st_uid == os.geteuid() and not (stat.S_IMODE(st.st_mode) & 0o077),
            "FILE_OWNER_OR_MODE_DENIED")
    require(0 < st.st_size <= maximum, "FILE_SIZE_DENIED")
    return path.read_bytes()


def owner_dir(path: Path, *, private: bool = False, create: bool = False) -> None:
    require(not path.is_symlink(), "DIRECTORY_SYMLINK_DENIED")
    if create and not path.exists():
        path.mkdir(mode=0o700)
    require(path.is_dir(), "DIRECTORY_MISSING")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & (0o077 if private else 0o022)),
            "DIRECTORY_OWNER_OR_PERMISSIONS")


def paths(home: Path) -> tuple[Path, Path]:
    require(os.geteuid() != 0 and home.is_absolute() and home == Path.home() and
            not home.is_symlink(), "ROOT_OR_HOME_DENIED")
    owner_dir(home)
    root = home
    for part in MCP_REL.parts:
        root = root / part
        owner_dir(root)
    state = home
    for part in STATE_REL.parts:
        state = state / part
        owner_dir(state, create=True)
    owner_dir(state, private=True)
    return root, state


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    require(not path.is_symlink(), "TARGET_SYMLINK_DENIED")
    require(not exclusive or not path.exists(), "TARGET_COLLISION_DENIED")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".fieldwork-v2-")
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        temp.chmod(0o600)
        if exclusive:
            os.link(temp, path, follow_symlinks=False)
            temp.unlink()
        else:
            os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise Stop("DOWNLOAD_REDIRECT_DENIED")


def download(commit: str, name: str) -> bytes:
    require(HEX40.fullmatch(commit) is not None and name in
            (UPDATED, KEEP, *ADDED), "DOWNLOAD_SOURCE_DENIED")
    url = f"https://raw.githubusercontent.com/{REPO}/{commit}/updater/{name}"
    client = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "fieldwork-local-v2/1"})
    with client.open(req, timeout=30) as response:
        require(response.status == 200, "DOWNLOAD_HTTP_STATUS")
        data = response.read(LIMIT + 1)
    require(0 < len(data) <= LIMIT, "DOWNLOAD_TOO_LARGE")
    try:
        ast.parse(data.decode("utf-8"), filename=name)
    except (UnicodeError, SyntaxError) as exc:
        raise Stop("DOWNLOAD_SYNTAX_INVALID:" + name) from exc
    return data


def transformed(current: bytes) -> bytes:
    require(sha(current) == SOURCE_PREVIOUS, "ACTIVE_MCP_SOURCE_SHA_DRIFT")
    try:
        source = current.decode("utf-8")
        ast.parse(source)
    except (UnicodeError, SyntaxError) as exc:
        raise Stop("MCP_SOURCE_UNREADABLE") from exc
    require("fieldwork_artifact_qualify" not in source and
            "fieldwork_artifact_retire" not in source and
            "import canary_archive_adapter" not in source,
            "ALREADY_UPDATED_OR_PARTIAL")
    for before, after in ((IMPORT_OLD, IMPORT_NEW),
                          (TOOLS_OLD, TOOLS_NEW),
                          (ANNOTATION_OLD, ANNOTATION_NEW)):
        require(source.count(before) == 1, "MCP_INTEGRATION_ANCHOR_DRIFT")
        source = source.replace(before, after, 1)
    tree = ast.parse(source)
    names = [node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.startswith("fieldwork_artifact_")]
    require(set(names) == {"fieldwork_artifact_begin", "fieldwork_artifact_append",
                           "fieldwork_artifact_status", "fieldwork_artifact_finalize",
                           "fieldwork_artifact_qualify", "fieldwork_artifact_retire"},
            "MCP_TOOLS_NOT_EXACT")
    return source.encode("utf-8")


def unit(action: str) -> bool:
    require(action in ("is-active", "restart"), "UNAUTHORIZED_SYSTEMD_ACTION")
    command = (["systemctl", "is-active", UNIT] if action == "is-active"
               else ["sudo", "-n", "systemctl", "restart", UNIT])
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=35, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sudo_ready() -> bool:
    try:
        return subprocess.run(["sudo", "-v"], timeout=70,
                              check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def local_ready() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/readyz",
                                    timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def lock(state: Path) -> int:
    target = state / "activation.lock"
    require(not target.is_symlink(), "LOCK_SYMLINK_DENIED")
    fd = os.open(target, os.O_RDWR | os.O_CREAT |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    st = os.fstat(fd)
    require(st.st_uid == os.geteuid() and
            stat.S_IMODE(st.st_mode) & 0o077 == 0, "LOCK_PERMISSIONS_DENIED")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def candidate(commit: str, root: Path) -> tuple[bytes, dict[str, bytes], bytes]:
    require(unit("is-active"), "TUNNEL_NOT_RUNNING")
    original_mcp = owned(root / "fieldwork_mcp.py")
    newer_mcp = transformed(original_mcp)
    old_inbox = download(PREVIOUS_COMMIT, UPDATED)
    old_adapter = download(PREVIOUS_COMMIT, KEEP)
    require(owned(root / UPDATED) == old_inbox, "ACTIVE_INBOX_BYTES_DRIFT")
    require(owned(root / KEEP) == old_adapter, "ACTIVE_ADAPTER_BYTES_DRIFT")
    require(all(not (root / name).exists() and not (root / name).is_symlink()
                for name in ADDED), "V2_MODULE_ALREADY_EXISTS")
    new_modules = {name: download(commit, name) for name in ADDED}
    new_modules[UPDATED] = download(commit, UPDATED)
    require(sha(new_modules[UPDATED]) != sha(old_inbox), "NO_NEW_INBOX_REVISION")
    return newer_mcp, new_modules, old_inbox


def receipt_file(state: Path) -> Path:
    return state / "receipt.json"


def write_receipt(state: Path, record: dict, *, exclusive: bool = False) -> None:
    atomic_write(receipt_file(state),
                 (json.dumps(record, sort_keys=True) + "\n").encode(),
                 exclusive=exclusive)


def restore(root: Path, state: Path) -> None:
    record = json.loads(owned(receipt_file(state), maximum=8192))
    require(record.get("status") in {"BACKUP_READY", "FILES_WRITTEN",
                                     "TUNNEL_READY_DISCOVERY_PENDING",
                                     "ROLLED_BACK"}, "ROLLBACK_STATE_UNKNOWN")
    mcp = owned(state / "old-fieldwork_mcp.py")
    inbox = owned(state / "old-artifact_inbox.py")
    require(sha(mcp) == SOURCE_PREVIOUS and
            sha(inbox) == record["old_inbox_sha256"], "BACKUP_HASH_DENIED")
    require(sha(owned(root / "fieldwork_mcp.py")) in {
        SOURCE_PREVIOUS, record["new_mcp_sha256"]},
        "ACTIVE_MCP_CHANGED_NO_OVERWRITE")
    require(sha(owned(root / UPDATED)) in {
        record["old_inbox_sha256"], record["new_inbox_sha256"]},
        "ACTIVE_INBOX_CHANGED_NO_OVERWRITE")
    for name in ADDED:
        target = root / name
        if target.exists() or target.is_symlink():
            require(sha(owned(target)) == record["module_sha256"][name],
                    "UNEXPECTED_MODULE_CHANGE:" + name)
    atomic_write(root / "fieldwork_mcp.py", mcp)
    atomic_write(root / UPDATED, inbox)
    for name in ADDED:
        target = root / name
        if target.exists():
            target.unlink()
    fsync_dir(root)
    record["status"] = "ROLLED_BACK"
    write_receipt(state, record)
    require(unit("restart"), "ROLLBACK_RESTART_FAILED")
    print("SOURCE_ROLLBACK_DONE_DISCOVERY_PENDING", flush=True)


def activate(commit: str, root: Path, state: Path) -> None:
    require(not receipt_file(state).exists(), "PREVIOUS_ACTIVATION_STATE_PRESENT")
    result, modules, old_inbox = candidate(commit, root)
    print("V2_PREFLIGHT_PASS", flush=True)
    print("CANDIDATE_SOURCE_SHA256=" + sha(result), flush=True)
    print("MODULE_COUNT=" + str(len(modules)), flush=True)
    print("SCOPE=MCP_SOURCE_AND_INERT_ARTIFACT_MODULES_ONLY", flush=True)
    confirm = input("Helyi jóváhagyás (AKTIVALOM_V2): ").strip()
    require(confirm == "AKTIVALOM_V2", "LOCAL_APPROVAL_REQUIRED")
    require(sudo_ready(), "SUDO_NOT_APPROVED_BEFORE_FILES")
    require(unit("is-active"), "TUNNEL_NOT_ACTIVE_AFTER_APPROVAL")
    require(sha(owned(root / "fieldwork_mcp.py")) == SOURCE_PREVIOUS,
            "SOURCE_CHANGED_AFTER_PREFLIGHT")
    require(sha(owned(root / UPDATED)) == sha(old_inbox),
            "INBOX_CHANGED_AFTER_PREFLIGHT")

    atomic_write(state / "old-fieldwork_mcp.py",
                 owned(root / "fieldwork_mcp.py"), exclusive=True)
    atomic_write(state / "old-artifact_inbox.py",
                 owned(root / UPDATED), exclusive=True)
    record = {"schema": 1, "status": "BACKUP_READY", "commit": commit,
              "previous_source_sha256": SOURCE_PREVIOUS,
              "new_mcp_sha256": sha(result),
              "old_inbox_sha256": sha(old_inbox),
              "new_inbox_sha256": sha(modules[UPDATED]),
              "module_sha256": {name: sha(modules[name]) for name in ADDED},
              "production_modified": False}
    write_receipt(state, record, exclusive=True)
    try:
        for name in ADDED:
            atomic_write(root / name, modules[name], exclusive=True)
        atomic_write(root / UPDATED, modules[UPDATED])
        atomic_write(root / "fieldwork_mcp.py", result)
        record["status"] = "FILES_WRITTEN"
        write_receipt(state, record)
        require(unit("restart"), "TUNNEL_RESTART_FAILED")
        for _ in range(12):
            if unit("is-active") and local_ready():
                record["status"] = "TUNNEL_READY_DISCOVERY_PENDING"
                write_receipt(state, record)
                print("V2_TUNNEL_READY_DISCOVERY_PENDING", flush=True)
                print("VERIFY_NEW_MCP_TOOL_DISCOVERY_FROM_CHATGPT", flush=True)
                return
            time.sleep(2)
        raise Stop("TUNNEL_HEALTH_FAILED")
    except Exception:
        print("V2_ROLLBACK_BEGIN", flush=True)
        restore(root, state)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        require(HEX40.fullmatch(args.commit) is not None, "IMMUTABLE_COMMIT_REQUIRED")
        root, state = paths(Path.home())
        fd = lock(state)
        try:
            if args.rollback:
                require(sudo_ready(), "SUDO_REQUIRED_FOR_ROLLBACK")
                restore(root, state)
            elif args.activate:
                activate(args.commit, root, state)
            else:
                after, modules, old = candidate(args.commit, root)
                print(json.dumps({
                    "status": "V2_PREFLIGHT_PASS_NOT_INSTALLED",
                    "active_mcp_sha256": SOURCE_PREVIOUS,
                    "candidate_mcp_sha256": sha(after),
                    "old_inbox_sha256": sha(old),
                    "modules": {name: sha(data) for name, data in modules.items()},
                    "approval_required": True,
                    "production_modified": False
                }, sort_keys=True))
            return 0
        finally:
            os.close(fd)
    except (Stop, OSError, ValueError, urllib.error.URLError,
            BlockingIOError, EOFError) as exc:
        print("V2_STOP=" + type(exc).__name__ + ":" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
