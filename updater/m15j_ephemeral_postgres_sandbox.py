"""M15-J3 ephemeral PostgreSQL sandbox on DISPOSABLE GitHub CI Docker only.

A fixed DB readiness/query fixture, NOT a caller-controlled command runner.
No production path, mounted host volume, arbitrary Docker CLI, host port,
host network or persistent DB. Uses one exact OCI digest to start a private
PostgreSQL container and a separate SQL client, in a uniquely named internal
Docker bridge network, all resources bound to a random local run ID.

Live Pi migration: NOT wired. The Docker caller remains host-root-equivalent.
A boolean CI proof is NOT a cryptographic authorization; this module MUST
NOT be installed as an MCP endpoint or executed on a real Pi.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

DOCKER = "/usr/bin/docker"
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
OCI = re.compile(r"[a-z0-9][a-z0-9._/-]{1,160}@sha256:[a-f0-9]{64}\Z")
PROJECT = "fieldwork-m15jdb-"
LABEL_RUN = "org.fieldwork.m15jdb.run"
LABEL_ROLE = "org.fieldwork.m15jdb.role"
NAME_FMT = '{{.Id}}|{{.Name}}|{{index .Config.Labels "org.fieldwork.m15jdb.run"}}|{{index .Config.Labels "org.fieldwork.m15jdb.role"}}|{{.State.Status}}|{{.HostConfig.Privileged}}'
NETWORK_FMT = '{{.Id}}|{{.Name}}|{{index .Labels "org.fieldwork.m15jdb.run"}}|{{.Internal}}'
NETWORK_ENDPOINT_FMT = '{{json .Containers}}'


class SandboxDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise SandboxDenied(code)


def validate(run_id: str, image: str) -> None:
    require(type(run_id) is str and HEX32.fullmatch(run_id) is not None and
            type(image) is str and OCI.fullmatch(image) is not None and
            ("/postgres@" in image or image.startswith("postgres@")),
            "M15J3_FIXED_DB_IMAGE_OR_RUN_ID_REQUIRED")


def names(run_id: str) -> dict:
    require(type(run_id) is str and HEX32.fullmatch(run_id) is not None,
            "M15J3_RUN_ID_DENIED")
    return {"network": PROJECT + run_id + "-net",
            "db": PROJECT + run_id + "-db",
            "test": PROJECT + run_id + "-test"}


def argv_network(run_id: str) -> tuple[str, ...]:
    n = names(run_id)
    return (DOCKER, "network", "create", "--driver", "bridge",
            "--internal", "--label", LABEL_RUN + "=" + run_id,
            n["network"])


def argv_db(run_id: str, image: str) -> tuple[str, ...]:
    validate(run_id, image)
    n = names(run_id)
    return (
        DOCKER, "container", "create", "--name", n["db"],
        "--label", LABEL_RUN + "=" + run_id,
        "--label", LABEL_ROLE + "=db",
        "--network", n["network"], "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "70:70", "--pids-limit", "64", "--memory", "256m",
        "--cpus", "1.0",
        "--tmpfs", "/var/lib/postgresql/data:rw,uid=70,gid=70,mode=0700",
        "--tmpfs", "/var/run/postgresql:rw,uid=70,gid=70,mode=0775",
        "--tmpfs", "/tmp:rw,uid=70,gid=70,mode=1777",
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
        "--env", "PGDATA=/var/lib/postgresql/data/pgdata",
        image,
    )


def argv_test(run_id: str, image: str) -> tuple[str, ...]:
    validate(run_id, image)
    n = names(run_id)
    return (
        DOCKER, "container", "create", "--name", n["test"],
        "--label", LABEL_RUN + "=" + run_id,
        "--label", LABEL_ROLE + "=test",
        "--network", n["network"], "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "70:70", "--pids-limit", "32", "--memory", "96m",
        "--cpus", "0.5",
        image, "psql", "-h", n["db"], "-U", "postgres",
        "-X", "-tAc", "SELECT 1",
    )


def _call(argv: tuple[str, ...], *, expected: tuple[str, ...],
          timeout: int = 35, may_fail: bool = False) -> tuple[int, str]:
    require(type(argv) is tuple and argv == expected and
            argv[0] == DOCKER and 1 <= timeout <= 90 and
            type(may_fail) is bool, "M15J3_DOCKER_ARGV_DENIED")
    try:
        proc = subprocess.run(
            list(argv), cwd="/", shell=False, check=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=timeout,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"})
    except (OSError, subprocess.SubprocessError):
        raise SandboxDenied("M15J3_DOCKER_SUBPROCESS_UNVERIFIED") from None
    require(len(proc.stdout) <= 4096 and
            (may_fail or proc.returncode == 0),
            "M15J3_DOCKER_ERROR_OR_OUTPUT_BOUNDS")
    try:
        return proc.returncode, proc.stdout.decode("ascii").strip()
    except UnicodeError:
        raise SandboxDenied("M15J3_DOCKER_OUTPUT_DENIED") from None


def _checked(argv: tuple[str, ...], timeout: int = 35) -> str:
    return _call(argv, expected=argv, timeout=timeout)[1]


def observe_container(run_id: str, cid: str, role: str) -> str:
    require(type(cid) is str and HEX64.fullmatch(cid) is not None and
            role in ("db", "test"), "M15J3_CONTAINER_ID_DENIED")
    argv = (DOCKER, "container", "inspect", "--format", NAME_FMT, cid)
    parts = _checked(argv).split("|")
    require(len(parts) == 6 and
            parts[0] == cid and parts[1] == "/" + names(run_id)[role] and
            parts[2] == run_id and parts[3] == role and
            parts[4] in ("created", "running", "exited") and
            parts[5] == "false",
            "M15J3_CONTAINER_ID_LABEL_OR_PRIVILEGE_DRIFT")
    return parts[4]


def observe_network(run_id: str, nid: str,
                    *, allowed_ids: set[str]) -> None:
    require(type(nid) is str and HEX64.fullmatch(nid) is not None and
            type(allowed_ids) is set and
            all(type(x) is str and HEX64.fullmatch(x)
                for x in allowed_ids), "M15J3_NETWORK_ID_DENIED")
    argv = (DOCKER, "network", "inspect", "--format", NETWORK_FMT, nid)
    fields = _checked(argv).split("|")
    require(len(fields) == 4 and fields[0] == nid and
            fields[1] == names(run_id)["network"] and
            fields[2] == run_id and fields[3] == "true",
            "M15J3_NETWORK_ID_OR_OWNERSHIP_DRIFT")
    endpoint_cmd = (DOCKER, "network", "inspect",
                    "--format", NETWORK_ENDPOINT_FMT, nid)
    data = _checked(endpoint_cmd)
    require(len(data) <= 4096, "M15J3_NETWORK_ENDPOINTS_TOO_LARGE")
    try:
        endpoints = json.loads(data)
    except ValueError:
        raise SandboxDenied("M15J3_NETWORK_ENDPOINT_JSON_DENIED") from None
    require(endpoints is None or (
                type(endpoints) is dict and
                all(type(k) is str and HEX64.fullmatch(k) is not None
                    and k in allowed_ids for k in endpoints)),
            "M15J3_FOREIGN_NETWORK_ENDPOINT_DENIED")


def run_isolated_database(*, run_id: str, image: str,
                          ci_disposable_host: bool,
                          source_locally_trusted: bool) -> dict:
    """CI-only. No MCP-supplied command, image, resource ID or path."""
    require(ci_disposable_host is True and
            source_locally_trusted is True and
            os.geteuid() != 0, "M15J3_LOCAL_DISPOSABLE_NONROOT_ONLY")
    validate(run_id, image)
    cid_db = cid_test = nid = None
    success = False
    cleanup_errors = []
    cleanup = []
    try:
        nid = _checked(argv_network(run_id))
        require(HEX64.fullmatch(nid) is not None,
                "M15J3_NETWORK_CREATE_ID_UNVERIFIED")
        observe_network(run_id, nid, allowed_ids=set())
        cid_db = _checked(argv_db(run_id, image))
        require(HEX64.fullmatch(cid_db) is not None,
                "M15J3_DB_CREATE_ID_UNVERIFIED")
        require(observe_container(run_id, cid_db, "db") == "created",
                "M15J3_DB_CREATED_STATE_DRIFT")
        cmd = (DOCKER, "container", "start", cid_db)
        require(_checked(cmd) == cid_db, "M15J3_DB_START_ID_DENIED")
        require(observe_container(run_id, cid_db, "db") == "running",
                "M15J3_DB_DID_NOT_RUN")
        ready = (DOCKER, "container", "exec", "--user", "postgres",
                 cid_db, "pg_isready", "-U", "postgres")
        for _ in range(30):
            rc, _ = _call(ready, expected=ready, timeout=5, may_fail=True)
            if rc == 0:
                break
            time.sleep(1)
        else:
            raise SandboxDenied("M15J3_DB_NOT_READY")
        cid_test = _checked(argv_test(run_id, image))
        require(HEX64.fullmatch(cid_test) is not None,
                "M15J3_TEST_CREATE_ID_UNVERIFIED")
        require(observe_container(run_id, cid_test, "test") == "created",
                "M15J3_TEST_CREATED_STATE_DRIFT")
        start = (DOCKER, "container", "start", cid_test)
        require(_checked(start) == cid_test,
                "M15J3_TEST_START_ID_DENIED")
        wait = (DOCKER, "container", "wait", cid_test)
        require(_checked(wait, timeout=45) == "0",
                "M15J3_SQL_TEST_NOT_PASS")
        logs = (DOCKER, "container", "logs", cid_test)
        require(_checked(logs) == "1", "M15J3_SQL_TEST_RESULT_DENIED")
        require(observe_container(run_id, cid_test, "test") == "exited",
                "M15J3_SQL_TEST_NOT_EXITED")
        observe_network(run_id, nid, allowed_ids={cid_db, cid_test})
        success = True
    finally:
        # Deterministic resource ownership check BEFORE every removal.
        # A daemon timeout can create an object without returning its ID;
        # in that case it is NOT safe to search by name and delete it.
        for role, cid in (("test", cid_test), ("db", cid_db)):
            if cid is None or HEX64.fullmatch(cid) is None:
                continue
            try:
                observe_container(run_id, cid, role)
                cmd = (DOCKER, "container", "rm", "--force", cid)
                require(_checked(cmd) == cid, "M15J3_REMOVE_ID_MISMATCH")
                cleanup.append(role)
            except (SandboxDenied, ValueError):
                cleanup_errors.append(role)
        if nid is not None and HEX64.fullmatch(nid):
            try:
                observe_network(run_id, nid, allowed_ids=set())
                rm = (DOCKER, "network", "rm", nid)
                require(_checked(rm) == nid, "M15J3_NETWORK_REMOVE_ID_DENIED")
                cleanup.append("network")
            except (SandboxDenied, ValueError):
                cleanup_errors.append("network")
    require(not cleanup_errors and cleanup == ["test", "db", "network"],
            "M15J3_CLEANUP_NOT_INDEPENDENTLY_CONFIRMED")
    require(success, "M15J3_SANDBOX_SQL_NOT_VERIFIED")
    return {"status": "M15J3_EPHEMERAL_POSTGRES_SQL_PASS",
            "network_created_and_removed": True,
            "db_container_removed": True, "test_container_removed": True,
            "sql_query_verified": True, "db_volume_persistent": False,
            "host_bind_mount_used": False, "production_modified": False,
            "real_pi_executed": False, "m12_parity_verified": False,
            "m15e_activation_authorized": False,
            "rootful_docker_privilege_removed": False}
