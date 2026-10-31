"""M15B *inactive* sidecar bootstrap, with a fixed /opt install scope.

Not a remote MCP tool and not a service/permission migrator.
One-time root-owned source installation ONLY, no systemd units written,
no Docker calls, no user/group creation, no operator HMAC keys generated,
no executable code imported or run. Requires an independently supplied
immutable source commit and SHA256; the caller is responsible for
establishing publisher trust and local admin authorization.

Incomplete bootstrap is deliberately never re-used or automatically cleaned.
Only a trusted local root operator may reconcile it. The pre-existing M12
is neither read nor changed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile

if __package__:
    from . import m15_portable_bundle as bundle
else:
    import m15_portable_bundle as bundle

INSTALL_PARENT = Path("/opt")
INSTALL_DIR = Path("/opt/linux-mcp-operator")
MAX_READ = bundle.MAX_ARCHIVE


class BootstrapDenied(ValueError):
    pass


def require(ok: bool, code: str):
    if not ok:
        raise BootstrapDenied(code)


def _directory_root_owned(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink(),
            "M15B_PARENT_NOT_DIRECTORY")
    st = path.stat()
    require(st.st_uid == 0 and
            stat.S_IMODE(st.st_mode) & 0o022 == 0,
            "M15B_PARENT_WRITABLE_OR_NOT_ROOT")


def _fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _new_file(dirpath: Path, name: str, content: bytes, *,
              mode: int = 0o444):
    require(name in {Path(p).name for p in bundle.FILES} |
            {"manifest.json", ".complete.json"} and
            type(content) is bytes and 0 < len(content) <= bundle.MAX_FILE,
            "M15B_FILE_DENIED")
    fd = os.open(dirpath / name,
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    (dirpath / name).chmod(mode)


def _source_manifest(archive: bytes, expected_commit: str, trusted_sha: str) -> dict:
    verified = bundle.inspect_archive(
        archive, trusted_outer_sha256=trusted_sha,
        trusted_source_commit=expected_commit)
    require(verified["publisher_signature_verified"] is False and
            verified["activation_authorized"] is False,
            "M15B_UNEXPECTED_ACTIVATION_FLAG")
    return verified


def verify_only(archive: bytes, *, trusted_sha: str,
                trusted_commit: str) -> dict:
    proof = _source_manifest(archive, trusted_commit, trusted_sha)
    # Validate static Python syntax before local privileged file creation.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for info in tar:
            if info.name.endswith(".py"):
                payload = tar.extractfile(info).read(bundle.MAX_FILE + 1)
                require(len(payload) == info.size,
                        "M15B_PYTHON_READ_DRIFT")
                try:
                    tree = ast.parse(payload.decode("utf-8"), filename=info.name)
                    compile(tree, info.name, "exec")
                except (SyntaxError, UnicodeError, ValueError) as exc:
                    raise BootstrapDenied("M15B_PYTHON_SYNTAX_DENIED") from exc
    return {
        **proof,
        "status": "M15B_INACTIVE_BOOTSTRAP_PREFLIGHT_PASS",
        "installation_performed": False,
        "activation_authorized": False,
        "service_started": False,
        "production_modified": False,
    }


def install_inactive(archive: bytes, *, trusted_sha: str,
                     trusted_commit: str, local_admin_approval: bool,
                     install_parent: Path = INSTALL_PARENT) -> dict:
    """Root-only file provisioning; does not grant the operator any authority.

    install_parent is an internal test seam; production CLI always uses
    /opt and forbids caller-selected install paths. A boolean is not a
    cryptographic proof of local presence and MUST NOT be exposed as MCP.
    """
    require(os.geteuid() == 0, "M15B_ROOT_ONLY")
    require(local_admin_approval is True,
            "M15B_EXPLICIT_LOCAL_ADMIN_APPROVAL_REQUIRED")
    require(type(install_parent) is Path and install_parent.is_absolute(),
            "M15B_INSTALL_PARENT_INVALID")
    _directory_root_owned(install_parent)
    target = install_parent / INSTALL_DIR.name
    require(not target.exists() and not target.is_symlink(),
            "M15B_EXISTING_INSTALL_REFUSED")
    proof = verify_only(archive, trusted_sha=trusted_sha,
                        trusted_commit=trusted_commit)
    # Creation with O_EXCL-style mkdir; no preexisting directory is replaced.
    target.mkdir(mode=0o700)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for info in tar:
                relative = info.name[len(bundle.ROOT) + 1:]
                payload = tar.extractfile(info).read(bundle.MAX_FILE + 1)
                require(len(payload) == info.size and
                        bundle._path_ok(info.name),
                        "M15B_PAYLOAD_READ_DRIFT")
                # Flatten audited Python modules only into /opt/operator.
                # Do not install systemd reference units anywhere on the host.
                if relative.endswith(".py"):
                    _new_file(target, Path(relative).name, payload)
                elif relative == "manifest.json":
                    _new_file(target, "manifest.json", payload)
        marker = bundle.canonical({
            "status": "M15B_INSTALLED_INACTIVE",
            "commit": trusted_commit,
            "archive_sha256": trusted_sha,
            "service_enabled": False,
            "service_started": False,
            "mcp_modified": False,
            "production_modified": False,
        })
        _new_file(target, ".complete.json", marker)
        _fsync_dir(target)
        target.chmod(0o755)
        _fsync_dir(install_parent)
    except Exception:
        # Fail closed. Leave root-owned 0700 incomplete directory for explicit
        # local manual reconciliation. Never blindly rm -rf a host path.
        raise
    return {
        "status": "M15B_INSTALLED_INACTIVE",
        "source_commit": trusted_commit,
        "source_archive_sha256": trusted_sha,
        "operator_modules_installed": len([p for p in bundle.FILES if p.endswith(".py")]),
        "service_enabled": False,
        "service_started": False,
        "mcp_modified": False,
        "production_modified": False,
        "privilege_boundary_verified": False,
        "update_capability_enabled": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M15B root-only inactive Linux MCP bootstrap")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--trusted-sha256", required=True)
    parser.add_argument("--trusted-commit", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install-inactive", action="store_true")
    args = parser.parse_args(argv)
    # CLI cannot override /opt target or choose a unit name.
    if args.install_inactive:
        require(os.geteuid() == 0, "M15B_ROOT_ONLY")
        require(sys.stdin.isatty(), "M15B_TTY_LOCAL_APPROVAL_REQUIRED")
        print("M15B: ONLY /opt/linux-mcp-operator will be created;")
        print("no running MCP, production, systemd or Docker change.")
        print("Verified commit: " + args.trusted_commit)
        print("Outer SHA256: " + args.trusted_sha256)
        approved = input("Type INSTALL_INACTIVE_M15B to authorize local file-only bootstrap: ")
        require(approved == "INSTALL_INACTIVE_M15B", "M15B_LOCAL_APPROVAL_DENIED")
    raw = args.archive.read_bytes()
    require(len(raw) <= MAX_READ, "M15B_ARCHIVE_TOO_LARGE")
    if args.check:
        result = verify_only(raw, trusted_sha=args.trusted_sha256,
                             trusted_commit=args.trusted_commit)
    else:
        result = install_inactive(raw, trusted_sha=args.trusted_sha256,
                                  trusted_commit=args.trusted_commit,
                                  local_admin_approval=True)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BootstrapDenied, bundle.BundleDenied, OSError) as exc:
        print("M15B_STOP=" + type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
