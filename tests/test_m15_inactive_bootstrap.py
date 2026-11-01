"""M15B inactive fixed-path OS bootstrap negative tests (no real host change).

Dedicated native GitHub CI has the separately authorized disposable root
installation smoke; this suite is strictly in-memory and tempdir only.
"""
from __future__ import annotations
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import m15_portable_bundle as b
from updater import m15_inactive_bootstrap as x

COMMIT = "e"*40


def fixture():
    sources = {path: (f"# trusted test module {path}\n").encode("utf-8")
               for path in b.FILES}
    raw = b.make_archive(sources, source_commit=COMMIT)
    return raw, b.sha(raw), sources


class InactiveBootstrapTests(unittest.TestCase):
    def test_preflight_is_pure(self):
        raw,sha,_ = fixture()
        r=x.verify_only(raw, trusted_sha=sha,trusted_commit=COMMIT)
        self.assertEqual(r["status"],"M15B_INACTIVE_BOOTSTRAP_PREFLIGHT_PASS")
        self.assertFalse(r["installation_performed"])
        self.assertFalse(r["activation_authorized"])
        self.assertFalse(r["service_started"])

    def test_root_denial_before_mutation(self):
        raw,sha,_ = fixture()
        with tempfile.TemporaryDirectory() as td:
            parent=Path(td)
            with patch.object(x.os,"geteuid",return_value=1000):
                with self.assertRaisesRegex(x.BootstrapDenied,"M15B_ROOT_ONLY"):
                    x.install_inactive(raw,trusted_sha=sha,
                                       trusted_commit=COMMIT,
                                       local_admin_approval=True,
                                       install_parent=parent)
            self.assertEqual(list(parent.iterdir()),[])

    def test_requires_explicit_local_approval_before_mutation(self):
        raw,sha,_=fixture()
        with tempfile.TemporaryDirectory() as td:
            with patch.object(x.os,"geteuid",return_value=0):
                with self.assertRaisesRegex(x.BootstrapDenied,
                        "M15B_EXPLICIT_LOCAL_ADMIN_APPROVAL_REQUIRED"):
                    x.install_inactive(raw,trusted_sha=sha,
                                       trusted_commit=COMMIT,
                                       local_admin_approval=False,
                                       install_parent=Path(td))
            self.assertEqual(list(Path(td).iterdir()),[])

    def test_same_or_wrong_source_no_overwrite(self):
        raw,sha,_=fixture()
        with tempfile.TemporaryDirectory() as td:
            parent=Path(td)
            prior=parent/x.INSTALL_DIR.name
            prior.mkdir()
            keep=prior/"irreplaceable"
            keep.write_text("KEEP")
            with patch.object(x.os,"geteuid",return_value=0):
                with self.assertRaises(x.BootstrapDenied):
                    x.install_inactive(raw,trusted_sha=sha,
                                       trusted_commit=COMMIT,
                                       local_admin_approval=True,
                                       install_parent=parent)
            self.assertEqual(keep.read_text(),"KEEP")

    def test_tampered_sha_and_commit_denied_preflight(self):
        raw,sha,_=fixture()
        for sh,commit,expected in [
            ("f"*64,COMMIT,"M15_ARCHIVE_OUTER_HASH_DENIED"),
            (sha,"f"*40,"M15_MANIFEST_POLICY_DENIED"),
        ]:
            with self.subTest(expected=expected),self.assertRaisesRegex(
                b.BundleDenied,expected):
                x.verify_only(raw,trusted_sha=sh,
                              trusted_commit=commit)

    def test_invalid_python_syntax_denied_even_with_matched_outer_pin(self):
        files={path:(f"# fixture {path}\n").encode() for path in b.FILES}
        files["updater/linux_upgrade_operator_app.py"]=b"def :=invalid\n"
        raw=b.make_archive(files,source_commit=COMMIT)
        with self.assertRaisesRegex(x.BootstrapDenied,
                                    "M15B_PYTHON_SYNTAX_DENIED"):
            x.verify_only(raw,trusted_sha=b.sha(raw),
                          trusted_commit=COMMIT)

    def test_no_docker_user_group_or_systemd_mutations(self):
        import inspect
        code=inspect.getsource(x)
        for forbidden in ("import subprocess", "useradd ", "groupadd ",
                          "systemctl restart","systemctl enable",
                          "docker run","docker stop","docker rm",
                          "shell=True","tar.extractall("):
            self.assertNotIn(forbidden,code)

    def test_cli_fixed_target_and_no_nonlocal_install(self):
        import inspect
        code=inspect.getsource(x.main)
        self.assertIn('sys.stdin.isatty()',code)
        self.assertIn('INSTALL_INACTIVE_M15B',code)
        self.assertNotIn('add_argument("--install-parent"',code)
        self.assertNotIn('add_argument("--service"',code)


if __name__=="__main__":
    unittest.main()
