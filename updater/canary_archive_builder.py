"""Deterministic builder for source-only FieldWork canary overlay artifacts.

Runs on the developer side, not as a host Pi MCP command. No deployment,
network, Docker, upload, subprocess or implicit filesystem reads.
The caller supplies explicit source bytes and exact previous-file SHA256s.
"""
from __future__ import annotations

import ast
import io
import json
import zipfile

if __package__:
    from . import canary_archive_qualifier as qualifier
else:
    import canary_archive_qualifier as qualifier


def make_archive(*, base_commit: str, files: dict[str, bytes],
                 previous_sha256: dict[str, str | None]) -> tuple[bytes, dict]:
    require = qualifier.require
    require(type(files) is dict and 1 <= len(files) <= qualifier.MAX_FILES,
            "SOURCE_FILE_COUNT_DENIED")
    require(type(previous_sha256) is dict and
            set(previous_sha256) == set(files),
            "PREVIOUS_FILE_MAP_INCOMPLETE")
    manifest_files = []
    for path in sorted(files):
        data = files[path]
        previous = previous_sha256[path]
        require(qualifier.allowed_path(path), "SOURCE_PATH_DENIED")
        require(type(data) is bytes and 0 < len(data) <= qualifier.MAX_FILE,
                "SOURCE_FILE_SIZE_DENIED")
        require(previous is None or (type(previous) is str and
                qualifier.HEX64.fullmatch(previous) is not None),
                "PREVIOUS_FILE_SHA_INVALID")
        require(b"\x00" not in data, "BINARY_SOURCE_DENIED")
        try:
            source = data.decode("utf-8")
            if path.endswith(".py"):
                ast.parse(source, filename=path)
        except (UnicodeError, SyntaxError) as exc:
            raise qualifier.QualificationDenied("SOURCE_SYNTAX_INVALID") from exc
        manifest_files.append({"path": path, "size": len(data),
                               "sha256": qualifier.digest(data),
                               "previous_sha256": previous})
    manifest = {"schema": 1, "kind": qualifier.KIND,
                "base_commit": base_commit, "files": manifest_files}
    manifest_bytes = (json.dumps(manifest, separators=(",", ":"),
                                 sort_keys=True, ensure_ascii=True) + "\n").encode()
    qualifier.parse_manifest(manifest_bytes)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        for path, content in [("MANIFEST.json", manifest_bytes)] + [
            (name, files[name]) for name in sorted(files)
        ]:
            item = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.external_attr = 0o100600 << 16
            item.compress_type = zipfile.ZIP_STORED
            archive.writestr(item, content)
    data = out.getvalue()
    require(len(data) <= qualifier.MAX_ARCHIVE, "ARCHIVE_TOO_LARGE")
    # Symmetric acceptance: packaged data MUST pass the identical strict
    # checker intended for the Pi, including exact archive member set.
    report = qualifier.qualify_bytes(data, qualifier.digest(data))
    return data, report
