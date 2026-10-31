"""M15 offline sidecar staging into disposable user-owned directories."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from updater import m15_portable_bundle as b
from updater import m15_user_stage as s

COMMIT = "e"*40


def candidate():
    files={path:(f"# test fixture {path}\n").encode("ascii") for path in b.FILES}
    raw=b.make_archive(files,source_commit=COMMIT)
    return raw,b.sha(raw),files


class StageTests(unittest.TestCase):
    def test_successful_offline_stage_is_not_activation(self):
        raw,sha,source=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            r=s.stage_verified_archive(
                raw,trusted_outer_sha256=sha,trusted_source_commit=COMMIT,
                local_parent=root,local_staging_consent=True)
            self.assertEqual(r["status"],"M15_USER_OWNED_CANDIDATE_STAGED")
            self.assertEqual(r["staged_files"],len(b.FILES))
            self.assertFalse(r["activation_authorized"])
            self.assertFalse(r["service_modified"])
            self.assertFalse(r["mcp_modified"])
            self.assertFalse(r["production_modified"])
            target=root/("m15-"+sha[:20])
            self.assertTrue((target/".complete.json").exists())
            self.assertEqual((target/".complete.json").stat().st_mode & 0o777,0o600)
            self.assertTrue((target/"manifest.json").is_file())
            for name,expected in source.items():
                self.assertEqual((target/name).read_bytes(),expected)
                self.assertEqual((target/name).stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads((target/".complete.json").read_text())["activation_authorized"],False)

    def test_no_local_consent_means_zero_changes(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            with self.assertRaisesRegex(s.StageDenied,"M15_STAGE_CONSENT_REQUIRED"):
                s.stage_verified_archive(
                    raw,trusted_outer_sha256=digest,trusted_source_commit=COMMIT,
                    local_parent=root,local_staging_consent=False)
            self.assertEqual(list(root.iterdir()),[])

    def test_tampered_outer_sha_denied_before_any_write(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            with self.assertRaisesRegex(b.BundleDenied,"M15_ARCHIVE_OUTER_HASH_DENIED"):
                s.stage_verified_archive(
                    raw,trusted_outer_sha256="0"*64,trusted_source_commit=COMMIT,
                    local_parent=root,local_staging_consent=True)
            self.assertEqual(list(root.iterdir()),[])

    def test_wrong_source_commit_denied_before_any_write(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            with self.assertRaisesRegex(b.BundleDenied,"M15_MANIFEST_POLICY_DENIED"):
                s.stage_verified_archive(
                    raw,trusted_outer_sha256=digest,trusted_source_commit="f"*40,
                    local_parent=root,local_staging_consent=True)
            self.assertEqual(list(root.iterdir()),[])

    def test_stage_replay_refuses_overwrite_even_if_every_file_exists(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            kwargs=dict(trusted_outer_sha256=digest,trusted_source_commit=COMMIT,
                        local_parent=root,local_staging_consent=True)
            s.stage_verified_archive(raw,**kwargs)
            with self.assertRaisesRegex(s.StageDenied,"M15_STAGE_REPLAY_DENIED"):
                s.stage_verified_archive(raw,**kwargs)

    def test_foreign_symlink_destination_denied(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            other=root/"outside"
            other.mkdir()
            (root/("m15-"+digest[:20])).symlink_to(other)
            with self.assertRaisesRegex(s.StageDenied,"M15_STAGE_REPLAY_DENIED"):
                s.stage_verified_archive(
                    raw,trusted_outer_sha256=digest,trusted_source_commit=COMMIT,
                    local_parent=root,local_staging_consent=True)
            self.assertEqual(list(other.iterdir()),[])

    def test_root_execution_is_not_installer(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o700)
            with patch.object(s.os,"geteuid",return_value=0):
                with self.assertRaisesRegex(s.StageDenied,"M15_STAGE_ROOT_DENIED"):
                    s.stage_verified_archive(
                        raw,trusted_outer_sha256=digest,trusted_source_commit=COMMIT,
                        local_parent=root,local_staging_consent=True)

    def test_world_readable_parent_denied(self):
        raw,digest,_=candidate()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            root.chmod(0o755)
            with self.assertRaisesRegex(s.StageDenied,"M15_STAGE_PARENT_NOT_PRIVATE"):
                s.stage_verified_archive(
                    raw,trusted_outer_sha256=digest,trusted_source_commit=COMMIT,
                    local_parent=root,local_staging_consent=True)

    def test_no_shell_docker_systemd_or_remote_net(self):
        import inspect
        code=inspect.getsource(s)
        for forbidden in ("subprocess.run(","os.system(","shell=True",
                          "docker stop", "docker run", "systemctl enable",
                          "systemctl restart", "urllib.request", "extractall(",
                          "sudo -n"):
            self.assertNotIn(forbidden,code)


if __name__=="__main__":
    unittest.main()
