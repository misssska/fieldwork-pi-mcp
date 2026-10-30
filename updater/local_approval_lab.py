"""Offline verifier for a locally issued, one-use FieldWork MCP approval.

NO token issuer, NO installer, NO remote approval endpoint. This module cannot
grant approval by itself. The signing key must remain in a separate, local-only
trusted approval process, never exposed through the MCP or GitHub.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import time

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = frozenset({
    "schema", "purpose", "commit", "manifest_sha256",
    "installed_sha256", "candidate_sha256", "extension_sha256",
    "nonce", "issued_at", "expires_at",
})
PURPOSE = "fieldwork-pi-mcp:activate-v1"
MAX_LIFETIME = 300
MAX_SKEW = 30


class ApprovalDenied(RuntimeError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ApprovalDenied(code)


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def verify(token: dict, key: bytes, *, expected: dict, now: int | None = None) -> dict:
    """Verify signed local evidence, without issuing, consuming or installing."""
    require(type(token) is dict and set(token) == {"payload", "mac"},
            "TOKEN_SCHEMA_DENIED")
    payload, mac = token["payload"], token["mac"]
    require(type(payload) is dict and set(payload) == FIELDS,
            "PAYLOAD_SCHEMA_DENIED")
    require(payload["schema"] == 1 and type(payload["schema"]) is int
            and payload["purpose"] == PURPOSE, "PURPOSE_DENIED")
    require(type(mac) is str and HEX64.fullmatch(mac) is not None,
            "MAC_FORMAT_DENIED")
    require(type(key) is bytes and len(key) >= 32, "LOCAL_KEY_REQUIRED")
    require(type(expected) is dict and set(expected) == {
        "commit", "manifest_sha256", "installed_sha256",
        "candidate_sha256", "extension_sha256",
    }, "EXPECTED_FIELDS_DENIED")
    for name in ("commit", "manifest_sha256", "installed_sha256",
                 "candidate_sha256", "extension_sha256"):
        value = payload[name]
        pattern = HEX40 if name == "commit" else HEX64
        require(type(value) is str and pattern.fullmatch(value) is not None,
                "INVALID_PIN:" + name)
        require(type(expected[name]) is str and
                hmac.compare_digest(value, expected[name]), "PIN_MISMATCH:" + name)
    require(type(payload["nonce"]) is str and HEX32.fullmatch(payload["nonce"]) is not None,
            "NONCE_DENIED")
    issued, expires = payload["issued_at"], payload["expires_at"]
    require(type(issued) is int and type(expires) is int,
            "TIME_SCHEMA_DENIED")
    now = int(time.time()) if now is None else now
    require(type(now) is int and issued <= now + MAX_SKEW
            and expires > now and 0 < expires - issued <= MAX_LIFETIME,
            "EXPIRED_OR_INVALID_WINDOW")
    correct = hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()
    require(hmac.compare_digest(correct, mac), "SIGNATURE_DENIED")
    return {"status": "VALID_LOCAL_PROOF_NOT_CONSUMED",
            "nonce": payload["nonce"], "expires_at": expires,
            "activation_authorized": False}


def _safe_dir(path: Path) -> None:
    home = Path.home()
    require(path.is_relative_to(home), "REPLAY_DESTINATION_DENIED")
    for part in (path, *path.parents):
        if part == home.parent:
            break
        require(part.is_dir() and not part.is_symlink(), "REPLAY_DIR_UNSAFE")
        st = part.stat()
        require(st.st_uid == os.getuid() and not (st.st_mode & 0o022),
                "REPLAY_PARENT_PERMISSIONS_DENIED")
    st = path.stat()
    require(not (st.st_mode & 0o077), "REPLAY_DIR_PERMISSIONS_DENIED")


def verify_and_consume(token: dict, key: bytes, *, expected: dict,
                       replay_dir: Path, now: int | None = None) -> dict:
    """Verify MAC and claim the nonce in one call; still never activates.

    The issuer and activation adapter are deliberately absent.
    """
    proof = verify(token, key, expected=expected, now=now)
    require(type(proof) is dict and set(proof) == {
        "status", "nonce", "expires_at", "activation_authorized",
    } and proof["status"] == "VALID_LOCAL_PROOF_NOT_CONSUMED"
            and proof["activation_authorized"] is False,
            "UNVERIFIED_PROOF_DENIED")
    nonce = proof["nonce"]
    require(type(nonce) is str and HEX32.fullmatch(nonce) is not None,
            "NONCE_DENIED")
    require(type(proof["expires_at"]) is int and proof["expires_at"] > int(time.time()),
            "EXPIRED_PROOF_DENIED")
    # The caller cannot redirect this state to a production or arbitrary path.
    expected_dir = Path.home() / ".local/state/fieldwork-pi-mcp/local-approval/used"
    require(replay_dir == expected_dir, "REPLAY_DESTINATION_DENIED")
    _safe_dir(replay_dir)
    # Anchor the create operation to the verified directory descriptor.
    dirfd = os.open(replay_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                    getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            fd = os.open(nonce, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=dirfd)
        except FileExistsError as exc:
            raise ApprovalDenied("APPROVAL_REPLAY_DENIED") from exc
        with os.fdopen(fd, "wb") as f:
            f.write((nonce + "\n").encode("ascii"))
            f.flush()
            os.fsync(f.fileno())
        os.fsync(dirfd)
    finally:
        os.close(dirfd)
    return {"status": "PROOF_CONSUMED_NO_ACTIVATION",
            "nonce": nonce, "activation_authorized": False}
