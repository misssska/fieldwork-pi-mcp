"""M15 independently pinned, user-owned *offline staging* (not activation).

Purpose: place a pre-verified sidecar candidate in a fresh private directory,
with no service changes or privileged operations. The caller must supply an
outer SHA-256 and commit from a separate trusted local release decision.
An untrusted MCP source cannot confer publisher trust or OS authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tarfile
import io

if __package__:
    from . import m15_portable_bundle as bundle
else:
    import m15_portable_bundle as bundle


class StageDenied(ValueError):
    pass


def require(ok: bool, reason: str):
    if not ok:
        raise StageDenied(reason)


def _private_dir(path: Path):
    require(isinstance(path, Path) and path.is_absolute()
            and path.is_dir() and not path.is_symlink(),
            "M15_STAGE_PARENT_INVALID")
    st = path.stat()
    require(st.st_uid == os.geteuid() and
            stat.S_IMODE(st.st_mode) == 0o700,
            "M15_STAGE_PARENT_NOT_PRIVATE")


def _sync(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(parent: Path, name: str, content: bytes):
    require(type(name) is str and
            (name in {".complete.json"} or name in {
                Path(f).name for f in bundle.FILES
            }) and
            type(content) is bytes and 0 < len(content) <= bundle.MAX_FILE,
            "M15_STAGE_FILE_DENIED")
    fd = os.open(parent / name,
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def stage_verified_archive(archive: bytes, *, trusted_outer_sha256: str,
                           trusted_source_commit: str, local_parent: Path,
                           local_staging_consent: bool) -> dict:
    """No shell/daemon, no import/exec, no root, no overwrite or auto-cleanup."""
    require(os.geteuid() != 0, "M15_STAGE_ROOT_DENIED")
    require(local_staging_consent is True, "M15_STAGE_CONSENT_REQUIRED")
    _private_dir(local_parent)
    proof = bundle.inspect_archive(
        archive, trusted_outer_sha256=trusted_outer_sha256,
        trusted_source_commit=trusted_source_commit)
    name = "m15-" + trusted_outer_sha256[:20]
    target = local_parent / name
    require(not target.exists() and not target.is_symlink(),
            "M15_STAGE_REPLAY_DENIED")
    target.mkdir(mode=0o700)
    _private_dir(target)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as t:
            for item in t:
                if item.name.endswith("/manifest.json"):
                    continue
                require(item.isfile() and bundle._path_ok(item.name),
                        "M15_STAGE_UNVERIFIED_ENTRY")
                relative = item.name[len(bundle.ROOT)+1:]
                output = target / relative
                subdir = output.parent
                if not subdir.exists():
                    subdir.mkdir(parents=True, mode=0o700)
                require(subdir.is_dir() and not subdir.is_symlink(),
                        "M15_STAGE_SUBDIR_INVALID")
                content = t.extractfile(item).read(bundle.MAX_FILE+1)
                require(len(content) == item.size,
                        "M15_STAGE_PAYLOAD_CHANGED")
                _write_new(subdir, output.name, content)
        # This is the LAST write, certifying all files are present.
        marker = (json.dumps({
            "status":"M15_STAGED_ONLY",
            "source_commit":trusted_source_commit,
            "outer_sha256":trusted_outer_sha256,
            "activation_authorized":False,
            "production_modified":False,
        }, sort_keys=True)+"\n").encode("ascii")
        _write_new(target, ".complete.json", marker)
        for subdir in (target / "updater", target / "deploy/systemd",
                       target / "deploy"):
            if subdir.exists():
                _sync(subdir)
        _sync(target)
        _sync(local_parent)
    except Exception:
        # A failed partial directory is intentionally not silently deleted:
        # it is not a complete install and cannot be reused (fail-closed).
        raise
    return {
        **proof,
        "status": "M15_USER_OWNED_CANDIDATE_STAGED",
        "staged_files": len(bundle.FILES),
        "activation_authorized": False,
        "service_modified": False,
        "mcp_modified": False,
        "production_modified": False,
    }
