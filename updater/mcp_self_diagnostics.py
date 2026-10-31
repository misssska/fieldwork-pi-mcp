"""FieldWork MCP self-service diagnostics: read-only, narrow, sanitized.

Candidate module for an *independently locally approved* MCP extension.
Never writes the FieldWork project, MCP installation, Docker resources, or
Tunnel configuration. The caller may review installed MCP source control flow
without extracting raw literals or secrets into ChatGPT.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HOME_REL = Path(".local/share/fieldwork-pi-mcp/v0.6.1")
ALLOWED_MODULES = frozenset({
    "sandbox_command.py", "runtime_runner.py", "fieldwork_mcp.py",
    "stage_manager.py", "stage_async.py", "stage_inspect.py",
    "stage_start_async.py",
})
SAFE_LITERALS = frozenset({
    "docker", "run", "rm", "-f", "--rm", "--name", "--network",
    "none", "container", "ls", "--all", "inspect", "--format",
    "DOCKER_TIMEOUT", "RUNTIME_CLEANUP_FAILED",
    "SANDBOX_COMMAND_FAIL", "SANDBOX_COMMAND_PASS",
    "test_container",
})
IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{0,79}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_SOURCE = 262144
MAX_OUTPUT = 50000
MAX_DOCKER_OUTPUT = 512000
MAX_DOCKER_ROWS = 128
DOCKER = "/usr/bin/docker"


class DiagnosticDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise DiagnosticDenied(code)


def _args(value: object, keys: set[str]) -> dict:
    require(type(value) is dict and set(value) == keys, "ARGS_SCHEMA_DENIED")
    return value


def _fixed_source(name: str) -> bytes:
    require(type(name) is str and name in ALLOWED_MODULES,
            "SOURCE_NOT_ALLOWED")
    require(os.geteuid() != 0, "ROOT_DENIED")
    root = Path.home()
    require(root.is_absolute() and not root.is_symlink(), "HOME_INVALID")
    for part in HOME_REL.parts:
        root = root / part
        require(root.is_dir() and not root.is_symlink(),
                "MCP_DIR_INVALID")
    p = root / name
    require(p.is_file() and not p.is_symlink(), "SOURCE_UNAVAILABLE")
    st = p.stat()
    require(st.st_uid == os.geteuid() and
            not (stat.S_IMODE(st.st_mode) & 0o022), "SOURCE_PERMISSION_DENIED")
    require(0 < st.st_size <= MAX_SOURCE, "SOURCE_SIZE_DENIED")
    data = p.read_bytes()
    require(len(data) == st.st_size, "SOURCE_CHANGED_ON_READ")
    return data


class _RedactLiterals(ast.NodeTransformer):
    def visit_Constant(self, node):
        v = node.value
        if type(v) is str and v in SAFE_LITERALS:
            return node
        if isinstance(v, (str, bytes, int, float, complex)):
            return ast.copy_location(ast.Constant(value="<REDACTED>"), node)
        return node


def source_review(args: object) -> dict:
    """One explicit module/function: SHA + masked AST, never raw source."""
    a = _args(args, {"module", "function"})
    name, func = a["module"], a["function"]
    require(type(func) is str and IDENT.fullmatch(func) is not None,
            "FUNCTION_NAME_DENIED")
    data = _fixed_source(name)
    digest = hashlib.sha256(data).hexdigest()
    try:
        tree = ast.parse(data, filename=name)
    except (UnicodeError, SyntaxError) as exc:
        raise DiagnosticDenied("SOURCE_AST_INVALID") from exc
    matching = [n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == func]
    require(len(matching) == 1, "FUNCTION_NOT_UNIQUE_OR_MISSING")
    import copy
    node = _RedactLiterals().visit(copy.deepcopy(matching[0]))
    rendered = ast.unparse(node)
    require(len(rendered) <= MAX_OUTPUT, "FUNCTION_OUTPUT_TOO_LARGE")
    return {
        "status": "READ_ONLY_SOURCE_AST",
        "module": name,
        "function": func,
        "sha256": digest,
        "source_start_line": matching[0].lineno,
        "source_end_line": matching[0].end_lineno,
        "redacted_ast": rendered,
        "source_executed": False,
        "mcp_modified": False,
        "production_modified": False,
    }


def source_inventory(args: object) -> dict:
    """Give exact hashes and top-level method names without code bodies."""
    _args(args, set())
    entries = []
    for name in sorted(ALLOWED_MODULES):
        try:
            data = _fixed_source(name)
            tree = ast.parse(data, filename=name)
        except (DiagnosticDenied, UnicodeError, SyntaxError):
            continue
        functions = [n.name for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and IDENT.fullmatch(n.name) is not None]
        entries.append({"module": name, "sha256": hashlib.sha256(data).hexdigest(),
                        "functions": functions[:80]})
    return {"status": "READ_ONLY_MCP_SOURCE_INVENTORY", "modules": entries,
            "mcp_modified": False, "production_modified": False}


def docker_inventory(args: object) -> dict:
    """Host read-only docker ps; no host shell, arbitrary argv or Docker writes."""
    _args(args, set())
    require(os.geteuid() != 0, "ROOT_DENIED")
    command = [DOCKER, "--host", "unix:///var/run/docker.sock",
               "container", "ls", "--all", "--no-trunc",
               "--format", "{{json .}}"]
    try:
        result = subprocess.run(
            command, cwd="/", env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiagnosticDenied("DOCKER_QUERY_FAILED") from exc
    require(result.returncode == 0 and
            len(result.stdout) <= MAX_DOCKER_OUTPUT,
            "DOCKER_QUERY_FAILED_OR_BOUNDS")
    try:
        lines = result.stdout.decode("utf-8").splitlines()
        require(len(lines) <= MAX_DOCKER_ROWS, "DOCKER_ROWS_OVER_LIMIT")
        rows = []
        for line in lines:
            d = json.loads(line)
            require(type(d) is dict, "DOCKER_SCHEMA_INVALID")
            cid = d.get("ID")
            state = d.get("State")
            name = d.get("Names")
            created = d.get("CreatedAt")
            require(type(cid) is str and HEX64.fullmatch(cid.lower()) and
                    type(state) is str and type(name) is str and
                    type(created) is str, "DOCKER_SCHEMA_INVALID")
            # Report names only for the FieldWork test/project prefix;
            # mask unrelated workloads and all Docker labels and mounts.
            disclose_name = (len(name) <= 100 and
                             bool(re.fullmatch(r"fieldwork[-_][a-zA-Z0-9_.-]+", name)))
            rows.append({
                "id": cid.lower(),
                "name": name if disclose_name else "<OTHER_CONTAINER>",
                "state": state if state in
                         {"created", "running", "restarting", "paused",
                          "exited", "dead"} else "unknown",
                "created": created[:48],
            })
        require(len({r["id"] for r in rows}) == len(rows),
                "DUPLICATE_CONTAINER_IDS")
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise DiagnosticDenied("DOCKER_OUTPUT_INVALID") from exc
    return {
        "status": "READ_ONLY_HOST_DOCKER_INVENTORY",
        "total": len(rows),
        "rows": rows,
        "inventory_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "host_modified": False,
        "production_modified": False,
        "container_removal_authorized": False,
        "sandbox_test_retry_authorized": False,
    }
