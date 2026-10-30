"""Read-only static import preflight for the FieldWork admin-rotation tests.

This checks whether explicitly imported local modules are present in the
isolated source snapshot. It never imports or executes FieldWork code, runs
tests, connects to a DB, reads secrets or changes the filesystem.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re


# Mirrors the Pi MCP snapshot exclusion rule for sensitive filenames.
# Never include excluded source modules in the generic photo-test snapshot.
DENY_FILE = re.compile(
    r'(?i)(^\\.env(?:\\.|$)|secret|password|credential|'
    r'(?:^|[._-])token(?:[._-]|$)|(?:^|[._-])key(?:[._-]|$)|'
    r'\\.pem$|\\.p12$|\\.pfx$|\\.crt$|\\.sqlite|\\.db$|'
    r'\\.log$|id_rsa|id_ed25519|\\.bak$|\\.dump$)'
)


class PreflightDenied(RuntimeError):
    pass


def _safe_path(root: Path, relative: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_./-]+", relative) or ".." in Path(relative).parts:
        raise PreflightDenied("INVALID_SOURCE_PATH")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise PreflightDenied("SYMLINK_SOURCE_DENIED")
    return current


def check_admin_imports(server_root: Path) -> dict:
    """Analyze imports in tests/test_admin_rotation.py without importing them.

    Explicit scripts.x imports are conclusive. The from-scripts-import form
    can refer to an attribute, so absence is reported as ambiguous, never
    automatically classified as a missing module.
    """
    root = Path(server_root)
    if not root.is_dir() or root.is_symlink():
        raise PreflightDenied("SOURCE_ROOT_UNSAFE")
    test = _safe_path(root, "tests/test_admin_rotation.py")
    if not test.is_file() or test.stat().st_size > 1_000_000:
        raise PreflightDenied("ADMIN_TEST_MISSING_OR_TOO_LARGE")
    tree = ast.parse(test.read_text(encoding="utf-8"), filename=test.name)
    explicit: set[str] = set()
    ambiguous: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("scripts."):
                    explicit.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module and node.module.startswith("scripts."):
                explicit.add(node.module)
            elif node.module == "scripts":
                for alias in node.names:
                    if alias.name != "*":
                        ambiguous.add("scripts." + alias.name)
    missing: list[str] = []
    present: list[str] = []
    for module in sorted(explicit):
        relative = module.replace(".", "/")
        py = _safe_path(root, relative + ".py")
        pkg = _safe_path(root, relative + "/__init__.py")
        (present if py.is_file() or pkg.is_file() else missing).append(module)
    excluded = sorted(m for m in missing if DENY_FILE.search(m.split(".")[-1] + ".py"))
    actionable = sorted(set(missing) - set(excluded))
    unresolved = sorted(module for module in ambiguous
                        if module not in explicit and
                        not _safe_path(root, module.replace(".", "/") + ".py").is_file() and
                        not _safe_path(root, module.replace(".", "/") + "/__init__.py").is_file())
    return {
        "status": "MISSING_LOCAL_IMPORTS" if actionable else
                  "POLICY_EXCLUDED_IMPORTS" if excluded else
                  "AMBIGUOUS_LOCAL_IMPORTS" if unresolved else
                  "STATIC_IMPORT_PATHS_PRESENT",
        "explicit_missing": actionable,
        "policy_excluded_count": len(excluded),
        "explicit_present": present,
        "ambiguous_from_import": unresolved,
        "executed_code": False,
        "production_modified": False,
    }
