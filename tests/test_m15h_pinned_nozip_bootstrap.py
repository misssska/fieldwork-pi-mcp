"""M15-H exact-commit no-manual-ZIP inactive bootstrap negative contracts."""
from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import m15_portable_bundle as bundle
from updater import m15h_pinned_nozip_bootstrap as m

COMMIT = "d"*40


def fixture():
    files = {
        name: (f"# offline benign test source {name}\n").encode("ascii")
        for name in bundle.FILES
    }
    archive = bundle.make_archive(files, source_commit=COMMIT)
    return files, archive, bundle.sha(archive)


class NoZipBootstrapTests(unittest.TestCase):
    def test_exact_reproducible_nozip_acquisition_never_installs(self):
        files,archive,sha = fixture()
        calls=[]
        def reader(commit,name):
            calls.append((commit,name))
            return files[name]
        got=m.acquire_verified_archive(
            commit=COMMIT,trusted_sha256=sha,source_reader=reader)
        self.assertEqual(archive,got)
        self.assertEqual(calls,[(COMMIT,p) for p in bundle.FILES])
        status=m.run(mode="check",commit=COMMIT,
                     trusted_sha256=sha,source_reader=reader)
        self.assertEqual(status["status"],
                         "M15H_PINNED_ARCHIVE_VERIFIED_NOT_INSTALLED")
        self.assertFalse(status["activation_authorized"])
        self.assertFalse(status["publisher_identity_verified"])
        self.assertFalse(status["installation_performed"])

    def test_incorrect_archive_digest_never_installs(self):
        files,archive,sha=fixture()
        with patch.object(m.bootstrap,"install_inactive") as installer:
            with self.assertRaisesRegex(
                    m.PinnedBootstrapDenied,
                    "M15H_ARCHIVE_NOT_IDENTICAL_TO_TRUST_PIN"):
                m.acquire_verified_archive(
                    commit=COMMIT,trusted_sha256="f"*64,
                    source_reader=lambda _,name:files[name])
            installer.assert_not_called()

    def test_remote_but_valid_bytes_are_untrusted_without_expected_pin(self):
        files,archive,sha=fixture()
        files[bundle.FILES[0]]=b"# malicious but syntactically valid\n"
        with self.assertRaises(m.PinnedBootstrapDenied):
            m.acquire_verified_archive(
                commit=COMMIT,trusted_sha256=sha,
                source_reader=lambda _,name:files[name])

    def test_exact_files_bounded_and_missing_is_failure(self):
        files,archive,sha=fixture()
        for data in (b"",b"x"*(bundle.MAX_FILE+1),"notbytes",None):
            with self.subTest(data=str(data)[:10]),self.assertRaises(
                    m.PinnedBootstrapDenied):
                m.acquire_verified_archive(
                    commit=COMMIT,trusted_sha256=sha,
                    source_reader=lambda _,name:data if name==bundle.FILES[-1]
                    else files[name])
        with self.assertRaises(KeyError):
            m.acquire_verified_archive(
                commit=COMMIT,trusted_sha256=sha,
                source_reader=lambda _,name:files[name]
                if name!=bundle.FILES[-1] else files["missing"])

    def test_commit_and_bundle_sha_validated_before_network(self):
        files,archive,sha=fixture()
        def unexpected(*args):
            self.fail("must not access network")
        for commit in ("main","HEAD",COMMIT[:-1],COMMIT.upper(),
                       "../etc",True,None):
            with self.subTest(commit=commit),self.assertRaises(
                    m.PinnedBootstrapDenied):
                m.acquire_verified_archive(
                    commit=commit,trusted_sha256=sha,
                    source_reader=unexpected)
        for digest in ("",sha.upper(),sha[:-1],True,None):
            with self.subTest(digest=digest),self.assertRaises(
                    m.PinnedBootstrapDenied):
                m.acquire_verified_archive(
                    commit=COMMIT,trusted_sha256=digest,
                    source_reader=unexpected)

    def test_root_and_approval_fail_before_network(self):
        files,archive,sha=fixture()
        with patch.object(m.os,"geteuid",return_value=1000):
            with patch.object(m,"acquire_verified_archive") as download:
                with self.assertRaisesRegex(
                        m.PinnedBootstrapDenied,"M15H_INSTALL_LOCAL_ROOT_ONLY"):
                    m.run(mode="install-inactive",commit=COMMIT,
                          trusted_sha256=sha,local_admin_approval=True)
                download.assert_not_called()
        with patch.object(m.os,"geteuid",return_value=0):
            with patch.object(m,"acquire_verified_archive") as download:
                with self.assertRaises(m.PinnedBootstrapDenied):
                    m.run(mode="install-inactive",commit=COMMIT,
                          trusted_sha256=sha,local_admin_approval=False)
                download.assert_not_called()

    def test_rollback_never_downloads_or_chooses_paths(self):
        files,archive,sha=fixture()
        with patch.object(m.os,"geteuid",return_value=0):
            with patch.object(m.bootstrap,"rollback_inactive",
                              return_value={"status":"ROLLBACK"}) as rollback:
                with patch.object(m,"acquire_verified_archive") as download:
                    result=m.run(mode="rollback-inactive",commit=COMMIT,
                                 trusted_sha256=sha,local_admin_approval=True)
                    self.assertEqual(result["status"],"ROLLBACK")
                    rollback.assert_called_once_with(
                        trusted_sha=sha,trusted_commit=COMMIT,
                        local_admin_approval=True)
                    download.assert_not_called()

    def test_source_reader_network_url_never_user_selected(self):
        self.assertEqual(m.REPO_BASE,
                         "https://raw.githubusercontent.com/misssska/fieldwork-pi-mcp/")
        for bad in ("../../etc/passwd","evil.py","updater/../bad"):
            with self.subTest(name=bad),self.assertRaises(
                    m.PinnedBootstrapDenied):
                m._network_reader(COMMIT,bad)

    def test_no_shell_systemd_docker_or_privilege_modifying_code(self):
        src=inspect.getsource(m)
        for forbidden in (
            "import subprocess","shell=True","os.system(",
            "os.chown(","os.chmod(","os.setuid(","docker run",
            "systemctl start","systemctl enable",
            "tar.extractall(","useradd","groupadd",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,src)

    def test_cli_has_no_host_path_url_or_service_override(self):
        src=inspect.getsource(m.main)
        for bad in ("--url","--source-root","--target","--install-parent",
                    "--service","--unit","--docker"):
            self.assertNotIn(bad,src)
        self.assertIn("sys.stdin.isatty()",src)
        self.assertIn("REVIEW_PHRASE",src)

    def test_syntax_invalid_inside_correctly_pinned_source_is_rejected(self):
        files,archive,sha=fixture()
        files["updater/linux_approval_redeemer.py"]=b"def :\n"
        newer=bundle.make_archive(files,source_commit=COMMIT)
        with self.assertRaises(m.bootstrap.BootstrapDenied):
            m.acquire_verified_archive(
                commit=COMMIT,trusted_sha256=bundle.sha(newer),
                source_reader=lambda _,name:files[name])

    def test_explicit_no_automatic_install_on_success(self):
        files,archive,sha=fixture()
        with patch.object(m.bootstrap,"install_inactive") as installed:
            m.run(mode="check",commit=COMMIT,trusted_sha256=sha,
                  source_reader=lambda _,name:files[name])
            installed.assert_not_called()


if __name__=="__main__":
    unittest.main()
