"""Offline deterministic package-builder safety and acceptance tests."""
import hashlib
import unittest
from updater import canary_archive_builder as b
from updater import canary_archive_qualifier as q

FILES = {
    "frontend/src/components/PhotoGallery.tsx": b"export const photoZoom = true\n",
    "server/app/photo_comments_api.py": b"def photo_comments():\n    return 1\n",
}
PREV = {"frontend/src/components/PhotoGallery.tsx": "e" * 64,
        "server/app/photo_comments_api.py": None}
BASE = "a" * 40


class BuilderTests(unittest.TestCase):
    def build(self, files=None, prev=None, base=BASE):
        return b.make_archive(base_commit=base, files=FILES if files is None else files,
                              previous_sha256=PREV if prev is None else prev)

    def test_same_bytes_regardless_input_order(self):
        first, receipt = self.build()
        second, _ = self.build(dict(reversed(list(FILES.items()))),
                               dict(reversed(list(PREV.items()))))
        self.assertEqual(first, second)
        self.assertEqual(q.digest(first), receipt["artifact_sha256"])
        self.assertEqual(receipt["source_file_count"], 2)
        self.assertEqual(receipt["files"][0]["previous_sha256"], PREV[sorted(FILES)[0]])
        self.assertFalse(receipt["execution_authorized"])

    def test_required_prior_hash_map(self):
        for prev in ({}, {"frontend/src/components/PhotoGallery.tsx": "e" * 64},
                     {**PREV, "frontend/src/injected.ts": None}):
            with self.subTest(prev=prev), self.assertRaisesRegex(
                    q.QualificationDenied, "PREVIOUS_FILE_MAP_INCOMPLETE"):
                self.build(prev=prev)

    def test_deny_unexpected_code_or_secrets(self):
        for path in ("server/app/../../root.py", ".env", "Dockerfile",
                     ".github/workflows/deploy.yml", "frontend/src/bad.sh"):
            with self.subTest(path=path), self.assertRaisesRegex(
                    q.QualificationDenied, "SOURCE_PATH_DENIED"):
                self.build({path: b"hello\n"}, {path: None})

    def test_python_syntax(self):
        with self.assertRaisesRegex(q.QualificationDenied, "SOURCE_SYNTAX_INVALID"):
            self.build({"server/app/bad.py": b"def broken(:\n"},
                       {"server/app/bad.py": None})

    def test_binary_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "BINARY_SOURCE_DENIED"):
            self.build({"frontend/src/data.ts": b"\x00payload"},
                       {"frontend/src/data.ts": None})

    def test_oversized_source_denied(self):
        with self.assertRaisesRegex(q.QualificationDenied, "SOURCE_FILE_SIZE_DENIED"):
            self.build({"frontend/src/big.ts": b"x" * (q.MAX_FILE + 1)},
                       {"frontend/src/big.ts": None})

    def test_previous_hash_must_be_sha256(self):
        with self.assertRaisesRegex(q.QualificationDenied, "PREVIOUS_FILE_SHA_INVALID"):
            self.build(prev={**PREV, "server/app/photo_comments_api.py": "main"})

    def test_base_commit_must_be_immutable(self):
        with self.assertRaisesRegex(q.QualificationDenied, "BASE_COMMIT_INVALID"):
            self.build(base="main")

    def test_no_empty_release(self):
        with self.assertRaisesRegex(q.QualificationDenied, "SOURCE_FILE_COUNT_DENIED"):
            self.build(files={}, prev={})


if __name__ == "__main__":
    unittest.main()
