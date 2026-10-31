"""Content-addressed, fail-closed canary overlay *planner*.

Only operates on explicitly supplied in-memory bytes. The caller MUST source
base_commit and base_files independently from a clean, pinned, separate Git
tree. Never trust a remote-reported base revision or filesystem contents.

Does not read/modify /opt/fieldwork, extract ZIPs, spawn processes, install,
start Docker, run source code, or persist artifacts. Produced source bytes must
only be consumed by a separate, approved isolated stage materializer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from . import canary_archive_qualifier as qualifier


@dataclass(frozen=True)
class PreparedOverlay:
    """In-memory source changes and non-secret review receipt, not deployed."""
    files: dict[str, bytes]
    receipt: dict

    def __repr__(self) -> str:
        return f"PreparedOverlay(status={self.receipt['status']!r}, source_hidden=True)"


def prepare(*, archive_bytes: bytes, archive_sha256: str,
            independently_observed_commit: str,
            observed_base_files: Mapping[str, bytes | None]) -> PreparedOverlay:
    """Reject any target changed since the expected pinned base snapshot.

    observed_base_files must contain EXACTLY the paths from the verified archive.
    None means independently established nonexistence in that Git revision,
    not a missing read or failed inspection.
    """
    q = qualifier
    report = q.qualify_bytes(archive_bytes, archive_sha256)
    q.require(type(independently_observed_commit) is str and
              q.HEX40.fullmatch(independently_observed_commit) is not None,
              "OBSERVED_GIT_COMMIT_INVALID")
    q.require(report["base_commit"] == independently_observed_commit,
              "CANARY_BASE_COMMIT_DRIFT")
    entries = report["files"]
    paths = [e["path"] for e in entries]
    q.require(type(observed_base_files) is dict and
              set(observed_base_files) == set(paths),
              "OBSERVED_BASE_MAP_INCOMPLETE")
    out: dict[str, bytes] = {}
    for entry in entries:
        path = entry["path"]
        old = observed_base_files[path]
        previous = entry["previous_sha256"]
        q.require(old is None or type(old) is bytes,
                  "OBSERVED_BASE_FILE_INVALID")
        if old is None:
            q.require(previous is None, "BASE_FILE_MISSING")
        else:
            q.require(0 < len(old) <= q.MAX_FILE,
                      "OBSERVED_BASE_FILE_SIZE_DENIED")
            q.require(previous is not None,
                      "UNDECLARED_OVERWRITE_DENIED")
            q.require(q.digest(old) == previous,
                      "BASE_FILE_SHA256_DRIFT")
        # ZIP was already checked, including symlinks, duplicates, sizes,
        # checksums and maximal expanded bytes. Re-read only into memory.
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            raw = q._read_bounded(archive, archive.getinfo(path), q.MAX_FILE)
        q.require(len(raw) == entry["size"] and
                  q.digest(raw) == entry["sha256"], "SOURCE_RECHECK_FAILED")
        q.require(old is None or raw != old, "REDUNDANT_SOURCE_PATCH_DENIED")
        out[path] = raw

    canonical = json.dumps({
        "schema": 1, "base_commit": independently_observed_commit,
        "artifact_sha256": archive_sha256,
        "file_sha256": {e["path"]: e["sha256"] for e in entries},
        "previous_sha256": {e["path"]: e["previous_sha256"] for e in entries},
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return PreparedOverlay(files=out, receipt={
        "status": "CANARY_OVERLAY_PREPARED_NOT_MATERIALIZED",
        "base_commit": independently_observed_commit,
        "archive_sha256": archive_sha256,
        "overlay_plan_sha256": hashlib.sha256(canonical).hexdigest(),
        "changed_paths": paths,
        "changed_file_count": len(paths),
        "source_executed": False,
        "stage_written": False,
        "canary_started": False,
        "production_modified": False,
    })
