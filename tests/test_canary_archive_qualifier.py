"""Negative-first ZIP and SHA256 tests; no host writes outside temporary home."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from updater import canary_archive_qualifier as q
from updater import artifact_inbox as inbox

BASE = "a" * 40
TID = "9" * 32
GOOD = {
    "frontend/src/components/PhotoGallery.tsx": b"export function Gallery(){return null;}\n",
    "server/app/m5_photo.py": b"def check():\n    return True\n",
}


def makezip(files=None, *, manifest=None, extra=None, symlink=None,
            compression=zipfile.ZIP_DEFLATED):
    files = GOOD if files is None else files
    entries = [{"path": p, "size": len(raw), "sha256": q.digest(raw)}
               for p, raw in sorted(files.items())]
    declaration = ({"schema": 1, "kind": q.KIND, "base_commit": BASE,
                    "files": entries} if manifest is None else manifest)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=compression) as z:
        z.writestr("MANIFEST.json", json.dumps(declaration, sort_keys=True))
        for name, payload in files.items():
            if name == symlink:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                info.compress_type = compression
                z.writestr(info, payload)
            else:
                z.writestr(name, payload)
        if extra is not None:
            name, payload = extra
            z.writestr(name, payload)
    return mem.getvalue()


class StaticArchiveTests(unittest.TestCase):
    def check(self, data: bytes):
        return q.qualify_bytes(data, q.digest(data))

    def test_valid_overlay_is_inert(self):
        result = self.check(makezip())
        self.assertEqual(result["status"], "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED")
        self.assertEqual(result["base_commit"], BASE)
        self.assertEqual(result["source_file_count"], 2)
        self.assertEqual(result["paths"], sorted(GOOD))
        for key in ("sandbox_tested", "canary_deployed",
                    "production_modified", "execution_authorized"):
            self.assertFalse(result[key])

    def test_modified_archive_hash_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "ARCHIVE_HASH_MISMATCH"):
            q.qualify_bytes(makezip(), "f" * 64)

    def test_traversal_and_protected_paths_denied(self):
        for path in ("../etc/shadow", "server/app/../../evil.py",
                     "/opt/fieldwork/server/app/main.py",
                     "frontend/src/.env", "frontend/src/evil.sh",
                     "frontend/src/../../.github/workflows/ci.yml",
                     "server/app/evil.py/../main.py",
                     "Dockerfile", "server/app/other.py\\hack"):
            with self.subTest(path=path), self.assertRaisesRegex(
                q.QualificationDenied, "UNAPPROVED_ARCHIVE_MEMBER|SOURCE_PATH_DENIED"
            ):
                self.check(makezip({path: b"unsafe\n"}))

    def test_undeclared_extra_member_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "ARCHIVE_MANIFEST_SET_MISMATCH"):
            self.check(makezip(extra=("server/app/extra.py", b"pass\n")))

    def test_duplicate_archive_member_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "DUPLICATE_ARCHIVE_MEMBER"):
            self.check(makezip(extra=("server/app/m5_photo.py", b"pass\n")))

    def test_symlink_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "ARCHIVE_SPECIAL_FILE_DENIED"):
            self.check(makezip(symlink="server/app/m5_photo.py"))

    def test_manifest_hash_mismatch_denied(self):
        files = GOOD
        entries = [{"path": path, "size": len(blob), "sha256": "0" * 64}
                   for path, blob in sorted(files.items())]
        bad = {"schema": 1, "kind": q.KIND,
               "base_commit": BASE, "files": entries}
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "SOURCE_HASH_MISMATCH"):
            self.check(makezip(manifest=bad))

    def test_manifest_is_pinned_to_base_commit(self):
        m = {"schema": 1, "kind": q.KIND, "base_commit": "main",
             "files": [{"path": p, "size": len(blob), "sha256": q.digest(blob)}
                       for p, blob in sorted(GOOD.items())]}
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "BASE_COMMIT_INVALID"):
            self.check(makezip(manifest=m))

    def test_binary_and_invalid_python_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "BINARY_SOURCE_DENIED"):
            self.check(makezip({"server/app/blob.py": b"\x00\x01"}))
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "SOURCE_SYNTAX_INVALID"):
            self.check(makezip({"server/app/broken.py": b"def (): invalid\n"}))

    def test_size_and_compression_bombs_denied(self):
        big = b"a" * (q.MAX_FILE + 1)
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "ARCHIVE_MEMBER_SIZE_DENIED|SOURCE_SIZE_DENIED"):
            self.check(makezip({"frontend/src/huge.ts": big},
                               compression=zipfile.ZIP_STORED))
        compressed = b"a" * 250_000
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "ARCHIVE_COMPRESSION_RATIO_DENIED"):
            self.check(makezip({"frontend/src/compress.ts": compressed}))

    def test_extra_member_kind_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "UNAPPROVED_ARCHIVE_MEMBER"):
            self.check(makezip(extra=(".github/workflows/run.yml", b"bad")))

    def test_unsorted_manifest_and_duplicate_files_denied(self):
        entries = [{"path": p, "size": len(blob), "sha256": q.digest(blob)}
                   for p, blob in reversed(sorted(GOOD.items()))]
        m = {"schema": 1, "kind": q.KIND, "base_commit": BASE, "files": entries}
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "MANIFEST_ORDER_NOT_CANONICAL"):
            self.check(makezip(manifest=m))
        m["files"] = [entries[0], entries[0]]
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "DUPLICATE_MANIFEST_PATH"):
            self.check(makezip(manifest=m))

    def test_normal_hash_but_unverified_transfer_denied(self):
        if inbox.os.geteuid() == 0:
            self.skipTest("actual root disallowed by inbox")
        with tempfile.TemporaryDirectory() as home:
            with patch.object(inbox.Path, "home", return_value=Path(home)):
                archive = makezip()
                inbox.begin(TID, len(archive), q.digest(archive))
                with self.assertRaisesRegex(q.QualificationDenied,
                                            "TRANSFER_NOT_VERIFIED"):
                    q.qualify_transfer(TID)
                inbox.append(TID, 0, base64.b64encode(archive).decode())
                inbox.finalize(TID)
                qualified = q.qualify_transfer(TID)
                self.assertEqual(qualified["status"], "STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED")
                self.assertEqual(qualified["transfer_id"], TID)


if __name__ == "__main__":
    unittest.main()
