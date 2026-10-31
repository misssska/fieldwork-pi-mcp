"""Strict, read-only qualification of one verified FieldWork canary overlay.

The existing MCP inbox stores bytes but never executes them. This module
validates a bounded ZIP as untrusted *source data* only. It never extracts,
runs code, patches a checkout, starts Docker or modifies production.

Archive contract:
  MANIFEST.json plus exactly the listed, non-executable source files.
  Manifest: schema, kind, base_commit, files[{path,size,sha256}].
An independent isolated stage manager MUST validate the base commit, review
authorization, migrations and code execution constraints before using files.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import stat
import zipfile

if __package__:
    from . import artifact_inbox as inbox
else:
    import artifact_inbox as inbox

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_MANIFEST = 32 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 24 * 1024 * 1024
MAX_FILES = 64
MAX_RATIO = 400
KIND = "fieldwork-canary-overlay-v1"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,80}\Z")
ALLOWED_SUFFIXES = (".ts", ".tsx", ".css", ".py", ".svg", ".md")


class QualificationDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise QualificationDenied(reason)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        require(key not in obj, "DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeError, ValueError) as exc:
        raise QualificationDenied("MANIFEST_JSON_INVALID") from exc


def allowed_path(path: str) -> bool:
    if type(path) is not str or len(path) > 200 or "\\" in path or "\x00" in path:
        return False
    parts = path.split("/")
    if not 3 <= len(parts) <= 9 or any(
        SEGMENT.fullmatch(x) is None or x in (".", "..") or x.startswith(".")
        for x in parts
    ):
        return False
    if parts[:2] == ["frontend", "src"]:
        return path.endswith((".ts", ".tsx", ".css", ".svg"))
    if parts[:2] == ["server", "app"]:
        return path.endswith(".py")
    if parts[:2] == ["server", "tests"]:
        return parts[-1].startswith("test_") and path.endswith(".py")
    return False


def parse_manifest(raw: bytes) -> tuple[str, list[dict]]:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST,
            "MANIFEST_SIZE_DENIED")
    obj = _json(raw)
    require(type(obj) is dict and set(obj) == {
        "schema", "kind", "base_commit", "files"
    }, "MANIFEST_SCHEMA_DENIED")
    require(type(obj["schema"]) is int and obj["schema"] == 1 and
            obj["kind"] == KIND, "MANIFEST_VERSION_DENIED")
    base = obj["base_commit"]
    require(type(base) is str and HEX40.fullmatch(base) is not None,
            "BASE_COMMIT_INVALID")
    entries = obj["files"]
    require(type(entries) is list and 1 <= len(entries) <= MAX_FILES,
            "MANIFEST_FILE_COUNT_DENIED")
    known = set()
    total = 0
    result = []
    for item in entries:
        require(type(item) is dict and set(item) == {"path", "size", "sha256", "previous_sha256"},
                "MANIFEST_ENTRY_SCHEMA_DENIED")
        path, size, hashed, previous = (item["path"], item["size"],
                                        item["sha256"], item["previous_sha256"])
        require(allowed_path(path), "SOURCE_PATH_DENIED")
        require(path not in known, "DUPLICATE_MANIFEST_PATH")
        known.add(path)
        require(previous is None or (type(previous) is str and
                HEX64.fullmatch(previous) is not None), "PREVIOUS_SHA_INVALID")
        require(type(size) is int and 0 < size <= MAX_FILE, "SOURCE_SIZE_DENIED")
        require(type(hashed) is str and HEX64.fullmatch(hashed) is not None,
                "SOURCE_HASH_INVALID")
        total += size
        require(total <= MAX_TOTAL, "TOTAL_SOURCE_SIZE_DENIED")
        result.append({"path": path, "size": size, "sha256": hashed,
                       "previous_sha256": previous})
    require([e["path"] for e in result] == sorted(known),
            "MANIFEST_ORDER_NOT_CANONICAL")
    return base, result


def _read_bounded(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Limit bytes *during* decompression; do not trust ZIP size metadata."""
    require(info.file_size <= limit, "ARCHIVE_MEMBER_SIZE_DENIED")
    try:
        with archive.open(info, "r") as member:
            data = member.read(limit + 1)
            require(len(data) <= limit, "ARCHIVE_EXPANSION_DENIED")
            require(member.read(1) == b"", "ARCHIVE_EXPANSION_DENIED")
    except (OSError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
        raise QualificationDenied("ARCHIVE_MEMBER_CORRUPTED") from exc
    require(len(data) == info.file_size, "ARCHIVE_MEMBER_SIZE_MISMATCH")
    return data


def qualify_bytes(raw: bytes, expected_archive_sha256: str) -> dict:
    """Static qualification ONLY, no extraction, importing, execution or I/O."""
    require(type(expected_archive_sha256) is str and
            HEX64.fullmatch(expected_archive_sha256) is not None,
            "ARCHIVE_PIN_INVALID")
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE,
            "ARCHIVE_SIZE_DENIED")
    require(digest(raw) == expected_archive_sha256, "ARCHIVE_HASH_MISMATCH")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r", allowZip64=False)
    except (ValueError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise QualificationDenied("ARCHIVE_INVALID") from exc
    with archive:
        infos = archive.infolist()
        require(2 <= len(infos) <= MAX_FILES + 1, "ARCHIVE_MEMBER_COUNT_DENIED")
        names = [i.filename for i in infos]
        require(len(names) == len(set(names)), "DUPLICATE_ARCHIVE_MEMBER")
        require("MANIFEST.json" in names, "MANIFEST_MISSING")
        for info in infos:
            name = info.filename
            require(name == "MANIFEST.json" or allowed_path(name),
                    "UNAPPROVED_ARCHIVE_MEMBER")
            require(not info.is_dir() and not info.flag_bits & 0x1,
                    "ARCHIVE_MEMBER_UNSAFE")
            mode = (info.external_attr >> 16) & 0xFFFF
            require(not mode or stat.S_IFMT(mode) in (0, stat.S_IFREG),
                    "ARCHIVE_SPECIAL_FILE_DENIED")
            require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    "ARCHIVE_COMPRESSION_DENIED")
            limit = MAX_MANIFEST if name == "MANIFEST.json" else MAX_FILE
            require(0 < info.file_size <= limit, "ARCHIVE_MEMBER_SIZE_DENIED")
            require(info.file_size <= max(1, info.compress_size) * MAX_RATIO,
                    "ARCHIVE_COMPRESSION_RATIO_DENIED")
        manifest_info = archive.getinfo("MANIFEST.json")
        manifest_data = _read_bounded(archive, manifest_info, MAX_MANIFEST)
        base, entries = parse_manifest(manifest_data)
        declared = {e["path"] for e in entries} | {"MANIFEST.json"}
        require(set(names) == declared, "ARCHIVE_MANIFEST_SET_MISMATCH")
        total = 0
        for entry in entries:
            info = archive.getinfo(entry["path"])
            require(info.file_size == entry["size"], "SOURCE_SIZE_MISMATCH")
            total += info.file_size
            require(total <= MAX_TOTAL, "ARCHIVE_TOTAL_TOO_LARGE")
            data = _read_bounded(archive, info, MAX_FILE)
            require(len(data) == entry["size"], "SOURCE_SIZE_MISMATCH")
            require(digest(data) == entry["sha256"], "SOURCE_HASH_MISMATCH")
            # All code is UTF-8 source; binary payloads / magic files are forbidden.
            require(b"\x00" not in data, "BINARY_SOURCE_DENIED")
            try:
                source = data.decode("utf-8")
                if entry["path"].endswith(".py"):
                    ast.parse(source, filename=entry["path"])
            except (UnicodeError, SyntaxError) as exc:
                raise QualificationDenied("SOURCE_SYNTAX_INVALID") from exc
        return {
            "status": "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED",
            "artifact_sha256": digest(raw),
            "base_commit": base,
            "source_file_count": len(entries),
            "total_source_bytes": total,
            "paths": [e["path"] for e in entries],
            "files": entries,
            "sandbox_tested": False,
            "canary_deployed": False,
            "production_modified": False,
            "execution_authorized": False,
        }


def qualify_transfer(transfer_id: str) -> dict:
    """Only an already-finalized, hash-pinned artifact can be qualified."""
    inbox._valid_id(transfer_id)
    root = inbox._transfer(transfer_id)
    lock_fd = inbox._lock(root)
    try:
        receipt = inbox._record(root)
        path, received, state = inbox._content_state(root, receipt)
        require(state == "VERIFIED" and received == receipt["size"],
                "TRANSFER_NOT_VERIFIED")
        raw = inbox._owned_file(path, max_size=MAX_ARCHIVE)
        result = qualify_bytes(raw, receipt["sha256"])
        return {"transfer_id": transfer_id, **result}
    finally:
        os.close(lock_fd)
