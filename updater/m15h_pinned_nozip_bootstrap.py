"""M15-H exact-commit/no-manual-ZIP bootstrap transport (INACTIVE ONLY).

A locally trusted, pinned script can fetch only the M15 allowlist from the
fixed public GitHub repository at one 40-hex commit, recreate the deterministic
bundle, then verify its entire SHA256 against an OUT-OF-BAND trusted value.
No downloaded Python bytes are imported or executed. Installation delegates
to M15-B: root + local TTY + manual phrase, fixed /opt target, no systemd,
users, Docker, MCP update or HMAC key creation.

This file is NOT callable from the currently installed MCP and is NOT active
on Pi; GitHub hosting and the user's verified script are trust prerequisites.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import ssl
import sys
import urllib.error
import urllib.request

if __package__:
    from . import m15_portable_bundle as bundle
    from . import m15_inactive_bootstrap as bootstrap
else:
    import m15_portable_bundle as bundle
    import m15_inactive_bootstrap as bootstrap

REPO_BASE = "https://raw.githubusercontent.com/misssska/fieldwork-pi-mcp/"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
REVIEW_PHRASE = "INSTALL_INACTIVE_PINNED_M15H"


class PinnedBootstrapDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise PinnedBootstrapDenied(code)


def validate_pins(commit: str, expected_sha256: str) -> None:
    require(type(commit) is str and HEX40.fullmatch(commit) is not None,
            "M15H_IMMUTABLE_COMMIT_REQUIRED")
    require(type(expected_sha256) is str and
            HEX64.fullmatch(expected_sha256) is not None,
            "M15H_OUT_OF_BAND_ARCHIVE_PIN_REQUIRED")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PinnedBootstrapDenied("M15H_HTTP_REDIRECT_DENIED")


def _network_reader(commit: str, relative: str) -> bytes:
    # Each segment is fixed by bundle.FILES and both fields are validated.
    require(relative in bundle.FILES, "M15H_SOURCE_PATH_DENIED")
    require(type(commit) is str and HEX40.fullmatch(commit) is not None,
            "M15H_NETWORK_COMMIT_DENIED")
    url = REPO_BASE + commit + "/" + relative
    require(url.startswith(REPO_BASE) and
            all(x not in relative for x in ("..", "?", "#", "\\", "%")),
            "M15H_SOURCE_URL_DENIED")
    request = urllib.request.Request(
        url, headers={"User-Agent": "linux-mcp-m15h-pinned-bootstrap/1",
                      "Accept": "application/octet-stream"},
        method="GET")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=8) as response:
            require(response.status == 200, "M15H_SOURCE_HTTP_DENIED")
            data = response.read(bundle.MAX_FILE + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise PinnedBootstrapDenied("M15H_SOURCE_UNAVAILABLE") from exc
    require(type(data) is bytes and 0 < len(data) <= bundle.MAX_FILE,
            "M15H_SOURCE_SIZE_DENIED")
    return data


def acquire_verified_archive(*, commit: str, trusted_sha256: str,
                             source_reader=None) -> bytes:
    """Every fetched file is DATA, not Python runtime code.

    Caller-provided reader is a test seam. Production CLI always uses
    the fixed no-redirect HTTPS reader. Never accept URL/source path as CLI.
    """
    validate_pins(commit, trusted_sha256)
    reader = _network_reader if source_reader is None else source_reader
    require(callable(reader), "M15H_SOURCE_READER_INVALID")
    files = {}
    for name in bundle.FILES:
        data = reader(commit, name)
        require(type(data) is bytes and 0 < len(data) <= bundle.MAX_FILE,
                "M15H_SOURCE_BOUNDS_DENIED")
        files[name] = data
    archive = bundle.make_archive(files, source_commit=commit)
    require(hashlib.sha256(archive).hexdigest() == trusted_sha256,
            "M15H_ARCHIVE_NOT_IDENTICAL_TO_TRUST_PIN")
    report = bootstrap.verify_only(
        archive, trusted_sha=trusted_sha256, trusted_commit=commit)
    require(report["activation_authorized"] is False and
            report["publisher_signature_verified"] is False and
            report["installation_performed"] is False,
            "M15H_UNEXPECTED_PRIVILEGE_GRANTED")
    return archive


def run(*, mode: str, commit: str, trusted_sha256: str,
        source_reader=None, local_admin_approval: bool = False,
        install_parent: Path | None = None) -> dict:
    """Local-only. install_parent is strictly an offline CI seam.

    In the production CLI, install_parent is always omitted and M15B
    uses its exact /opt/linux-mcp-operator target.
    """
    require(mode in ("check", "install-inactive", "rollback-inactive")
            and type(mode) is str, "M15H_MODE_DENIED")
    validate_pins(commit, trusted_sha256)
    if mode == "rollback-inactive":
        require(os.geteuid() == 0 and local_admin_approval is True,
                "M15H_ROLLBACK_LOCAL_ROOT_ONLY")
        kwargs = {} if install_parent is None else {
            "install_parent": install_parent}
        return bootstrap.rollback_inactive(
            trusted_sha=trusted_sha256, trusted_commit=commit,
            local_admin_approval=True, **kwargs)
    if mode == "install-inactive":
        # Reject remote/non-privileged caller *before* any network fetch.
        require(os.geteuid() == 0 and local_admin_approval is True,
                "M15H_INSTALL_LOCAL_ROOT_ONLY")
    archive = acquire_verified_archive(
        commit=commit, trusted_sha256=trusted_sha256,
        source_reader=source_reader)
    if mode == "check":
        return {
            "status": "M15H_PINNED_ARCHIVE_VERIFIED_NOT_INSTALLED",
            "source_commit": commit,
            "archive_sha256": trusted_sha256,
            "publisher_identity_verified": False,
            "installation_performed": False,
            "activation_authorized": False,
            "production_modified": False,
        }
    kwargs = {} if install_parent is None else {
        "install_parent": install_parent}
    installed = bootstrap.install_inactive(
        archive, trusted_sha=trusted_sha256, trusted_commit=commit,
        local_admin_approval=True, **kwargs)
    require(installed["status"] == "M15B_INSTALLED_INACTIVE" and
            installed["service_enabled"] is False and
            installed["update_capability_enabled"] is False,
            "M15H_INACTIVE_INSTALL_RESULT_INVALID")
    return {
        "status": "M15H_INACTIVE_SOURCE_INSTALLED_ONLY",
        "source_commit": commit,
        "archive_sha256": trusted_sha256,
        "services_started": False,
        "users_created": False,
        "hmac_keys_created": False,
        "production_modified": False,
        "privilege_boundary_verified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Local exact Git commit M15 source transport; no Pi MCP API")
    parser.add_argument("--trusted-commit", required=True)
    parser.add_argument("--trusted-archive-sha256", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install-inactive", action="store_true")
    mode.add_argument("--rollback-inactive", action="store_true")
    args = parser.parse_args(argv)
    validate_pins(args.trusted_commit, args.trusted_archive_sha256)
    if args.install_inactive or args.rollback_inactive:
        require(os.geteuid() == 0, "M15H_ROOT_REQUIRED")
        require(sys.stdin.isatty(), "M15H_LOCAL_TERMINAL_REQUIRED")
        print("M15H: ONLY the inactive root-owned /opt/linux-mcp-operator source")
        print("may be installed or rolled back; no live service or MCP changes.")
        print("Commit: " + args.trusted_commit)
        print("Bundle SHA256: " + args.trusted_archive_sha256)
        require(input("Type " + REVIEW_PHRASE + " to approve: ") ==
                REVIEW_PHRASE, "M15H_PHYSICAL_REVIEW_NOT_CONFIRMED")
    operation = ("install-inactive" if args.install_inactive else
                 "rollback-inactive" if args.rollback_inactive else "check")
    result = run(mode=operation, commit=args.trusted_commit,
                 trusted_sha256=args.trusted_archive_sha256,
                 local_admin_approval=bool(args.install_inactive or
                                           args.rollback_inactive))
    import json
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PinnedBootstrapDenied, bundle.BundleDenied,
            bootstrap.BootstrapDenied, OSError, ValueError) as exc:
        # Do not leak external URLs or arbitrary filesystem paths into
        # user-visible failure diagnostics. No automatic retries or deletes.
        code = str(exc)
        if not re.fullmatch(r"M15[A-Z0-9_]+", code):
            code = type(exc).__name__
        print("M15H_STOP=" + code, file=sys.stderr)
        raise SystemExit(2)
