"""M11 SHA-pinned *offline* source patch candidate for the Pi MCP.

The installed sandbox_command.py is NOT checked into this repository.
This transforms only the exact SHA-pinned locally installed bytes and only the
run_command finally/if attempted cleanup block. No file I/O, Docker invocation,
service activation, host writes, or local approval bypass. No installation tool.

The old code treats any docker inspect nonzero return code as 'not present'.
The new code observes container absence using two independent, successful,
exact-name filtered docker container ls invocations; uncertain results fail
closed. This is a candidate pending native installed-source integration tests.
"""
from __future__ import annotations

import ast
import hashlib
import re
import textwrap

PINNED_ACTIVE_SANDBOX_SHA256 = (
    "5255968dac5c0bb8ac3a94eb72f3131ea2081b683974d97db6bb9ddc3d432615"
)
MAX_SOURCE_BYTES = 131072


class CleanupOverlayDenied(ValueError):
    pass


def require(ok: bool, error: str) -> None:
    if not ok:
        raise CleanupOverlayDenied(error)


def _is_rm_call(call: ast.AST) -> bool:
    if not isinstance(call, ast.Call):
        return False
    f = call.func
    if not (isinstance(f, ast.Attribute) and f.attr == "_run"
            and isinstance(f.value, ast.Name) and f.value.id == "r"
            and call.args and isinstance(call.args[0], ast.List)):
        return False
    values = call.args[0].elts
    return (len(values) == 4 and
            isinstance(values[0], ast.Attribute) and
            isinstance(values[0].value, ast.Name) and
            values[0].value.id == "r" and values[0].attr == "DOCKER_BIN" and
            all(isinstance(values[i], ast.Constant) and
                values[i].value == s for i, s in ((1, "rm"), (2, "-f"))) and
            isinstance(values[3], ast.Name) and values[3].id == "test")


def _anchor(source: str) -> ast.If:
    try:
        root = ast.parse(source)
    except SyntaxError as e:
        raise CleanupOverlayDenied("SOURCE_AST_INVALID") from e
    functions = [n for n in root.body
                 if isinstance(n, ast.FunctionDef) and n.name == "run_command"]
    require(len(functions) == 1, "RUN_COMMAND_NOT_UNIQUE")
    fn = functions[0]

    # The only permitted target is 'if attempted:' *inside a finally* of
    # run_command, with the exact legacy 'docker rm -f test' argument pattern.
    matches = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        for branch in node.finalbody:
            if (not isinstance(branch, ast.If) or
                    not isinstance(branch.test, ast.Name) or
                    branch.test.id != "attempted" or branch.orelse):
                continue
            rm_calls = [call for call in ast.walk(branch)
                        if _is_rm_call(call)]
            if len(rm_calls) == 1:
                matches.append(branch)
    require(len(matches) == 1, "LEGACY_CLEANUP_ANCHOR_NOT_UNIQUE")
    target = matches[0]

    # Avoid deleting any extra actions which a later version might add.
    require(len(target.body) == 1 and isinstance(target.body[0], ast.Try),
            "LEGACY_CLEANUP_SHAPE_DRIFT")
    oldtry = target.body[0]
    require(len(oldtry.handlers) == 1 and
            isinstance(oldtry.handlers[0].type, ast.Name) and
            oldtry.handlers[0].type.id == "ValueError" and
            not oldtry.orelse and not oldtry.finalbody,
            "LEGACY_CLEANUP_HANDLER_DRIFT")
    # Confirm only the expected status append branches exist.
    appends = [
        n for n in ast.walk(target)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "append"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "cleanup"
    ]
    require(len(appends) == 2, "LEGACY_CLEANUP_APPEND_DRIFT")
    return target


# A single replacement block, at the existing 'if attempted:' indentation.
# name=^/<test>$ is exact-name Docker filtering, with ID-only results.
# Do not accept nonzero Docker exit code as proof of container absence.
# Two independent successful reads of empty result are required.
# No raw daemon outputs are added to the persistent receipts.
REPLACEMENT = """if attempted:
    _cleanup_absent = True
    try:
        r._run([r.DOCKER_BIN, 'rm', '-f', test], timeout=12)
    except ValueError:
        # Docker may have removed --rm container before, during or after
        # a failed CLI request; verify existence separately.
        pass
    for _cleanup_probe in range(2):
        try:
            _probe_code, _probe_result = r._run(
                [r.DOCKER_BIN, 'container', 'ls', '--all',
                 '--filter', 'name=^/' + test + '$',
                 '--format', '{{.ID}}'],
                timeout=8, output_limit=1024,
            )
            if _probe_code != 0 or _probe_result.strip():
                _cleanup_absent = False
                break
        except ValueError:
            _cleanup_absent = False
            break
    cleanup.append({'object': 'test_container',
                    'ok': _cleanup_absent})"""


def _transform_exact_bytes(source: bytes) -> bytes:
    """Pure transformation; input pin is checked separately in public entry."""
    require(type(source) is bytes and 0 < len(source) <= MAX_SOURCE_BYTES,
            "SOURCE_SIZE_OR_TYPE_DENIED")
    try:
        content = source.decode("utf-8")
    except UnicodeError as e:
        raise CleanupOverlayDenied("SOURCE_UTF8_INVALID") from e
    anchor = _anchor(content)
    lines = content.splitlines(keepends=True)
    start = anchor.lineno - 1
    end = anchor.end_lineno
    require(0 <= start < end <= len(lines), "CLEANUP_SOURCE_RANGE_INVALID")
    oldline = lines[start]
    m = re.fullmatch(r"([ ]*)if attempted:\s*(?:\r?\n)?", oldline)
    require(m is not None, "CLEANUP_INDENT_OR_LINE_DRIFT")
    indent = m.group(1)
    require(len(indent) % 4 == 0 and len(indent) > 0,
            "CLEANUP_INDENT_DENIED")
    # Full-line AST replacement without touching surrounding code.
    replacement = textwrap.indent(REPLACEMENT, indent) + "\n"
    output = "".join(lines[:start]) + replacement + "".join(lines[end:])
    try:
        tree = ast.parse(output)
        compile(tree, "sandbox_command_candidate.py", "exec")
    except (SyntaxError, ValueError) as e:
        raise CleanupOverlayDenied("CANDIDATE_AST_INVALID") from e
    require(output != content and "RUNTIME_CLEANUP_FAILED" in output,
            "CANDIDATE_UNEXPECTED_SOURCE")
    # Guarantee unrelated line sequences are unchanged byte-for-byte.
    require(output.startswith("".join(lines[:start])) and
            output.endswith("".join(lines[end:])),
            "CANDIDATE_UNRELATED_SOURCE_CHANGED")
    return output.encode("utf-8")


def build(installed_source: bytes) -> dict:
    """Offline bytes-only API. Never reads installed file or activates patch."""
    require(type(installed_source) is bytes and
            0 < len(installed_source) <= MAX_SOURCE_BYTES,
            "SOURCE_SIZE_OR_TYPE_DENIED")
    installed_sha = hashlib.sha256(installed_source).hexdigest()
    require(installed_sha == PINNED_ACTIVE_SANDBOX_SHA256,
            "PINNED_INSTALLED_SOURCE_MISMATCH")
    candidate = _transform_exact_bytes(installed_source)
    return {
        "status": "M11_CANDIDATE_ONLY",
        "original_sha256": installed_sha,
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_source": candidate,
        "activation_authorized": False,
        "mcp_modified": False,
        "production_modified": False,
        "tunnel_modified": False,
    }
