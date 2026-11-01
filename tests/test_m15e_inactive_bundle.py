"""M15E candidate is genuinely in M15B *inactive* bundle, not deployed."""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from updater import m15_portable_bundle as bundle
from updater import m15_inactive_bootstrap as bootstrap

COMMIT = "d"*40
NAME = "updater/linux_approval_redeemer.py"


class M15EInactiveBundleAcceptance(unittest.TestCase):
    def test_exact_m15e_inclusion_and_no_service_activation(self):
        self.assertIn(NAME,bundle.FILES)
        files={name:(f"# exact inert CI source {name}\n").encode()
               for name in bundle.FILES}
        files[NAME] = (Path(__file__).resolve().parent.parent / NAME).read_bytes()
        first=bundle.make_archive(files,source_commit=COMMIT)
        self.assertEqual(first,bundle.make_archive(files,source_commit=COMMIT))
        sha=hashlib.sha256(first).hexdigest()
        verified=bundle.inspect_archive(
            first,trusted_outer_sha256=sha,trusted_source_commit=COMMIT)
        self.assertEqual(verified["files_checked"],len(bundle.FILES))
        self.assertFalse(verified["activation_authorized"])
        self.assertFalse(verified["publisher_signature_verified"])
        self.assertFalse(verified["installation_performed"])
        report=bootstrap.verify_only(
            first,trusted_sha=sha,trusted_commit=COMMIT)
        self.assertEqual(report["status"],
                         "M15B_INACTIVE_BOOTSTRAP_PREFLIGHT_PASS")
        self.assertFalse(report["service_started"])
        with tarfile.open(fileobj=io.BytesIO(first),mode="r:gz") as archive:
            members={member.name:member for member in archive}
            member=bundle.ROOT+"/"+NAME
            self.assertIn(member,members)
            b=archive.extractfile(members[member]).read()
            self.assertEqual(hashlib.sha256(b).digest(),
                             hashlib.sha256(files[NAME]).digest())

    def test_m15e_missing_from_bundle_is_fatal(self):
        files={name:b"# test\n" for name in bundle.FILES
               if name != NAME}
        with self.assertRaisesRegex(bundle.BundleDenied,
                                    "M15_FILE_SET_DENIED"):
            bundle.make_archive(files,source_commit=COMMIT)

    def test_m15e_tampered_source_denied_by_external_sha(self):
        files={name:b"# test\n" for name in bundle.FILES}
        original=bundle.make_archive(files,source_commit=COMMIT)
        files[NAME]=b"# changed\n"
        changed=bundle.make_archive(files,source_commit=COMMIT)
        with self.assertRaisesRegex(bundle.BundleDenied,
                                    "M15_ARCHIVE_OUTER_HASH_DENIED"):
            bundle.inspect_archive(
                changed,trusted_outer_sha256=bundle.sha(original),
                trusted_source_commit=COMMIT)

    def test_inactive_bootstrap_rejects_missing_local_root_approval(self):
        files={name:b"# test\n" for name in bundle.FILES}
        raw=bundle.make_archive(files,source_commit=COMMIT)
        with patch.object(bootstrap.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(
                    bootstrap.BootstrapDenied,
                    "M15B_EXPLICIT_LOCAL_ADMIN_APPROVAL_REQUIRED"):
                bootstrap.install_inactive(
                    raw,trusted_sha=bundle.sha(raw),
                    trusted_commit=COMMIT,
                    local_admin_approval=False)


if __name__=="__main__":
    unittest.main()
