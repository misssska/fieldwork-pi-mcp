"""M14D privileged Docker *read-only projection* protocol.

This module is intended for a SEPARATE local helper OS principal, never a
remote MCP handler. A Docker-connected helper is itself root-equivalent on
ordinary rootful Docker: its isolation and systemd hardening are release gates.

The protocol cannot select Docker commands, IDs, paths or filters. The only
operations are pre-defined sanitized inventory and bounded resource stats.
Unix peer credentials and the listener's Unix mode are both required.
"""
from __future__ import annotations

import json
import os
import re
import socket
import struct

if __package__:
    from . import mcp_self_diagnostics as inventory
    from . import mcp_linux_telemetry as telemetry
else:
    import mcp_self_diagnostics as inventory
    import mcp_linux_telemetry as telemetry

MAX_REQUEST = 512
MAX_REPLY = 240 * 1024
OPERATIONS = frozenset({"inventory", "resources"})


class ProxyDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ProxyDenied(code)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "DOCKER_PROXY_DUPLICATE_FIELD")
        result[key] = value
    return result


def parse_request(payload: bytes) -> str:
    require(type(payload) is bytes and 0 < len(payload) <= MAX_REQUEST,
            "DOCKER_PROXY_REQUEST_BOUNDS")
    require(payload.endswith(b"\n") and payload.count(b"\n") == 1,
            "DOCKER_PROXY_REQUEST_FRAMING")
    try:
        obj = json.loads(payload[:-1].decode("ascii"),
                         object_pairs_hook=_unique_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(
                             ProxyDenied("DOCKER_PROXY_CONSTANT_DENIED")))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ProxyDenied):
            raise
        raise ProxyDenied("DOCKER_PROXY_REQUEST_JSON_DENIED") from exc
    require(type(obj) is dict and set(obj) == {"version", "operation"},
            "DOCKER_PROXY_REQUEST_SCHEMA")
    require(type(obj["version"]) is int and obj["version"] == 1 and
            type(obj["operation"]) is str and
            obj["operation"] in OPERATIONS, "DOCKER_PROXY_OPERATION_DENIED")
    return obj["operation"]


def check_peer_uid(peer_uid: int, *, allowed_mcp_uid: int,
                   helper_uid: int) -> None:
    """A separate trusted OS launcher chooses allowed UID, not a request."""
    require(type(peer_uid) is int and peer_uid > 0 and
            type(allowed_mcp_uid) is int and allowed_mcp_uid > 0 and
            type(helper_uid) is int and helper_uid > 0 and
            allowed_mcp_uid != helper_uid and
            peer_uid == allowed_mcp_uid,
            "DOCKER_PROXY_PEER_CREDENTIALS_DENIED")


def peer_uid(conn: socket.socket) -> int:
    require(conn.family == socket.AF_UNIX, "DOCKER_PROXY_AF_UNIX_REQUIRED")
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                              struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, ValueError, struct.error, AttributeError) as exc:
        raise ProxyDenied("DOCKER_PROXY_PEERCREDS_UNAVAILABLE") from exc
    require(pid > 0 and uid >= 0 and gid >= 0,
            "DOCKER_PROXY_PEERCREDS_INVALID")
    return uid


def dispatch(operation: str) -> dict:
    """Strict allowlist; Docker commands are constants in imported handlers."""
    require(type(operation) is str and operation in OPERATIONS,
            "DOCKER_PROXY_OPERATION_DENIED")
    if operation == "inventory":
        data = inventory.docker_inventory({})
        require(data.get("status") == "READ_ONLY_HOST_DOCKER_INVENTORY"
                and data.get("host_modified") is False,
                "DOCKER_PROXY_INVENTORY_RESULT_DENIED")
        return data
    data = telemetry.docker_stats({})
    require(data.get("status") == "READ_ONLY_DOCKER_RESOURCE_STATS"
            and data.get("write_performed") is False
            and data.get("production_modified") is False,
            "DOCKER_PROXY_STATS_RESULT_DENIED")
    return data


def encode_result(data: dict) -> bytes:
    require(type(data) is dict and
            data.get("status") in {
                "READ_ONLY_HOST_DOCKER_INVENTORY",
                "READ_ONLY_DOCKER_RESOURCE_STATS",
            }, "DOCKER_PROXY_RESULT_SCHEMA_DENIED")
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode("ascii")
    require(len(encoded) <= MAX_REPLY,
            "DOCKER_PROXY_REPLY_TOO_LARGE")
    return encoded + b"\n"


def serve_connection(conn: socket.socket, *, allowed_mcp_uid: int,
                     helper_uid: int) -> bool:
    """One bounded request; no caller-supplied command and no raw exception."""
    conn.settimeout(7)
    try:
        check_peer_uid(peer_uid(conn),
                       allowed_mcp_uid=allowed_mcp_uid,
                       helper_uid=helper_uid)
        packet = bytearray()
        while len(packet) <= MAX_REQUEST:
            chunk = conn.recv(min(MAX_REQUEST + 1 - len(packet), 256))
            if not chunk:
                break
            packet.extend(chunk)
            if b"\n" in chunk:
                break
        operation = parse_request(bytes(packet))
        response = encode_result(dispatch(operation))
    except (ProxyDenied, inventory.DiagnosticDenied, telemetry.MetricsDenied,
            OSError, TypeError, OverflowError, ValueError):
        response = b'{"status":"DOCKER_PROXY_DENIED"}\n'
        success = False
    else:
        success = True
    try:
        conn.sendall(response)
    except OSError:
        return False
    return success


def activated_listener() -> socket.socket:
    """systemd socket activation, exact one FD (3); never bind arbitrary port."""
    require(os.getenv("LISTEN_PID") == str(os.getpid()) and
            os.getenv("LISTEN_FDS") == "1" and
            os.getenv("LISTEN_FDNAMES") in (None, "docker-ro"),
            "DOCKER_PROXY_ACTIVATION_ENV_DENIED")
    listener = socket.socket(fileno=3)
    require(listener.family == socket.AF_UNIX and
            listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1,
            "DOCKER_PROXY_ACTIVATION_SOCKET_DENIED")
    listener.settimeout(4)
    return listener


def serve_activation(*, allowed_mcp_uid: int, helper_uid: int,
                     max_requests: int = 64) -> int:
    """Bounded local service entrypoint; a launcher must verify group and UID."""
    require(type(max_requests) is int and 1 <= max_requests <= 1024,
            "DOCKER_PROXY_REQUEST_LIMIT_DENIED")
    listener = activated_listener()
    processed = 0
    for _ in range(max_requests):
        try:
            conn, _ = listener.accept()
        except socket.timeout:
            break
        with conn:
            serve_connection(conn, allowed_mcp_uid=allowed_mcp_uid,
                             helper_uid=helper_uid)
        processed += 1
    return processed
