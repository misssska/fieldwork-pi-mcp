"""Locally authorized, strictly isolated canary test-suite runner.

NOT part of the active Pi MCP server. Do not register this as an MCP tool
before a separate local security review/approval. It uses Docker through the
host account and must never be run as root or with arbitrary CLI input.

It executes only five fixed suites inside ONE locally approved, immutable
offline test-appliance image. The appliance must already contain Node deps,
Python deps, a local ephemeral PostgreSQL harness and the fixed entrypoint
/usr/local/bin/fieldwork-test-suite; this module never installs dependencies.
All canary code is mounted read-only, without network or Docker socket.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from . import artifact_inbox as inbox
from . import canary_archive_qualifier as q
from . import canary_stage_inspect as stage

PIN_REL = Path(".local/state/fieldwork-pi-mcp/approved-test-appliance.json")
TESTS_REL = Path(".local/state/fieldwork-pi-mcp/canary-test-receipts")
IMAGE_RE = re.compile(r"fieldwork-canary-test-appliance@sha256:[a-f0-9]{64}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
SUITES = (
    "frontend-typecheck",
    "frontend-lint",
    "frontend-vitest",
    "frontend-build",
    "backend-pytest-postgres",
)
# In particular, no test gets an externally supplied arbitrary command.
TIME_LIMIT = {
    "frontend-typecheck": 180,
    "frontend-lint": 180,
    "frontend-vitest": 300,
    "frontend-build": 300,
    "backend-pytest-postgres": 600,
}
ENTRYPOINT = "/usr/local/bin/fieldwork-test-suite"
PROFILE = "fieldwork-offline-test-appliance-v1"


def _owner_private(path: Path, *, directory: bool) -> None:
    q.require(not path.is_symlink() and
              (path.is_dir() if directory else path.is_file()),
              "TEST_POLICY_FILE_UNSAFE")
    st = path.stat()
    q.require(st.st_uid == os.geteuid() and
              stat.S_IMODE(st.st_mode) & 0o077 == 0,
              "TEST_POLICY_OWNER_OR_PERMISSIONS_DENIED")


def _config() -> dict:
    q.require(os.geteuid() != 0, "TEST_RUNNER_ROOT_DENIED")
    home = Path.home()
    q.require(home.is_dir() and not home.is_symlink(),
              "HOME_UNSAFE")
    path = home
    for part in PIN_REL.parts[:-1]:
        path = path / part
        q.require(path.is_dir() and not path.is_symlink(),
                  "TEST_POLICY_PARENT_UNSAFE")
    pin = home / PIN_REL
    _owner_private(pin, directory=False)
    q.require(pin.stat().st_size <= 2048, "TEST_POLICY_TOO_BIG")
    try:
        raw = pin.read_bytes()
        config = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise q.QualificationDenied("TEST_POLICY_INVALID") from exc
    q.require(type(config) is dict and set(config) == {
        "schema", "profile", "image", "stage_testing_only",
        "locally_approved"
    }, "TEST_POLICY_SCHEMA_DENIED")
    q.require(type(config["schema"]) is int and config["schema"] == 1 and
              config["profile"] == PROFILE and
              config["stage_testing_only"] is True and
              config["locally_approved"] is True and
              type(config["image"]) is str and
              IMAGE_RE.fullmatch(config["image"]) is not None,
              "TEST_IMAGE_NOT_LOCALLY_APPROVED")
    return config


def _root(tid: str) -> Path:
    inbox._valid_id(tid)
    base = Path.home()
    for index, part in enumerate(TESTS_REL.parts):
        base = base / part
        q.require(not base.is_symlink(),
                  "TEST_RECEIPT_PARENT_SYMLINK")
        if not base.exists():
            base.mkdir(mode=0o700)
        st = base.stat()
        q.require(st.st_uid == os.geteuid() and
                  not (st.st_mode & 0o022),
                  "TEST_RECEIPT_PARENT_MODE_DENIED")
        if index == len(TESTS_REL.parts) - 1:
            _owner_private(base, directory=True)
    dest = base / tid
    q.require(not dest.exists() and not dest.is_symlink(),
              "TEST_ALREADY_ATTEMPTED")
    dest.mkdir(mode=0o700)  # exclusive, crashed/failed runs are not reused
    return dest


def _write(root: Path, report: dict) -> None:
    payload = (json.dumps(report, sort_keys=True,
                          separators=(",", ":")) + "\n").encode()
    q.require(len(payload) <= 16_384, "TEST_RECEIPT_TOO_BIG")
    fd, name = tempfile.mkstemp(prefix=".test-report-", dir=root)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, root / "TEST_REPORT.json")
        inbox._sync_dir(root)
    finally:
        if tmp.exists():
            tmp.unlink()


def _command(tid: str, suite: str, image: str) -> list[str]:
    """Only bounded static Docker args; no shell, arbitrary volume or network."""
    inbox._valid_id(tid)
    q.require(suite in SUITES and type(suite) is str,
              "UNKNOWN_TEST_SUITE")
    q.require(type(image) is str and IMAGE_RE.fullmatch(image) is not None,
              "TEST_IMAGE_NOT_PINNED")
    # Fixed stage root and validated ID, never an external path from MCP.
    source = Path.home() / inbox.STATE.parent / stage.STAGE_NAME / tid
    q.require(source.is_dir() and not source.is_symlink(),
              "TEST_SOURCE_DIRECTORY_UNSAFE")
    uid, gid = os.geteuid(), os.getegid()
    return [
        "docker", "run", "--rm", "--pull=never",
        "--name", "fw-canary-" + tid + "-" + str(SUITES.index(suite)),
        "--network=none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=128", "--memory=2g", "--cpus=2",
        "--user", f"{uid}:{gid}",
        "--mount", f"type=bind,source={source},target=/source,readonly",
        "--tmpfs", f"/work:rw,nosuid,nodev,size=1073741824,uid={uid},gid={gid}",
        "--env", "HOME=/work",
        "--entrypoint", ENTRYPOINT,
        image, suite,
    ]


def _run_docker(argv: list[str], timeout: int) -> tuple[bool, str]:
    """No output capture: test code cannot exfiltrate secrets into receipts.

    Timeout and abnormal exits return a fail-closed result. Docker's --rm
    typically removes a completed container, but an interrupted Docker CLI
    can leave a container behind: inspect manually before retrying.
    """
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=timeout, check=False)
        return (proc.returncode == 0, "EXIT_0" if proc.returncode == 0
                else "NONZERO_EXIT")
    except subprocess.TimeoutExpired:
        return (False, "TIMEOUT_MANUAL_CONTAINER_REVIEW_REQUIRED")
    except (OSError, subprocess.SubprocessError):
        return (False, "DOCKER_LAUNCH_FAILED")


def run(transfer_id: str) -> dict:
    """Locally approved operation, NOT callable from the existing MCP adapter."""
    inbox._valid_id(transfer_id)
    config = _config()  # must have explicit local approval before any command
    baseline = stage.inspect_stage(transfer_id)
    root = _root(transfer_id)
    report = {
        "schema": 1, "status": "TEST_RUNNING",
        "transfer_id": transfer_id,
        "snapshot_tree_sha256": baseline["snapshot_tree_sha256"],
        "base_commit": baseline["base_commit"],
        "image": config["image"],
        "profile": PROFILE,
        "completed_suites": [],
        "all_suites_pass": False,
        "canary_started": False, "production_modified": False,
    }
    _write(root, report)
    for suite in SUITES:
        # Recheck entire source before EACH execution and after each result;
        # never trust stage receipt alone.
        try:
            rechecked = stage.inspect_stage(transfer_id)
            q.require(rechecked["snapshot_tree_sha256"] ==
                      baseline["snapshot_tree_sha256"],
                      "STAGE_CHANGED_BEFORE_TEST")
            argv = _command(transfer_id, suite, config["image"])
            passed, outcome = _run_docker(argv, TIME_LIMIT[suite])
            final = stage.inspect_stage(transfer_id)
            q.require(final["snapshot_tree_sha256"] ==
                      baseline["snapshot_tree_sha256"],
                      "STAGE_CHANGED_DURING_TEST")
        except (OSError, ValueError, inbox.InboxDenied) as exc:
            # Never include exception messages with sensitive paths/details.
            passed, outcome = False, "STAGE_INTEGRITY_OR_POLICY_DENIED"
        report["completed_suites"].append({
            "suite": suite, "passed": passed, "outcome": outcome
        })
        if not passed:
            report["status"] = "TEST_FAILED"
            _write(root, report)
            return report
        _write(root, report)
    report["all_suites_pass"] = True
    report["status"] = "FULL_TEST_PASS_NOT_DEPLOYED"
    _write(root, report)
    return report
