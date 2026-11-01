"""CI-only independent cross-check of the private M5 R6 Vitest receipt contract.

Never treats receipt verification as app correctness or release authorization.
No FieldWork application source or credentials reside in this public repo.
"""
from __future__ import annotations
import re
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
PASS_FILE = re.compile(
    r"^[ \t]*[✓✔][ \t]+"
    r"(src/(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\.test\.(?:ts|tsx))"
    r"[ \t]+\((\d+)[ \t]+tests?\)",
    re.MULTILINE,
)
FILE_TOTAL = re.compile(r"^[ \t]*Test Files[ \t]+(\d+) passed \((\d+)\)[ \t]*$", re.MULTILINE)
TEST_TOTAL = re.compile(r"^[ \t]*Tests[ \t]+(\d+) passed \((\d+)\)[ \t]*$", re.MULTILINE)
REQUIRED = frozenset({
    "src/components/DocumentViewer.test.tsx",
    "src/components/PhotoGalleryM5.test.tsx",
})


class ReceiptRejected(ValueError):
    pass


def verify(log: str) -> dict:
    if not isinstance(log, str) or not 0 < len(log) <= 12_000_000 or "\x00" in log:
        raise ReceiptRejected("M5_RECEIPT_EMPTY_BINARY_OR_OVERSIZE")
    log = ANSI.sub("", log).replace("\r\n", "\n")
    fs, ts = FILE_TOTAL.findall(log), TEST_TOTAL.findall(log)
    if len(fs) != 1 or len(ts) != 1 or any(a != b or int(a) < 1 for a, b in fs + ts):
        raise ReceiptRejected("M5_RECEIPT_EXACT_SUCCESS_SUMMARIES_REQUIRED")
    rows = PASS_FILE.findall(log)
    paths = [p for p, _ in rows]
    if (len(rows) != int(fs[0][0]) or len(paths) != len(set(paths)) or
            sum(int(n) for _, n in rows) != int(ts[0][0])):
        raise ReceiptRejected("M5_RECEIPT_ALL_REAL_FILE_ROWS_REQUIRED")
    if not REQUIRED.issubset(paths):
        raise ReceiptRejected("M5_RECEIPT_NAMED_M5_FILES_MISSING")
    if re.search(r"\b(?:FAIL|FAILED|Unhandled Errors|unhandled error|\d+ skipped|\d+ failed)\b", log):
        raise ReceiptRejected("M5_RECEIPT_NONPASS_SIGNAL")
    return {"status": "M5_NATIVE_VITEST_RECEIPT_ACCEPTED",
            "files": len(paths), "tests": int(ts[0][0]),
            "release_authorized": False, "real_fieldwork_tested": False}


def verify_file(file: Path) -> dict:
    if file.name != "m5-frontend-test.log" or not file.is_file() or file.is_symlink():
        raise ReceiptRejected("M5_NONCANONICAL_LOG")
    if file.stat().st_size > 12_000_000:
        raise ReceiptRejected("M5_LOG_TOO_LARGE")
    return verify(file.read_text(encoding="utf-8"))
