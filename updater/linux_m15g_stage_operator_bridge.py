"""M15-G operator-only stage existing-container bridge; ISOLATED CI ONLY.

There is NO remote MCP route, no installer, no arbitrary Docker command.
A local AF_UNIX peer is authenticated by Linux SO_PEERCRED; a fixed locally
reviewed M14E plan is SHA-pinned and independently revalidated immediately
before mutation. The existing M14E journal/rollback engine remains the only
code permitted to start/stop exactly three existing fieldwork-stage containers.

CRITICAL: an operator OS UID is not proof of physical human presence.
The helper is Docker-connected/root-equivalent and has a stage-scoped
ephemeral HMAC issued inside its own process. Real Pi activation requires
real local-human consent and independent M12 Docker privilege audit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import struct
import time

if __package__:
    from . import linux_stage_existing_lifecycle as stage
else:
    import linux_stage_existing_lifecycle as stage

MAX_REQUEST = 256
MAX_REPLY = 1024
DENIED = b'{"status":"M15G_STAGE_BRIDGE_DENIED","production_modified":false}\n'


class StageBridgeDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise StageBridgeDenied(reason)


def _pairs(entries: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in entries:
        require(key not in result, "M15G_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse_request(packet: bytes, *, plan_sha256: str) -> None:
    require(type(packet) is bytes and
            0 < len(packet) <= MAX_REQUEST and
            packet.count(b"\n") == 1 and
            packet.endswith(b"\n"),
            "M15G_FRAMING_DENIED")
    require(type(plan_sha256) is str and
            stage.HEX64.fullmatch(plan_sha256) is not None,
            "M15G_PIN_DENIED")
    try:
        obj = json.loads(
            packet[:-1].decode("ascii"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                StageBridgeDenied("M15G_CONSTANT_DENIED")))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, StageBridgeDenied):
            raise
        raise StageBridgeDenied("M15G_JSON_DENIED") from exc
    require(type(obj) is dict and set(obj) == {
        "version", "plan_sha256"} and type(obj["version"]) is int
        and obj["version"] == 1 and
        type(obj["plan_sha256"]) is str and
        obj["plan_sha256"] == plan_sha256,
        "M15G_PINNED_PLAN_REQUIRED")
    expected = json.dumps(
        {"version": 1, "plan_sha256": plan_sha256},
        sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    require(packet == expected, "M15G_NONCANONICAL_REQUEST")


def peer_uid(conn: socket.socket) -> int:
    require(conn.family == socket.AF_UNIX and
            hasattr(socket, "SO_PEERCRED"), "M15G_LOCAL_PEER_REQUIRED")
    try:
        raw = conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, ValueError, struct.error) as exc:
        raise StageBridgeDenied("M15G_PEERCREDS_UNAVAILABLE") from exc
    require(pid > 0 and uid >= 0 and gid >= 0,
            "M15G_PEERCREDS_INVALID")
    return uid


class OperatorOnlyExistingStage:
    """No Docker-code execution is allowed until positive trusted local IPC.

    The trusted local launcher constructs this with an exact known M14E plan,
    local-only short-lived secret, helper-owned 0700 state, and three
    independently configured, non-root UIDs: operator, MCP, Docker helper.
    """
    def __init__(self, *, plan: dict, plan_sha256: str,
                 helper_secret: bytes, state_root: Path,
                 operator_uid: int, mcp_uid: int, helper_uid: int):
        require(type(operator_uid) is int and operator_uid > 0 and
                type(mcp_uid) is int and mcp_uid > 0 and
                type(helper_uid) is int and helper_uid > 0 and
                len({operator_uid, mcp_uid, helper_uid}) == 3,
                "M15G_UID_ISOLATION_REQUIRED")
        require(os.geteuid() == helper_uid,
                "M15G_HELPER_EUID_MISMATCH")
        require(type(helper_secret) is bytes and
                len(helper_secret) >= 32, "M15G_HELPER_KEY_INVALID")
        stage._secure_state(state_root)
        require(stage.validate_plan(plan, now=int(time.time()), observe=False)
                == plan_sha256, "M15G_INVALID_TRUSTED_PLAN")
        self.plan = plan
        self.plan_sha = plan_sha256
        self._key = helper_secret
        self.state_root = state_root
        self.operator_uid = operator_uid
        self.mcp_uid = mcp_uid
        self.helper_uid = helper_uid

    def _mutate(self, *, payload: bytes, uid: int, now: int) -> dict:
        require(type(uid) is int and uid == self.operator_uid
                and uid not in (0, self.mcp_uid, self.helper_uid),
                "M15G_OPERATOR_UID_DENIED")
        parse_request(payload, plan_sha256=self.plan_sha)
        require(type(now) is int, "M15G_CLOCK_DENIED")
        require(stage.validate_plan(self.plan, now=now, observe=True)
                == self.plan_sha, "M15G_STAGE_CHANGED_AFTER_REVIEW")
        # Separate OS operator UID/peercred authenticates the caller.
        # This is NOT yet real physical-user authorization and therefore
        # this service is NOT to be deployed to the Pi.
        ticket = stage.issue_local_ticket(
            self.plan, secret=self._key, local_operator_present=True,
            now=now, nonce=os.urandom(16).hex())
        result = stage.execute_approved(
            self.plan, ticket, secret=self._key,
            state=self.state_root, now=now)
        require(result.get("status") ==
                "STAGE_APPROVED_EXISTING_CONTAINERS_CHANGED" and
                result.get("production_modified") is False and
                result.get("volume_deleted") is False,
                "M15G_RESULT_SCOPE_INVALID")
        return {
            "status": "M15G_STAGE_EXISTING_ONLY_APPLIED",
            "project": stage.PROJECT,
            "plan_sha256": self.plan_sha,
            "changed_count": result["changed_count"],
            "action": result["action"],
            "no_create_or_delete": True,
            "production_modified": False,
        }

    def serve_connection(self, conn: socket.socket) -> bool:
        conn.settimeout(4)
        try:
            uid = peer_uid(conn)
            require(uid == self.operator_uid, "M15G_OPERATOR_ONLY")
            data = bytearray()
            while len(data) <= MAX_REQUEST:
                chunk = conn.recv(min(128, MAX_REQUEST + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if b"\n" in chunk:
                    break
            response = self._mutate(
                payload=bytes(data), uid=uid, now=int(time.time()))
            encoded = json.dumps(response, sort_keys=True,
                                 separators=(",", ":")).encode("ascii") + b"\n"
            require(len(encoded) <= MAX_REPLY, "M15G_RESPONSE_TOO_LARGE")
            successful = True
        except (StageBridgeDenied, stage.StageDenied, OSError, TypeError,
                ValueError, OverflowError):
            encoded = DENIED
            successful = False
        try:
            conn.sendall(encoded)
        except OSError:
            return False
        return successful
