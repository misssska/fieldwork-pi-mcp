"""M15-E: separate-UID, one-shot local approval redemption. NOT an updater.

The operator holds the HMAC key and canonical approval ticket. An independent
executor UID can redeem only the currently pinned plan over AF_UNIX.
Redemption commits a durable nonce tombstone BEFORE answering success.
No shell, Docker API, source install, service restart or remote MCP handler.
The service is NOT installed or registered by this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct
import time

if __package__:
    from . import linux_upgrade_gate as gate
else:
    import linux_upgrade_gate as gate

MAX_REQUEST = 256
MAX_TICKET = 4096
RECEIPT_KEYS = frozenset({"protocol", "plan_sha256"})


class RedemptionDenied(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RedemptionDenied(code)


def _dir(path: Path, *, mode: int) -> None:
    require(isinstance(path, Path) and path.is_absolute(),
            "REDEEM_DIRECTORY_PATH_DENIED")
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid()
            and stat.S_IMODE(st.st_mode) == mode,
            "REDEEM_DIRECTORY_OWNER_MODE_DENIED")


def _read_ticket(path: Path) -> dict:
    require(path.name.endswith(".json") and not path.is_symlink(),
            "REDEEM_TICKET_PATH_DENIED")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise RedemptionDenied("REDEEM_TICKET_OPEN_DENIED") from exc
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid()
                and stat.S_IMODE(st.st_mode) == 0o600
                and 0 < st.st_size <= MAX_TICKET,
                "REDEEM_TICKET_OWNER_MODE_DENIED")
        raw = stream.read(MAX_TICKET + 1)
    require(len(raw) == st.st_size, "REDEEM_TICKET_SIZE_CHANGED")
    try:
        ticket = json.loads(raw.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise RedemptionDenied("REDEEM_TICKET_JSON_DENIED") from exc
    require(type(ticket) is dict and set(ticket) == gate.AUTH_KEYS
            and gate.canon(ticket) == raw, "REDEEM_TICKET_SCHEMA_DENIED")
    return ticket


def _parse_request(raw: bytes, pinned_plan_sha: str) -> None:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST
            and raw.endswith(b"\n"), "REDEEM_REQUEST_SIZE_DENIED")
    try:
        value = json.loads(raw[:-1].decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise RedemptionDenied("REDEEM_REQUEST_JSON_DENIED") from exc
    require(type(value) is dict and frozenset(value) == RECEIPT_KEYS
            and type(value["protocol"]) is int and value["protocol"] == 1
            and type(value["plan_sha256"]) is str
            and value["plan_sha256"] == pinned_plan_sha
            and gate.canon(value) + b"\n" == raw,
            "REDEEM_REQUEST_NOT_PINNED")


def _peer(conn: socket.socket, expected_uid: int) -> int:
    require(hasattr(socket, "SO_PEERCRED"), "REDEEM_LINUX_PEERCRED_REQUIRED")
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    pid, uid, gid = struct.unpack("3i", raw)
    require(pid > 0 and uid == expected_uid and uid != 0
            and uid != os.geteuid(), "REDEEM_PEER_UID_DENIED")
    return uid


class LocalRedeemer:
    """Trust inputs are supplied by a separate, locally owned operator.

    A positive receipt is proof of one-time HMAC ticket redemption only.
    It is explicitly NOT an installation or service activation capability.
    """
    def __init__(self, *, plan: gate.ValidatedPlan, local_secret: bytes,
                 approval_root: Path, spent_root: Path, socket_root: Path,
                 expected_executor_uid: int, expected_executor_gid: int):
        require(isinstance(plan, gate.ValidatedPlan)
                and type(local_secret) is bytes and len(local_secret) >= 32,
                "REDEEM_TRUST_INPUT_DENIED")
        require(type(expected_executor_uid) is int
                and expected_executor_uid > 0
                and expected_executor_uid != os.geteuid()
                and type(expected_executor_gid) is int
                and expected_executor_gid > 0
                and os.getegid() == expected_executor_gid,
                "REDEEM_EXECUTOR_IDENTITY_DENIED")
        _dir(approval_root, mode=0o700)
        _dir(spent_root, mode=0o700)
        _dir(socket_root, mode=0o710)
        require(socket_root.stat().st_gid == expected_executor_gid,
                "REDEEM_SOCKET_GROUP_DENIED")
        require(len({approval_root.resolve(), spent_root.resolve(),
                     socket_root.resolve()}) == 3,
                "REDEEM_DIRECTORY_OVERLAP_DENIED")
        self.plan = plan
        self._secret = local_secret
        self.approval_root = approval_root
        self.spent_root = spent_root
        self.socket_root = socket_root
        self.executor_uid = expected_executor_uid

    def redeem(self, *, request: bytes, peer_uid: int, now: int) -> dict:
        require(type(peer_uid) is int
                and peer_uid == self.executor_uid and peer_uid != 0
                and peer_uid != os.geteuid(), "REDEEM_PEER_UID_DENIED")
        _parse_request(request, self.plan.plan_sha256)
        _dir(self.approval_root, mode=0o700)
        _dir(self.spent_root, mode=0o700)
        ticket = _read_ticket(
            self.approval_root / (self.plan.plan_sha256 + ".json"))
        require(ticket["plan_sha256"] == self.plan.plan_sha256,
                "REDEEM_TICKET_PLAN_MISMATCH")
        nonce = gate.verify_local_approval(
            self.plan, ticket, local_secret=self._secret, now=now,
            spent_nonces=frozenset())
        # Consuming before replying is fail-closed after a power loss:
        # never silently retry a ticket after an uncertain execution.
        target = self.spent_root / nonce
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except FileExistsError as exc:
            raise RedemptionDenied("REDEEM_NONCE_REPLAY_DENIED") from exc
        try:
            with os.fdopen(fd, "wb") as stream:
                receipt = gate.canon({
                    "host_id": self.plan.host_id,
                    "plan_sha256": self.plan.plan_sha256,
                    "commit_sha": self.plan.commit_sha,
                    "consumed_at": now,
                })
                stream.write(receipt)
                stream.flush()
                os.fsync(stream.fileno())
            dir_fd = os.open(self.spent_root, os.O_RDONLY | os.O_DIRECTORY
                             | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            # Do not remove an uncertain nonce after partial write.
            raise RedemptionDenied("REDEEM_DURABILITY_UNCERTAIN")
        return {
            "status": "LOCAL_APPROVAL_REDEEMED_NOT_EXECUTED",
            "host_id": self.plan.host_id,
            "plan_sha256": self.plan.plan_sha256,
            "commit_sha": self.plan.commit_sha,
            "approval_consumed": True,
            "publisher_verified": False,
            "execution_authorized": False,
            "deployment_performed": False,
            "production_modified": False,
        }

    def serve_one(self, *, filename: str = "handoff.sock") -> None:
        """At most one connection; restart requires local socket cleanup.

        Never unlink a preexisting socket, even after abnormal termination.
        The operator must reconcile any uncertain approval before restart.
        """
        require(filename == "handoff.sock", "REDEEM_SOCKET_NAME_DENIED")
        _dir(self.socket_root, mode=0o710)
        path = self.socket_root / filename
        require(not path.exists() and not path.is_symlink(),
                "REDEEM_SOCKET_ALREADY_EXISTS")
        old_mask = os.umask(0o007)
        try:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(path))
                os.chmod(path, 0o660)
                server.listen(1)
                server.settimeout(5)
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(2)
                    try:
                        peer_uid = _peer(conn, self.executor_uid)
                        chunks = []
                        total = 0
                        while True:
                            data = conn.recv(MAX_REQUEST + 2 - total)
                            if not data:
                                break
                            chunks.append(data)
                            total += len(data)
                            if total > MAX_REQUEST or b"\n" in data:
                                break
                        response = self.redeem(
                            request=b"".join(chunks),
                            peer_uid=peer_uid,
                            now=int(time.time()))
                    except (RedemptionDenied, gate.UpgradeDenied,
                            OSError, ValueError):
                        response = {"status": "LOCAL_APPROVAL_REDEMPTION_DENIED",
                                    "execution_authorized": False}
                    conn.sendall(gate.canon(response) + b"\n")
            finally:
                server.close()
                # Socket retained as a deliberate no-restart safety marker.
        finally:
            os.umask(old_mask)
