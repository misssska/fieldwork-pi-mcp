"""M15 portable sidecar packaging negative and reproducibility checks.

Nothing is extracted or installed; no Docker, systemd, Pi or tunnel.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from updater import m15_portable_bundle as m

COMMIT = "a" * 40


def fake_files():
    return {
        name: (f"# fixture for {name}\n").encode("ascii")
        for name in m.FILES
    }


def verified(raw, sha=None):
    return m.inspect_archive(
        raw, trusted_outer_sha256=sha or hashlib.sha256(raw).hexdigest(),
        trusted_source_commit=COMMIT,
    )


class BundleTests(unittest.TestCase):
    def test_exact_manifest_and_deterministic_output(self):
        payload = fake_files()
        first = m.make_archive(payload, source_commit=COMMIT)
        second = m.make_archive(dict(reversed(list(payload.items()))),
                                source_commit=COMMIT)
        self.assertEqual(first, second)
        self.assertEqual(first[:2], b"\\x1f\\x8b")
        self.assertEqual(first[4:8], b"\\0\\0\\0\\0")
        result = verified(first)
        self.assertEqual(result["status"], "M15_OFFLINE_BUNDLE_VERIFIED")
        self.assertEqual(result["files_checked"], len(m.FILES))
        self.assertFalse(result["activation_authorized"])
        self.assertFalse(result["installation_performed"])
        self.assertFalse(result["publisher_signature_verified"])
        self.assertFalse(result["production_modified"])

    def test_external_sha_pin_denies_tampered_byte(self):
        archive = m.make_archive(fake_files(), source_commit=COMMIT)
        other = archive[:-1] + bytes([archive[-1] ^ 1])
        with self.assertRaisesRegex(m.BundleDenied,
                                    "M15_ARCHIVE_OUTER_HASH_DENIED"):
            m.inspect_archive(other,
                              trusted_outer_sha256=m.sha(archive),
                              trusted_source_commit=COMMIT)

    def test_other_immutable_commit_denied(self):
        archive = m.make_archive(fake_files(), source_commit=COMMIT)
        with self.assertRaisesRegex(m.BundleDenied,
                                    "M15_MANIFEST_POLICY_DENIED"):
            m.inspect_archive(archive,
                              trusted_outer_sha256=m.sha(archive),
                              trusted_source_commit="b" * 40)

    def test_missing_or_extra_modules_denied(self):
        for item in ("updater/linux_upgrade_gate.py", "deploy/evil.service"):
            values = fake_files()
            if item in values:
                del values[item]
            else:
                values[item] = b"evil"
            with self.subTest(item=item), self.assertRaisesRegex(
                m.BundleDenied, "M15_FILE_SET_DENIED"):
                m.make_archive(values, source_commit=COMMIT)

    def test_no_mutable_git_ref_or_unpinned_source_accepted(self):
        for commit in ("main", "HEAD", "a" * 39, "A" * 40,
                       "feat/release", ""):
            with self.subTest(commit=commit), self.assertRaisesRegex(
                m.BundleDenied, "M15_IMMUTABLE_COMMIT_REQUIRED"):
                m.make_archive(fake_files(), source_commit=commit)

    def test_tar_symlink_and_traversal_rejected_despite_matching_outer_hash(self):
        bad = (
            "../../etc/passwd",
            m.ROOT + "/updater/../../etc/passwd",
            m.ROOT + "/updater/evil.py",
            m.ROOT + "/updater/linux_upgrade_gate.py",
        )
        for path in bad:
            with self.subTest(path=path):
                buf = io.BytesIO()
                with gzip.GzipFile(fileobj=buf, mode="wb",
                                   filename="", mtime=0) as gz:
                    with tarfile.open(fileobj=gz, mode="w") as out:
                        meta = tarfile.TarInfo(path)
                        meta.size = 0
                        meta.mode = 0o600
                        meta.type = tarfile.SYMTYPE
                        meta.linkname = "/etc/passwd"
                        out.addfile(meta)
                raw = buf.getvalue()
                with self.assertRaisesRegex(
                        m.BundleDenied, "M15_TAR_ENTRY_DENIED"):
                    verified(raw)

    def test_duplicate_tar_member_denied_with_matching_outer_pin(self):
        archive = m.make_archive(fake_files(), source_commit=COMMIT)
        # Repack a valid archive but add duplicate safe member.
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb",
                           filename="", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as out:
                with tarfile.open(fileobj=io.BytesIO(archive),
                                  mode="r:gz") as original:
                    for member in original:
                        data = original.extractfile(member).read()
                        out.addfile(member, io.BytesIO(data))
                        if member.name.endswith("/manifest.json"):
                            out.addfile(member, io.BytesIO(data))
        with self.assertRaisesRegex(m.BundleDenied, "M15_TAR_ENTRY_DENIED"):
            verified(buf.getvalue())

    def test_private_source_file_and_parent_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for relative in m.FILES:
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"test\n")
            self.assertEqual(len(m.collect(root)), len(m.FILES))
            bad = root / m.FILES[0]
            bad.chmod(0o666)
            with self.assertRaisesRegex(
                    m.BundleDenied, "M15_SOURCE_FILE_MODE_OR_SIZE_DENIED"):
                m.collect(root)
            bad.chmod(0o600)
            bad.unlink()
            bad.symlink_to(root / m.FILES[1])
            with self.assertRaisesRegex(
                    m.BundleDenied, "M15_SOURCE_FILE_UNSAFE"):
                m.collect(root)

    def test_noncanonical_filename_or_oversized_payload_denied(self):
        for x in (b"", b"x" * (m.MAX_FILE + 1)):
            with self.subTest(size=len(x)), self.assertRaisesRegex(
                    m.BundleDenied, "M15_CONTENT_INVALID"):
                values = fake_files()
                values[m.FILES[0]] = x
                m.make_archive(values, source_commit=COMMIT)

    def test_cli_output_creation_is_not_an_installer(self):
        import inspect
        src = inspect.getsource(m)
        for forbidden in (
            "import subprocess", "sudo -n", "systemctl restart",
            "systemctl enable", "docker stop", "docker run",
            "shutil.rmtree(", "extractall(", "shell=True",
        ):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
