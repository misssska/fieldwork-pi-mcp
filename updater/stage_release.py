"""Fail-closed GitHub release downloader for FieldWork Pi MCP.

Stages files only. It cannot install, restart services, run downloaded code,
or access /opt/fieldwork. Requires a pinned Git commit and manifest SHA256.
Python 3.11+; no third-party dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.request

OWNER = "misssska"
REPO = "fieldwork-pi-mcp"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_PATH = re.compile(
    r"(?:fieldwork_mcp|stage_async|stage_manager)\.py"
    r"|tests/test_[a-z0-9_]+\.py"
)
MAX_MANIFEST = 65536
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 12 * 1024 * 1024


class StageError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StageError(message)


def fetch(commit: str, path: str, limit: int) -> bytes:
    # No redirects to arbitrary domains; no mutable branch/tag references.
    url = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{commit}/{path}"
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "fieldwork-pi-mcp-stager/1"})
    with opener.open(req, timeout=20) as response:
        require(response.status == 200, "HTTP_STATUS_NOT_OK")
        data = response.read(limit + 1)
    require(len(data) <= limit, "DOWNLOAD_TOO_LARGE")
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StageError("REDIRECT_DENIED")


def parse_manifest(raw: bytes) -> list[tuple[str, str]]:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise StageError("INVALID_MANIFEST_JSON") from exc
    require(isinstance(obj, dict) and set(obj) == {"schema", "files"}, "INVALID_MANIFEST_KEYS")
    require(type(obj["schema"]) is int and obj["schema"] == 1, "UNSUPPORTED_SCHEMA")
    entries = obj["files"]
    require(isinstance(entries, list) and 1 <= len(entries) <= 30, "INVALID_FILE_COUNT")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in entries:
        require(isinstance(item, dict) and set(item) == {"path", "sha256"}, "INVALID_FILE_ENTRY")
        path, digest = item["path"], item["sha256"]
        require(isinstance(path, str) and SAFE_PATH.fullmatch(path) is not None, "UNSAFE_FILE_PATH")
        require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None, "INVALID_FILE_HASH")
        require(path not in seen, "DUPLICATE_FILE_PATH")
        seen.add(path)
        out.append((path, digest))
    require(any(path == "fieldwork_mcp.py" for path, _ in out), "MAIN_FILE_REQUIRED")
    return out


def safe_parent(path: Path) -> None:
    # Fail if any existing component of the destination is a symlink.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise StageError("SYMLINK_PATH_DENIED")


def stage(commit: str, manifest_sha256: str, state: Path) -> Path:
    require(HEX40.fullmatch(commit) is not None, "COMMIT_SHA_REQUIRED")
    require(HEX64.fullmatch(manifest_sha256) is not None, "MANIFEST_SHA_REQUIRED")
    require(os.geteuid() != 0, "ROOT_NOT_ALLOWED")
    state = state.expanduser().absolute()
    safe_parent(state)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(state.is_dir() and state.stat().st_uid == os.getuid(), "STATE_NOT_OWNED")
    require((state.stat().st_mode & 0o077) == 0, "STATE_PERMISSIONS_TOO_OPEN")
    manifest = fetch(commit, "release/manifest.json", MAX_MANIFEST)
    require(sha256(manifest) == manifest_sha256, "MANIFEST_HASH_MISMATCH")
    files = parse_manifest(manifest)
    total = 0
    blobs: list[tuple[str, bytes]] = []
    for path, digest in files:
        data = fetch(commit, "release/" + path, MAX_FILE)
        total += len(data)
        require(total <= MAX_TOTAL, "RELEASE_TOO_LARGE")
        require(sha256(data) == digest, "FILE_HASH_MISMATCH:" + path)
        if path.endswith(".py"):
            import ast
            try:
                ast.parse(data.decode("utf-8"), filename=path)
            except (SyntaxError, UnicodeError) as exc:
                raise StageError("INVALID_PYTHON:" + path) from exc
        blobs.append((path, data))
    dest = state / (commit + "-" + manifest_sha256[:12])
    require(not dest.exists() and not dest.is_symlink(), "STAGE_ALREADY_EXISTS")
    temp = Path(tempfile.mkdtemp(prefix=".stage-", dir=state))
    try:
        for path, data in blobs:
            output = temp / path
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            output.chmod(0o600)
        with (temp / "receipt.json").open("x", encoding="utf-8") as handle:
            json.dump({"commit": commit, "manifest_sha256": manifest_sha256,
                       "files": [p for p, _ in blobs], "status": "STAGED_NOT_INSTALLED"}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        (temp / "receipt.json").chmod(0o600)
        os.replace(temp, dest)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="Immutable 40-character Git commit SHA")
    parser.add_argument("--manifest-sha256", required=True, help="Pinned manifest SHA256")
    parser.add_argument("--state", type=Path,
                        default=Path.home() / ".local/state/fieldwork-pi-mcp/update-staging")
    args = parser.parse_args()
    try:
        destination = stage(args.commit, args.manifest_sha256, args.state)
    except (StageError, OSError, urllib.error.URLError) as exc:
        print("STAGING_FAILED=" + str(exc), file=sys.stderr)
        return 1
    print("STAGING_PASS=" + str(destination))
    print("INSTALLATION_PERFORMED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
