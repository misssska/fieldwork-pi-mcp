"""M14C operator-only service entrypoint (local review; NO deployment).

Can be launched under a dedicated non-root Unix account. The configured
request and hashes must originate from the LOCAL trusted staging process,
NOT from MCP or an unauthenticated web request. This process can only sign
one approved manifest and store a local ticket. It CANNOT install code.

The local root path is fixed in production; tests may pass a tmp directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import time

if __package__:
    from . import linux_upgrade_gate as gate
    from . import linux_upgrade_review_ui as review
    from . import linux_upgrade_local_transaction as transaction
else:
    import linux_upgrade_gate as gate
    import linux_upgrade_review_ui as review
    import linux_upgrade_local_transaction as transaction

STATE_ROOT = Path("/var/lib/linux-mcp-operator")
MAX_CONFIG = 16384
MAX_REQUEST = 16384
MAX_SECRET = 4096
REQUIRED_CONFIG = frozenset({
    "host_id", "remote_mcp_euid", "allowed_modules", "locked_modules",
    "active_hashes", "listen_port",
})


class OperatorServiceDenied(ValueError):
    pass


def require(ok: bool, msg: str):
    if not ok:
        raise OperatorServiceDenied(msg)


def read_private(root: Path, name: str, *, limit: int) -> bytes:
    transaction.directory(root)
    require(name in {"config.json", "request.json", "approval_hmac.key",
                     "operator_token.key"}, "OPERATOR_FILE_NAME_DENIED")
    file = root / name
    require(file.is_file() and not file.is_symlink(),
            "OPERATOR_FILE_MISSING_OR_SYMLINK")
    st = file.stat()
    require(st.st_uid == os.geteuid() and
            stat.S_IMODE(st.st_mode) == 0o600 and
            0 < st.st_size <= limit, "OPERATOR_FILE_MODE_OR_SIZE_DENIED")
    fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as f:
            data = f.read(limit + 1)
    except OSError as exc:
        raise OperatorServiceDenied("OPERATOR_FILE_READ_FAILED") from exc
    require(len(data) == st.st_size and len(data) <= limit,
            "OPERATOR_FILE_CHANGED_DURING_READ")
    return data


def decode_json(data: bytes, name: str) -> dict:
    try:
        obj = json.loads(data.decode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise OperatorServiceDenied("OPERATOR_JSON_INVALID") from exc
    require(type(obj) is dict and gate.canon(obj) == data,
            "OPERATOR_JSON_NONCANONICAL")
    return obj


def load_review_session(*, root: Path=STATE_ROOT,
                        now: int | None=None) -> review.ReviewSession:
    require(os.geteuid() != 0, "OPERATOR_ROOT_DENIED")
    transaction.directory(root)
    config = decode_json(read_private(root,"config.json",limit=MAX_CONFIG),
                         "config")
    require(frozenset(config) == REQUIRED_CONFIG,
            "OPERATOR_CONFIG_SCHEMA_DENIED")
    remote_uid = config["remote_mcp_euid"]
    require(type(remote_uid) is int and remote_uid > 0 and
            remote_uid != os.geteuid(), "OPERATOR_NOT_SEPARATE_UID")
    names,locked = config["allowed_modules"],config["locked_modules"]
    require(type(names) is list and type(locked) is list and
            all(type(x) is str for x in names+locked),
            "OPERATOR_MODULE_LIST_DENIED")
    policy = gate.HostPolicy(
        host_id=config["host_id"],
        allowed_modules=frozenset(names),
        locked_modules=frozenset(locked),
    )
    require(len(names) == len(policy.allowed_modules) and
            len(locked) == len(policy.locked_modules),
            "OPERATOR_DUPLICATE_MODULES_DENIED")
    require(type(config["listen_port"]) is int and
            config["listen_port"] == 8767,
            "OPERATOR_PORT_NOT_FIXED")
    hashes = config["active_hashes"]
    require(type(hashes) is dict and
            set(hashes) == policy.allowed_modules,
            "OPERATOR_ACTIVE_HASH_SET_DENIED")
    request = decode_json(
        read_private(root,"request.json",limit=MAX_REQUEST),"request")
    timestamp = int(time.time()) if now is None else now
    plan = gate.validate_plan(request, policy, hashes, timestamp)
    local_secret = read_private(
        root,"approval_hmac.key",limit=MAX_SECRET)
    operator_token = read_private(
        root,"operator_token.key",limit=MAX_SECRET)
    handoff = root / "approved"
    transaction.directory(handoff)
    return review.ReviewSession(
        plan=plan,local_secret=local_secret,
        operator_token=operator_token,handoff=handoff
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local-only Linux MCP approval service")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    require(args.check != args.serve, "OPERATOR_ACTION_REQUIRED")
    try:
        session = load_review_session()
        if args.check:
            print("M14C_LOCAL_REVIEW_CONFIG_PASS host="+session.plan.host_id)
            print("M14C_NO_DEPLOYMENT_PERFORMED")
            return 0
        server = review.create_local_server(session,port=8767)
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            server.server_close()
        return 0
    except (gate.UpgradeDenied,transaction.LocalApplyDenied,
            review.ReviewDenied,OperatorServiceDenied,OSError) as exc:
        detail = str(exc)
        code = detail if detail.isascii() and detail.replace("_","").isalnum() and detail.isupper() else type(exc).__name__
        print("M14C_SERVICE_STOP="+code,file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
