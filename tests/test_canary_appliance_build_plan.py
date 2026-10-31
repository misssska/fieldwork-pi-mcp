"""M9 offline BuildKit plan tests; all Git operations are locally mocked."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import canary_appliance_build_plan as build
from updater import canary_archive_qualifier as q

HEAD = "5" * 40
NODE = "node:24-bookworm@sha256:" + "1" * 64
PG = "postgres:18-bookworm@sha256:" + "2" * 64
SOURCE = {
    "frontend/package-lock.json": b'{ "lockfileVersion": 3 }\n',
    "server/requirements.txt": b"fastapi==0.116.1\n",
    "server/requirements-dev.txt": b"pytest==8.4.2\n",
}


class CandidateApplianceBuildPlan(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Build preflight never runs as root")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "isolated-git-base"
        self.root.mkdir(mode=0o700)
        for path, blob in SOURCE.items():
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(blob)
        policy_dir = Path(build.__file__).resolve().parents[1] / "appliance"
        self.pins = {
            key: hashlib.sha256((policy_dir / key).read_bytes()).hexdigest()
            for key in build.POLICY
        }
        self.git = patch.object(build.base, "_git",
                                side_effect=lambda repo, *args, **kw:
                                HEAD.encode() if args[0] == "rev-parse" else b"")
        self.fixed = patch.object(build.base, "fixed_checkout", return_value=self.root)
        self.git.start()
        self.fixed.start()
        self.addCleanup(self.git.stop)
        self.addCleanup(self.fixed.stop)

    def make(self, **replace):
        args = dict(expected_base_commit=HEAD, node_base=NODE, postgres_base=PG,
                    expected_policy_sha256=self.pins)
        args.update(replace)
        return build.plan(**args)

    def test_exact_plan_is_inert_and_uses_no_production(self):
        result = self.make()
        self.assertEqual(result["status"], "APPLIANCE_BUILD_PLAN_PASS_NOT_EXECUTED")
        self.assertFalse(result["build_executed"])
        self.assertFalse(result["image_approved"])
        self.assertFalse(result["mcp_modified"])
        self.assertFalse(result["production_modified"])
        self.assertEqual(result["base_commit"], HEAD)
        argv = result["argv"]
        self.assertEqual(argv[:3], ["docker", "buildx", "build"])
        self.assertIn("linux/arm64", argv)
        self.assertIn("--pull=false", argv)
        self.assertIn("policy=" + str(Path(build.__file__).resolve().parents[1] / "appliance"), argv)
        self.assertIn("fieldwork_base=" + str(self.root), argv)
        self.assertNotIn("/opt/fieldwork", " ".join(argv))
        self.assertNotIn("--privileged", argv)
        self.assertEqual(result["dependencies"]["frontend_lock_sha256"],
                         hashlib.sha256(SOURCE["frontend/package-lock.json"]).hexdigest())

    def test_no_mutation_to_private_source(self):
        before = {x: (self.root / x).read_bytes() for x in SOURCE}
        self.make()
        self.assertEqual(before, {x: (self.root / x).read_bytes() for x in SOURCE})

    def test_unpinned_node_is_rejected(self):
        for node in ("node:24-bookworm", "node:latest", "ubuntu@sha256:"+"1"*64):
            with self.subTest(node=node), self.assertRaisesRegex(
                    q.QualificationDenied, "APPLIANCE_NODE_IMAGE_PIN_REQUIRED"):
                self.make(node_base=node)

    def test_unpinned_postgres_is_rejected(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_POSTGRES_IMAGE_PIN_REQUIRED"):
            self.make(postgres_base="postgres:18-bookworm")

    def test_base_commit_mismatch_is_rejected(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_PRIVATE_GIT_HEAD_DRIFT"):
            self.make(expected_base_commit="6"*40)

    def test_policy_source_tamper_is_rejected(self):
        wrong = {**self.pins, "Dockerfile": "0"*64}
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_POLICY_SOURCE_DRIFT"):
            self.make(expected_policy_sha256=wrong)

    def test_policy_missing_member_rejected(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_POLICY_FILE_SET_DENIED"):
            self.make(expected_policy_sha256={"Dockerfile": self.pins["Dockerfile"]})

    def test_missing_dependency_rejected(self):
        (self.root / "server/requirements-dev.txt").unlink()
        with self.assertRaises(q.QualificationDenied):
            self.make()

    def test_world_writable_dependency_rejected(self):
        (self.root / "frontend/package-lock.json").chmod(0o666)
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_SOURCE_MODE_OR_SIZE"):
            self.make()

    def test_special_dependency_symlink_rejected(self):
        file = self.root / "server/requirements.txt"
        file.rename(file.with_suffix(".backup"))
        file.symlink_to(file.with_suffix(".backup"))
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_SOURCE_NOT_REGULAR"):
            self.make()

    def test_private_git_dirty_rejected(self):
        with patch.object(build.base, "_git",
                          side_effect=lambda repo, *args, **kw:
                          HEAD.encode() if args[0] == "rev-parse" else b" M frontend/src/App.tsx"):
            with self.assertRaisesRegex(q.QualificationDenied,
                                        "APPLIANCE_PRIVATE_GIT_DIRTY"):
                self.make()

    def test_x86_build_only_with_explicit_architecture(self):
        result = self.make(architecture="amd64")
        self.assertIn("linux/amd64", result["argv"])
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_ARCHITECTURE_DENIED"):
            self.make(architecture="armv7")

    def test_pin_must_be_trusted_input(self):
        with self.assertRaisesRegex(q.QualificationDenied,
                                    "APPLIANCE_POLICY_PIN_INVALID"):
            self.make(expected_policy_sha256={**self.pins, "Dockerfile": "bad"})


if __name__ == "__main__":
    unittest.main()
