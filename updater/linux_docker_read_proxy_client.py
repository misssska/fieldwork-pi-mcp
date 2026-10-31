"""Read-only MCP-side Docker proxy client for a locally installed helper.

Client has no Docker library, subprocess or direct docker.sock connection.
Only the systemd-owned exact AF_UNIX endpoint is supported in production.
The optional socket_path parameter is solely for isolated integration tests.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket

if __package__:
    from . import linux_docker_read_proxy as protocol
else:
    import linux_docker_read_proxy as protocol

PATH = Path("/run/linux-mcp-docker-proxy.sock")
MAX_REPLY = protocol.MAX_REPLY


class ClientDenied(ValueError):
    pass


def query(operation: str, *, socket_path: Path = PATH) -> dict:
    """Only two no-argument operations. In deployed MCP: call with no path."""
    if type(operation) is not str or operation not in protocol.OPERATIONS:
        raise ClientDenied("DOCKER_CLIENT_OPERATION_NOT_ALLOWED")
    if not isinstance(socket_path, Path) or not socket_path.is_absolute():
        raise ClientDenied("DOCKER_CLIENT_PATH_NOT_ABSOLUTE")
    request = json.dumps({"version":1,"operation":operation},
                         separators=(",",":")).encode("ascii") + b"\n"
    result = bytearray()
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(12)
            conn.connect(str(socket_path))
            conn.sendall(request)
            while len(result) <= MAX_REPLY:
                data=conn.recv(min(8192,MAX_REPLY+1-len(result)))
                if not data:
                    break
                result.extend(data)
                if b"\n" in data:
                    break
    except (OSError, TimeoutError) as exc:
        raise ClientDenied("DOCKER_CLIENT_LOCAL_HELPER_UNAVAILABLE") from exc
    if not result or len(result) > MAX_REPLY or result.count(b"\n") != 1 or not result.endswith(b"\n"):
        raise ClientDenied("DOCKER_CLIENT_RESPONSE_FRAMING_DENIED")
    try:
        parsed=json.loads(result[:-1].decode("ascii"))
    except (UnicodeError,ValueError) as exc:
        raise ClientDenied("DOCKER_CLIENT_RESPONSE_INVALID") from exc
    if type(parsed) is not dict or parsed.get("status") not in {
        "READ_ONLY_HOST_DOCKER_INVENTORY",
        "READ_ONLY_DOCKER_RESOURCE_STATS",
    }:
        raise ClientDenied("DOCKER_CLIENT_OPERATION_DENIED_BY_HELPER")
    if operation=="inventory" and (parsed["status"]!="READ_ONLY_HOST_DOCKER_INVENTORY" or
                                   parsed.get("host_modified") is not False):
        raise ClientDenied("DOCKER_CLIENT_INVENTORY_BAD_SCOPE")
    if operation=="resources" and (
        parsed["status"]!="READ_ONLY_DOCKER_RESOURCE_STATS" or
        parsed.get("write_performed") is not False or
        parsed.get("production_modified") is not False
    ):
        raise ClientDenied("DOCKER_CLIENT_RESOURCE_BAD_SCOPE")
    return parsed
