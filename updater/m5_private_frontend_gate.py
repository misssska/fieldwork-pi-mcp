"""M5: preflight and postflight for a trusted private-repository frontend CI.

This contract does not execute npm, Docker, or release commands. It is intended
for a disposable GitHub-hosted runner and no user-supplied commands. The source
under test stays in the caller's *private* repository; no application bytes are
uploaded to the public MCP repository. Never run this against the live Pi.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

try:
    from updater.m5_native_vitest_receipt_contract import (
        verify as verify_vitest_receipt, PASS_FILE, ANSI, ReceiptRejected,
    )
except ModuleNotFoundError:
    from m5_native_vitest_receipt_contract import (
        verify as verify_vitest_receipt, PASS_FILE, ANSI, ReceiptRejected,
    )

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
TEST_PATH = re.compile(r"frontend/src/(?:[a-zA-Z0-9_-][a-zA-Z0-9_.-]*/)*[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\.test\.(?:ts|tsx)\Z")
REQUIRED = frozenset({
    "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.ts",
    "frontend/src/components/DocumentViewer.test.tsx",
    "frontend/src/components/PhotoGalleryM5.test.tsx",
    "frontend/src/components/PhotoGallery.tsx",
})
SCRIPTS = {
    "typecheck": "tsc -p tsconfig.app.json --noEmit --pretty false && tsc -p tsconfig.node.json --noEmit --pretty false",
    "lint": "eslint .",
    "test": "vitest run",
    "build": "npm run typecheck && vite build",
}
MAX_SOURCE = 8_388_608

class M5PrivateCIGateDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise M5PrivateCIGateDenied(code)


def git(root: Path, *args: str) -> str:
    """Only fixed Git commands, never Git hooks or shell."""
    require(args in (("rev-parse", "HEAD"),
                     ("rev-parse", "--show-toplevel"),
                     ("ls-files", "-z", "--", "frontend/"),
                     ("status", "--porcelain", "--untracked-files=all"),
                     ("diff", "--quiet", "--", "frontend/")),
            "M5_GIT_COMMAND_NOT_ALLOWLISTED")
    try:
        p = subprocess.run(["git", "-C", str(root), *args],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=20,
                           check=False, shell=False,
                           env={**os.environ, "GIT_OPTIONAL_LOCKS": "0",
                                "GIT_CONFIG_NOSYSTEM": "1"})
    except (OSError, subprocess.SubprocessError):
        raise M5PrivateCIGateDenied("M5_GIT_OPERATION_FAILED") from None
    require(p.returncode == 0 and len(p.stdout) <= 2_000_000,
            "M5_GIT_FAIL_OR_OUTPUT_BOUNDS")
    return p.stdout.decode("utf-8")


def path_file(root: Path, rel: str) -> Path:
    require(type(rel) is str and rel.startswith("frontend/") and
            len(rel) <= 256 and "\\" not in rel and
            all(t not in ("", ".", "..") for t in PurePosixPath(rel).parts),
            "M5_INVALID_SOURCE_PATH")
    current = root
    for segment in PurePosixPath(rel).parts:
        current = current / segment
        require(not current.is_symlink(), "M5_SYMLINK_PATH_DENIED")
    require(current.is_file() and 0 < current.stat().st_size <= MAX_SOURCE,
            "M5_SOURCE_NOT_REGULAR_OR_BOUNDED")
    require(current.resolve().is_relative_to(root.resolve()),
            "M5_SOURCE_PATH_ESCAPE")
    return current


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root(root: Path) -> Path:
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
            "M5_WORKSPACE_NOT_CANONICAL")
    require(root.resolve() == root and
            git(root, "rev-parse", "--show-toplevel").strip() == str(root),
            "M5_WORKSPACE_NOT_GIT_ROOT")
    return root


def _source_files(root: Path) -> tuple[set[str], set[str]]:
    data = git(root, "ls-files", "-z", "--", "frontend/")
    files = set(data.rstrip("\x00").split("\x00"))
    require(REQUIRED.issubset(files) and all(isinstance(s, str) for s in files),
            "M5_REQUIRED_TRACKED_SOURCES_MISSING")
    tests = {p for p in files if TEST_PATH.fullmatch(p)}
    require(len(tests) >= 2 and all(p.startswith("frontend/src/") for p in tests),
            "M5_TRACKED_TEST_FILES_MISSING")
    return files, tests


def _source_hashes(root: Path, files: set[str]) -> dict[str, str]:
    # Only bounded tracked test files and six exact CI config paths are accessed.
    return {p: sha(path_file(root, p).read_bytes()) for p in sorted(files)}


def preflight(*, workspace: Path, expected_commit: str,
              repository_private: bool, runner_environment: str,
              github_actions: bool) -> dict:
    require(repository_private is True and runner_environment == "github-hosted"
            and github_actions is True, "M5_PRIVATE_DISPOSABLE_GH_RUNNER_REQUIRED")
    require(type(expected_commit) is str and HEX40.fullmatch(expected_commit) is not None,
            "M5_EXPECTED_COMMIT_REQUIRED")
    root = _root(workspace)
    require(git(root, "rev-parse", "HEAD").strip() == expected_commit,
            "M5_HEAD_SHA_NOT_EXACT")
    require(git(root, "status", "--porcelain", "--untracked-files=all") == "",
            "M5_UNCLEAN_SOURCE_WORKTREE")
    files, tests = _source_files(root)
    package = json.loads(path_file(root, "frontend/package.json").read_text())
    lock = json.loads(path_file(root, "frontend/package-lock.json").read_text())
    require(type(package) is dict and package.get("private") is True and
            package.get("scripts") == SCRIPTS and
            package.get("devDependencies", {}).get("vitest") == "3.2.7" and
            lock.get("packages", {}).get("node_modules/vitest", {}).get("version") == "3.2.7",
            "M5_NPM_SCRIPTS_OR_VITEST_LOCK_DRIFT")
    vite = path_file(root, "frontend/vite.config.ts").read_text()
    require("src/**/*.test.{ts,tsx}" in vite,
            "M5_VITEST_DISCOVERY_CONTRACT_DRIFT")
    tracked = tests | REQUIRED
    hashes = _source_hashes(root, tracked)
    return {"status": "M5_PRIVATE_FRONTEND_PREFLIGHT_PASS",
            "commit": expected_commit, "source_hashes": hashes,
            "test_files": sorted(tests), "test_file_count": len(tests),
            "private_ci_only": True,
            "production_access": False, "release_authorized": False}


def postflight(*, workspace: Path, expected_commit: str,
               preflight_receipt: dict, log: str,
               repository_private: bool, runner_environment: str,
               github_actions: bool) -> dict:
    require(repository_private is True and runner_environment == "github-hosted"
            and github_actions is True, "M5_PRIVATE_DISPOSABLE_GH_RUNNER_REQUIRED")
    require(type(preflight_receipt) is dict and
            preflight_receipt.get("status") == "M5_PRIVATE_FRONTEND_PREFLIGHT_PASS" and
            preflight_receipt.get("commit") == expected_commit and
            HEX40.fullmatch(expected_commit or "") is not None,
            "M5_PREFLIGHT_RECEIPT_INVALID")
    root = _root(workspace)
    require(git(root, "rev-parse", "HEAD").strip() == expected_commit,
            "M5_POSTFLIGHT_HEAD_CHANGED")
    require(git(root, "diff", "--quiet", "--", "frontend/") == "",
            "M5_TRACKED_FRONTEND_WAS_MODIFIED")
    files, tests = _source_files(root)
    require(sorted(tests) == preflight_receipt.get("test_files") and
            _source_hashes(root, tests | REQUIRED) == preflight_receipt.get("source_hashes"),
            "M5_SOURCE_OR_TEST_MANIFEST_DRIFT")
    try:
        result = verify_vitest_receipt(log)
    except (ReceiptRejected, ValueError) as exc:
        raise M5PrivateCIGateDenied("M5_VITEST_RECEIPT_REJECTED") from exc
    normalized = ANSI.sub("", log).replace("\r\n", "\n")
    shown = {"frontend/" + p for p, _ in PASS_FILE.findall(normalized)}
    require(shown == tests, "M5_SILENT_TEST_COLLECTION_GAP")
    return {"status": "M5_FULL_PRIVATE_FRONTEND_CI_PASS",
            "commit": expected_commit,
            "tests": result["tests"], "test_files": len(tests),
            "source_manifest_sha256": sha(json.dumps(preflight_receipt["source_hashes"],
                                                sort_keys=True).encode()),
            "full_frontend_only": True,
            "backend_pg_migrations_tested": False,
            "release_authorized": False,
            "production_access": False}


def main() -> None:
    require(len(sys.argv) == 5 and sys.argv[1] in ("preflight", "postflight"),
            "M5_COMMAND_ONLY_PREFLIGHT_OR_POSTFLIGHT")
    command, workspace, expected_commit, receipt_path = sys.argv[1:]
    env = os.environ
    common = dict(workspace=Path(workspace), expected_commit=expected_commit,
                  repository_private=env.get("M5_REPOSITORY_PRIVATE") == "true",
                  runner_environment=env.get("RUNNER_ENVIRONMENT", ""),
                  github_actions=env.get("GITHUB_ACTIONS") == "true")
    path = Path(receipt_path)
    require(path.is_absolute() and path.name == "m5-ci-receipt.json" and
            path.parent.is_dir() and not path.is_symlink(),
            "M5_RECEIPT_DESTINATION_DENIED")
    if command == "preflight":
        outcome = preflight(**common)
        path.write_text(json.dumps(outcome, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)
        print("M5_PRIVATE_SOURCE_AND_TEST_MANIFEST_PREFLIGHT_PASS")
    else:
        require(path.is_file(), "M5_PREFLIGHT_RECEIPT_MISSING")
        logpath = path.with_name("m5-frontend-test.log")
        require(logpath.is_file() and not logpath.is_symlink() and
                logpath.stat().st_size <= 12_000_000,
                "M5_FRONTEND_TEST_LOG_MISSING_OR_TOO_BIG")
        outcome = postflight(preflight_receipt=json.loads(path.read_text()),
                             log=logpath.read_text(encoding="utf-8"), **common)
        print(json.dumps(outcome, sort_keys=True))

if __name__ == "__main__":
    main()
