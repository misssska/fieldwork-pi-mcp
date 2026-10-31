"""Read-only BuildKit plan for the reviewed offline FieldWork test appliance.

No Docker execution, download, directory creation, Git modification, secrets
or production access. Locally trusted expected hashes are mandatory.
The returned command is a proposed manual operator action, NOT an MCP tool.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from . import canary_archive_qualifier as q
from . import canary_git_base as base
from . import canary_test_runner as runner

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = q.HEX64
NODE = re.compile(r"node:24-bookworm@sha256:[0-9a-f]{64}\Z")
POSTGRES = re.compile(r"postgres:18-bookworm@sha256:[0-9a-f]{64}\Z")
POLICY = frozenset({"Dockerfile", "fieldwork-test-suite"})


def _sha_file(file: Path, limit: int) -> str:
    q.require(file.is_file() and not file.is_symlink(),
              "APPLIANCE_SOURCE_NOT_REGULAR")
    st = file.stat()
    q.require(st.st_uid == os.geteuid() and
              stat.S_ISREG(st.st_mode) and
              not (stat.S_IMODE(st.st_mode) & 0o022) and
              0 < st.st_size <= limit, "APPLIANCE_SOURCE_MODE_OR_SIZE")
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    q.require(file.stat().st_size == st.st_size,
              "APPLIANCE_SOURCE_CHANGED_DURING_READ")
    return digest


def plan(*, expected_base_commit: str, node_base: str, postgres_base: str,
         expected_policy_sha256: dict[str, str],
         architecture: str = "arm64") -> dict:
    """Produce a fixed build command after strict source and policy checks."""
    q.require(os.geteuid() != 0, "APPLIANCE_ROOT_DENIED")
    q.require(type(expected_base_commit) is str and
              HEX40.fullmatch(expected_base_commit) is not None,
              "APPLIANCE_BASE_PIN_REQUIRED")
    q.require(type(node_base) is str and NODE.fullmatch(node_base) is not None,
              "APPLIANCE_NODE_IMAGE_PIN_REQUIRED")
    q.require(type(postgres_base) is str and
              POSTGRES.fullmatch(postgres_base) is not None,
              "APPLIANCE_POSTGRES_IMAGE_PIN_REQUIRED")
    q.require(architecture in ("arm64", "amd64"),
              "APPLIANCE_ARCHITECTURE_DENIED")
    q.require(type(expected_policy_sha256) is dict and
              set(expected_policy_sha256) == POLICY,
              "APPLIANCE_POLICY_FILE_SET_DENIED")
    for digest in expected_policy_sha256.values():
        q.require(type(digest) is str and HEX64.fullmatch(digest) is not None,
                  "APPLIANCE_POLICY_PIN_INVALID")
    repo = base.fixed_checkout()
    head = base._git(repo, "rev-parse", "--verify", "HEAD^{commit}",
                     max_output=128).decode("ascii").strip()
    q.require(head == expected_base_commit,
              "APPLIANCE_PRIVATE_GIT_HEAD_DRIFT")
    q.require(base._git(repo, "status", "--porcelain=v1",
                        "--untracked-files=all", max_output=65536) == b"",
              "APPLIANCE_PRIVATE_GIT_DIRTY")

    policy_dir = Path(__file__).resolve().parents[1] / "appliance"
    q.require(policy_dir.is_dir() and not policy_dir.is_symlink(),
              "APPLIANCE_POLICY_DIRECTORY_INVALID")
    for file, expected in expected_policy_sha256.items():
        q.require(_sha_file(policy_dir / file, 64 * 1024) == expected,
                  "APPLIANCE_POLICY_SOURCE_DRIFT:" + file)
    hashes = {}
    for binding, rel in runner.DEPENDENCY_FILES.items():
        hashes[binding] = _sha_file(repo / rel, 4 * 1024 * 1024)
    q.require(base._git(repo, "rev-parse", "--verify", "HEAD^{commit}",
                        max_output=128).decode("ascii").strip() == head and
              base._git(repo, "status", "--porcelain=v1",
                        "--untracked-files=all", max_output=65536) == b"",
              "APPLIANCE_PRIVATE_GIT_CHANGED_DURING_PREFLIGHT")
    argv = [
        "docker", "buildx", "build",
        "--platform", "linux/" + architecture,
        "--pull=false",
        "--load",
        "--progress=plain",
        "--build-context", "fieldwork_base=" + str(repo),
        "--build-context", "policy=" + str(policy_dir),
        "--build-arg", "NODE_BASE=" + node_base,
        "--build-arg", "POSTGRES_BASE=" + postgres_base,
        "--build-arg", "FRONTEND_LOCK_SHA256=" + hashes["frontend_lock_sha256"],
        "--build-arg", "BACKEND_REQUIREMENTS_SHA256=" + hashes["backend_requirements_sha256"],
        "--build-arg", "BACKEND_DEV_REQUIREMENTS_SHA256=" + hashes["backend_dev_requirements_sha256"],
        "-f", str(policy_dir / "Dockerfile"),
        "-t", "fieldwork-canary-test-appliance:review-only",
        str(policy_dir),
    ]
    return {
        "status": "APPLIANCE_BUILD_PLAN_PASS_NOT_EXECUTED",
        "base_commit": head,
        "architecture": architecture,
        "policy_sha256": expected_policy_sha256.copy(),
        "dependencies": hashes,
        "argv": argv,
        "build_executed": False,
        "image_approved": False,
        "mcp_modified": False,
        "production_modified": False,
    }
