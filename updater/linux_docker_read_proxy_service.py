"""M14D fixed local Docker projection service entrypoint, socket activated.

Only one installed and owned config may set the MCP Unix UID. This daemon
must run as a *separate* non-root helper with Docker access. Its Docker access
is root-equivalent; never share this helper principal with remote MCP or
operator HMAC secrets. Do not activate before stage lifecycle migration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

if __package__:
    from . import linux_docker_read_proxy as proxy
else:
    import linux_docker_read_proxy as proxy

CONFIG = Path("/etc/linux-mcp-docker-proxy/client.json")


class DockerHelperDenied(ValueError):
    pass


def require(ok: bool, code: str):
    if not ok:
        raise DockerHelperDenied(code)


def read_fixed_config(*, config: Path = CONFIG) -> int:
    require(isinstance(config, Path) and config.is_absolute()
            and config.name == "client.json"
            and not config.is_symlink() and config.is_file(),
            "DOCKER_HELPER_CONFIG_PATH_DENIED")
    parent = config.parent
    require(parent.is_dir() and not parent.is_symlink(),
            "DOCKER_HELPER_CONFIG_PARENT_UNSAFE")
    parent_stat = parent.stat()
    require(parent_stat.st_uid in (0, os.geteuid()) and
            not (stat.S_IMODE(parent_stat.st_mode) & 0o022),
            "DOCKER_HELPER_CONFIG_PARENT_PERMISSIONS_DENIED")
    st = config.stat()
    require(st.st_uid in (0, os.geteuid()) and
            st.st_gid == os.getegid() and
            stat.S_IMODE(st.st_mode) in (0o440, 0o640, 0o600) and
            0 < st.st_size <= 512,
            "DOCKER_HELPER_CONFIG_MODE_DENIED")
    fd = os.open(config, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as file:
            raw = file.read(513)
    except OSError as exc:
        raise DockerHelperDenied("DOCKER_HELPER_CONFIG_READ_DENIED") from exc
    require(0 < len(raw) == st.st_size <= 512,
            "DOCKER_HELPER_CONFIG_RACE_OR_SIZE")
    try:
        body = json.loads(raw.decode("ascii"),
                          object_pairs_hook=proxy._unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise DockerHelperDenied("DOCKER_HELPER_CONFIG_JSON_DENIED") from exc
    require(type(body) is dict and set(body) == {"version", "client_uid"}
            and type(body["version"]) is int and body["version"] == 1 and
            type(body["client_uid"]) is int and body["client_uid"] > 0 and
            body["client_uid"] != os.geteuid(),
            "DOCKER_HELPER_CONFIG_SCHEMA_DENIED")
    return body["client_uid"]


def main() -> int:
    try:
        helper_uid = os.geteuid()
        require(helper_uid > 0, "DOCKER_HELPER_ROOT_DENIED")
        client_uid = read_fixed_config()
        proxy.serve_activation(allowed_mcp_uid=client_uid,
                               helper_uid=helper_uid)
        return 0
    except (DockerHelperDenied, proxy.ProxyDenied, OSError) as exc:
        print("DOCKER_HELPER_STOP=" + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
