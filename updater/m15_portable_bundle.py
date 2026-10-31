"""M15 deterministic Linux MCP *sidecar candidate* packaging.

Builds one archive of explicitly reviewed plain Python and systemd references.
No installation, root commands, service changes, Docker operations, or Pi
network access. Signed publisher authorization is NOT provided by the package:
the outer sha256 must be pinned by a separately trusted operator source.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import gzip
import json
from pathlib import Path, PurePosixPath
import os
import stat
import sys
import tarfile

FILES = (
    "updater/m15_portable_bundle.py",
    "updater/m15_user_stage.py",
    "updater/m15_inactive_bootstrap.py",
    "updater/linux_telemetry.py",
    "updater/mcp_linux_telemetry.py",
    "updater/linux_upgrade_gate.py",
    "updater/linux_approval_redeemer.py",
    "updater/linux_upgrade_inbox.py",
    "updater/linux_upgrade_review_ui.py",
    "updater/linux_upgrade_local_handoff.py",
    "updater/linux_upgrade_local_transaction.py",
    "updater/linux_upgrade_operator_app.py",
    "updater/linux_upgrade_trust_gate.py",
    "updater/linux_docker_read_proxy.py",
    "updater/linux_docker_read_proxy_client.py",
    "updater/linux_docker_read_proxy_service.py",
    "updater/linux_stage_existing_lifecycle.py",
    "updater/linux_stage_compose_contract.py",
    "updater/linux_sandbox_ownership_gate.py",
    "deploy/systemd/linux-mcp-operator.service",
    "deploy/systemd/linux-mcp-docker-proxy.service",
    "deploy/systemd/linux-mcp-docker-proxy.socket",
)
ROOT = "linux-mcp-sidecar-m15"
MANIFEST = "manifest.json"
MAX_FILE = 256 * 1024
MAX_ARCHIVE = 4 * 1024 * 1024
MTIME = 0


class BundleDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise BundleDenied(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _path_ok(name: str) -> bool:
    if type(name) is not str or not name.startswith(ROOT + "/"):
        return False
    p = PurePosixPath(name)
    if name != p.as_posix() or p.is_absolute() or ".." in p.parts:
        return False
    return name[len(ROOT) + 1:] in set(FILES) | {MANIFEST}


def _member(name: str, data: bytes) -> tuple[tarfile.TarInfo, bytes]:
    require(type(data) is bytes and 0 < len(data) <= MAX_FILE,
            "M15_FILE_SIZE_DENIED")
    info = tarfile.TarInfo(ROOT + "/" + name)
    info.size = len(data)
    info.mtime = MTIME
    info.mode = 0o600
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info, data


def collect(repo_root: Path) -> dict[str, bytes]:
    require(isinstance(repo_root, Path) and repo_root.is_absolute() and
            repo_root.is_dir() and not repo_root.is_symlink(),
            "M15_SOURCE_ROOT_DENIED")
    entries = {}
    for relative in FILES:
        path = repo_root / relative
        # Parent symlinks can escape a repository even if the file isn't a link.
        for parent in (repo_root / "updater", repo_root / "deploy",
                       repo_root / "deploy/systemd"):
            if parent == path.parent or parent in path.parents:
                require(not parent.is_symlink(),
                        "M15_SOURCE_PARENT_SYMLINK_DENIED")
        require(path.is_file() and not path.is_symlink(),
                "M15_SOURCE_FILE_UNSAFE")
        st = path.stat()
        require(stat.S_ISREG(st.st_mode) and
                not (st.st_mode & 0o022) and
                0 < st.st_size <= MAX_FILE,
                "M15_SOURCE_FILE_MODE_OR_SIZE_DENIED")
        b = path.read_bytes()
        require(len(b) == st.st_size, "M15_SOURCE_RACE_DENIED")
        entries[relative] = b
    return entries


def make_archive(files: dict[str, bytes], *, source_commit: str) -> bytes:
    require(type(source_commit) is str and len(source_commit) == 40 and
            all(c in "0123456789abcdef" for c in source_commit),
            "M15_IMMUTABLE_COMMIT_REQUIRED")
    require(type(files) is dict and set(files) == set(FILES),
            "M15_FILE_SET_DENIED")
    listing = []
    for name in sorted(FILES):
        b = files[name]
        require(type(b) is bytes and 0 < len(b) <= MAX_FILE,
                "M15_CONTENT_INVALID")
        listing.append({"path": name, "size": len(b), "sha256": sha(b)})
    manifest = canonical({
        "schema": 1, "kind": "linux-mcp-sidecar-candidate",
        "source_commit": source_commit, "entries": listing,
        "deployment_authorized": False,
        "production_modified": False,
        "publisher_signature_verified": False,
    })
    payload = {**files, MANIFEST: manifest}
    output = io.BytesIO()
    # gzip's default header timestamp breaks reproducibility even when
    # every tar entry mtime is fixed. Pin both layer timestamps to zero.
    with gzip.GzipFile(fileobj=output, mode="wb", filename="",
                       mtime=0, compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed, mode="w",
                          format=tarfile.PAX_FORMAT) as tar:
            for name in sorted(payload):
                info, b = _member(name, payload[name])
                tar.addfile(info, io.BytesIO(b))
    result = output.getvalue()
    require(len(result) <= MAX_ARCHIVE, "M15_ARCHIVE_TOO_LARGE")
    return result


def inspect_archive(raw: bytes, *, trusted_outer_sha256: str,
                    trusted_source_commit: str) -> dict:
    """Verify WITHOUT extracting. Do not trust an archive's own manifest."""
    require(type(trusted_outer_sha256) is str and
            len(trusted_outer_sha256) == 64 and
            all(c in "0123456789abcdef" for c in trusted_outer_sha256) and
            type(trusted_source_commit) is str and
            len(trusted_source_commit) == 40 and
            all(c in "0123456789abcdef" for c in trusted_source_commit),
            "M15_EXTERNAL_TRUST_PIN_MISSING")
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE and
            sha(raw) == trusted_outer_sha256,
            "M15_ARCHIVE_OUTER_HASH_DENIED")
    found = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for entry in archive:
                require(entry.isfile() and not entry.issym() and
                        not entry.islnk() and
                        _path_ok(entry.name) and
                        entry.name not in found and
                        entry.size > 0 and entry.size <= MAX_FILE and
                        entry.mode == 0o600 and
                        entry.uid == 0 and entry.gid == 0,
                        "M15_TAR_ENTRY_DENIED")
                stream = archive.extractfile(entry)
                require(stream is not None,
                        "M15_TAR_PAYLOAD_MISSING")
                b = stream.read(MAX_FILE + 1)
                require(len(b) == entry.size,
                        "M15_TAR_PAYLOAD_TRUNCATED")
                found[entry.name] = b
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BundleDenied("M15_TAR_INVALID") from exc
    require(set(found) == {ROOT + "/" + x for x in FILES} |
            {ROOT + "/" + MANIFEST},
            "M15_TAR_SET_DENIED")
    try:
        manifest = json.loads(found[ROOT + "/" + MANIFEST].decode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise BundleDenied("M15_MANIFEST_JSON_DENIED") from exc
    require(type(manifest) is dict and
            set(manifest) == {
                "schema", "kind", "source_commit", "entries",
                "deployment_authorized", "production_modified",
                "publisher_signature_verified",
            } and
            manifest["schema"] == 1 and
            manifest["kind"] == "linux-mcp-sidecar-candidate" and
            manifest["source_commit"] == trusted_source_commit and
            manifest["deployment_authorized"] is False and
            manifest["production_modified"] is False and
            manifest["publisher_signature_verified"] is False and
            canonical(manifest) == found[ROOT + "/" + MANIFEST],
            "M15_MANIFEST_POLICY_DENIED")
    listing = manifest["entries"]
    require(type(listing) is list and len(listing) == len(FILES),
            "M15_MANIFEST_COUNT_DENIED")
    for actual, relative in zip(listing, sorted(FILES)):
        b = found[ROOT + "/" + relative]
        require(type(actual) is dict and
                set(actual) == {"path", "sha256", "size"} and
                actual["path"] == relative and
                type(actual["size"]) is int and
                actual["size"] == len(b) and
                actual["sha256"] == sha(b),
                "M15_MODULE_HASH_DENIED")
    return {
        "status": "M15_OFFLINE_BUNDLE_VERIFIED",
        "source_commit": trusted_source_commit,
        "outer_sha256": trusted_outer_sha256,
        "files_checked": len(FILES),
        "contains_executable_entrypoints": True,
        "installation_performed": False,
        "activation_authorized": False,
        "publisher_signature_verified": False,
        "production_modified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline Linux MCP sidecar bundle; never install")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    data = make_archive(collect(args.source_root.resolve()),
                        source_commit=args.commit)
    # Build restricted to a fresh artifact path, no overwrite.
    require(not args.out.exists() and not args.out.is_symlink(),
            "M15_OUTPUT_EXISTS")
    require(args.out.parent.is_dir() and
            not args.out.parent.is_symlink(),
            "M15_OUTPUT_PARENT_UNSAFE")
    descriptor = os.open(args.out, os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        args.out.unlink(missing_ok=True)
        raise
    print(json.dumps(inspect_archive(data,
           trusted_outer_sha256=sha(data),
           trusted_source_commit=args.commit), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleDenied as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
