"""M9 image attestation, shell syntax and executor-boundary unit tests.

Pure CI tests: no Docker image is built and no FieldWork test is executed.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from updater import canary_appliance_image as sut
from updater import canary_archive_qualifier as q
from updater import canary_test_runner as runner

IMAGE = "sha256:" + "a" * 64
PINS = {
    "frontend_lock_sha256": "1" * 64,
    "backend_requirements_sha256": "2" * 64,
    "backend_dev_requirements_sha256": "3" * 64,
}
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "appliance" / "fieldwork-test-suite"
DOCKERFILE = ROOT / "appliance" / "Dockerfile"
SCRIPT_SHA = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()


def inspected():
    return [{
        "Id": IMAGE, "Os": "linux", "Architecture": "arm64",
        "Config": {"Labels": {
            sut.LABELS["profile"]: runner.PROFILE,
            sut.LABELS["production_access"]: "denied",
            sut.LABELS["scope"]: "isolated-test-only",
            sut.LABELS["script_sha256"]: SCRIPT_SHA,
            **{sut.LABELS[key]: digest for key, digest in PINS.items()},
        }},
    }]


class ImageQualificationTests(unittest.TestCase):
    def verify(self, obj=None, *, image=IMAGE, pins=None, arch="arm64"):
        return sut.qualify(
            json.dumps(inspected() if obj is None else obj).encode(),
            expected_image_id=image,
            dependency_sha256=PINS if pins is None else pins,
            expected_script_sha256=SCRIPT_SHA,
            architecture=arch,
        )

    def test_arm64_verified_but_never_authorized(self):
        r = self.verify()
        self.assertEqual(r["status"], "APPLIANCE_IMAGE_PREFLIGHT_PASS_NOT_APPROVED")
        self.assertEqual(r["image_id"], IMAGE)
        self.assertFalse(r["local_approval_granted"])
        self.assertFalse(r["mcp_activation_authorized"])
        self.assertFalse(r["canary_start_authorized"])
        self.assertFalse(r["production_modified"])
        self.assertFalse(r["five_suites_executed"])

    def test_local_image_id_is_accepted_by_existing_fixed_runner(self):
        self.assertTrue(runner.IMAGE_RE.fullmatch(IMAGE))
        self.assertEqual(runner._command.__name__, "_command")

    def test_old_repository_digest_form_remains_backward_compatible(self):
        self.assertTrue(runner.IMAGE_RE.fullmatch(
            "fieldwork-canary-test-appliance@sha256:" + "b" * 64))

    def test_unpinned_tag_and_unrelated_repo_denied(self):
        for image in ("fieldwork:latest", "postgres:18", "sha256:bad",
                      "ubuntu@sha256:" + "a" * 64):
            with self.subTest(image=image), self.assertRaises(q.QualificationDenied):
                self.verify(image=image)

    def test_image_id_drift_denied(self):
        self.assertDenied("APPLIANCE_IMAGE_ID_DRIFT",
                          lambda x: x[0].__setitem__("Id", "sha256:" + "f" * 64))

    def test_wrong_arch_denied(self):
        self.assertDenied("APPLIANCE_PLATFORM_MISMATCH",
                          lambda x: x[0].__setitem__("Architecture", "amd64"))

    def test_wrong_entrypoint_digest_denied(self):
        self.assertDenied("APPLIANCE_SCRIPT_SOURCE_DRIFT",
                          lambda x: x[0]["Config"]["Labels"].__setitem__(
                              sut.LABELS["script_sha256"], "f" * 64))

    def test_non_linux_denied(self):
        self.assertDenied("APPLIANCE_PLATFORM_MISMATCH",
                          lambda x: x[0].__setitem__("Os", "windows"))

    def test_missing_or_unsafe_profile_denied(self):
        self.assertDenied("APPLIANCE_BUILD_PROFILE_DENIED",
                          lambda x: x[0]["Config"]["Labels"].__setitem__(
                              sut.LABELS["profile"], "prod"))

    def test_wrong_source_dependency_hash_denied(self):
        self.assertDenied("APPLIANCE_SOURCE_DEPENDENCY_DRIFT",
                          lambda x: x[0]["Config"]["Labels"].__setitem__(
                              sut.LABELS["frontend_lock_sha256"], "e" * 64))

    def test_missing_label_denied(self):
        self.assertDenied("APPLIANCE_SOURCE_DEPENDENCY_DRIFT",
                          lambda x: x[0]["Config"]["Labels"].pop(
                              sut.LABELS["backend_requirements_sha256"]))

    def test_production_access_label_denied(self):
        self.assertDenied("APPLIANCE_BUILD_PROFILE_DENIED",
                          lambda x: x[0]["Config"]["Labels"].__setitem__(
                              sut.LABELS["production_access"], "allowed"))

    def test_extra_inspect_records_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "APPLIANCE_INSPECT_SCHEMA_DENIED"):
            self.verify(inspected() * 2)

    def test_bad_dependency_schema_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "APPLIANCE_DEPENDENCY_SCHEMA_DENIED"):
            self.verify(pins={"frontend_lock_sha256": "1" * 64})

    def test_invalid_digest_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "APPLIANCE_DEPENDENCY_DIGEST_INVALID"):
            self.verify(pins={**PINS, "frontend_lock_sha256": "not-a-sha"})

    def test_blank_inspection_denied(self):
        with self.assertRaises(q.QualificationDenied):
            sut.qualify(b"", expected_image_id=IMAGE, dependency_sha256=PINS,
                        expected_script_sha256=SCRIPT_SHA)

    def test_malformed_json_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "APPLIANCE_INSPECT_INVALID"):
            sut.qualify(b"not json", expected_image_id=IMAGE,
                            dependency_sha256=PINS, expected_script_sha256=SCRIPT_SHA)

    def test_supported_platform_is_explicit(self):
        rec = inspected()
        rec[0]["Architecture"] = "amd64"
        self.assertEqual(self.verify(rec, arch="amd64")["platform"], "linux/amd64")
        with self.assertRaisesRegex(q.QualificationDenied, "APPLIANCE_ARCHITECTURE_NOT_ALLOWED"):
            self.verify(arch="386")

    def assertDenied(self, message, mutator):
        data = copy.deepcopy(inspected())
        mutator(data)
        with self.assertRaisesRegex(q.QualificationDenied, message):
            self.verify(data)


class ApplianceScriptContract(unittest.TestCase):
    def test_shell_syntax(self):
        p = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True,
                           text=True, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_unknown_suite_exits_before_source_access(self):
        p = subprocess.run(["sh", str(SCRIPT), "some-arbitrary-command"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
        self.assertEqual(p.returncode, 64)

    def test_no_default_suite_is_allowed(self):
        p = subprocess.run(["sh", str(SCRIPT)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5, check=False)
        self.assertEqual(p.returncode, 64)

    def test_all_five_suite_names_are_fixed_in_script(self):
        script = SCRIPT.read_text()
        for name in runner.SUITES:
            self.assertIn(name, script)
        self.assertIn("127.0.0.1:55432", script)
        self.assertIn("FIELDWORK_TESTING=1", script)
        self.assertIn("NSS_WRAPPER_PASSWD", script)

    def test_dockerfile_requires_named_contexts_and_source_hashes(self):
        dockerfile = DOCKERFILE.read_text()
        self.assertIn("FROM ${NODE_BASE}", dockerfile)
        self.assertIn("FROM ${POSTGRES_BASE}", dockerfile)
        self.assertIn("COPY --from=fieldwork_base frontend/package.json", dockerfile)
        self.assertIn("COPY --from=policy fieldwork-test-suite", dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/local/bin/fieldwork-test-suite"]', dockerfile)
        self.assertIn('CMD ["NO_UNAPPROVED_DEFAULT_SUITE"]', dockerfile)
        self.assertIn('sha256sum /build/frontend/package-lock.json', dockerfile)
        self.assertNotIn("COPY . /", dockerfile)

    def test_runner_tmpfs_and_read_only_source(self):
        from unittest.mock import patch
        with patch.object(Path, "home", return_value=Path("/nonexistent-test-home")):
            # _command validates stage root: bypass only its existence for this
            # command-construction contract, never call Docker.
            with patch.object(Path, "is_dir", return_value=True), \
                 patch.object(Path, "is_symlink", return_value=False):
                args = runner._command("6" * 32, "backend-pytest-postgres", IMAGE)
        self.assertIn("--read-only", args)
        self.assertIn("--network=none", args)
        self.assertTrue(any("/work:rw," in item for item in args))
        self.assertTrue(any("/tmp:rw," in item for item in args))
        self.assertIn("target=/source,readonly", " ".join(args))
        self.assertNotIn("/opt/fieldwork", " ".join(args))


if __name__ == "__main__":
    unittest.main()
