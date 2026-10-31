"""M14 loopback local approval UI: negative HTTP security tests.

All sockets bind only localhost of the disposable CI runner.
No Pi, no production service, no external network, no browser automation.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

from updater import linux_upgrade_gate as gate
from updater import linux_upgrade_review_ui as ui

NOW = 1793468000
SECRET = b"only-local-ui-test-hmac-signature-key-super-long"
BEFORE = "a" * 64
AFTER = "b" * 64
COMMIT = "c" * 40


def plan():
    policy = gate.HostPolicy(
        host_id="fieldwork-pi",
        allowed_modules=frozenset({"fieldwork_mcp.py"}),
    )
    request = {
        "protocol": 1, "host_id": "fieldwork-pi",
        "commit_sha": COMMIT,
        "issued_at": NOW - 30, "expires_at": NOW + 1000,
        "files": [{"name": "fieldwork_mcp.py",
                   "action": "replace", "old_sha256": BEFORE,
                   "new_sha256": AFTER}],
    }
    return gate.validate_plan(
        request, policy, {"fieldwork_mcp.py": BEFORE}, NOW)


@contextmanager
def running_ui(session):
    server = ui.create_local_server(session)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def http(url, *, method="GET", host=None, origin=None,
         content_type="application/x-www-form-urlencoded",
         form=None, fetch_site=None):
    headers = {}
    if host is not None:
        headers["Host"] = host
    if origin is not None:
        headers["Origin"] = origin
    if fetch_site is not None:
        headers["Sec-Fetch-Site"] = fetch_site
    data = None
    if method == "POST":
        headers["Content-Type"] = content_type
        data = urlencode(form or {}).encode("ascii")
    request = Request(url, method=method, headers=headers, data=data)
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as res:
            return res.status, res.read(), dict(res.headers)
    except HTTPError as err:
        return err.code, err.read(), dict(err.headers)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        root.chmod(0o700)
        self.session = ui.ReviewSession(
            plan=plan(), local_secret=SECRET, handoff=root,
        )

    def test_approval_creates_no_overwrite_protected_hmac(self):
        r = self.session.approve(
            self.session.csrf, self.session.plan.plan_sha256, NOW)
        self.assertEqual(r["status"], "LOCALLY_APPROVED_HANDOFF_PENDING")
        self.assertFalse(r["source_installed"])
        self.assertEqual(self.session.state, "APPROVED")
        f = self.session.handoff / (self.session.plan.plan_sha256 + ".json")
        self.assertTrue(f.exists())
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        signed = json.loads(f.read_text())
        nonce = gate.verify_local_approval(
            self.session.plan, signed,
            local_secret=SECRET, now=NOW, spent_nonces=frozenset())
        self.assertEqual(len(nonce), 32)
        with self.assertRaisesRegex(ui.ReviewDenied, "REVIEW_ALREADY_DECIDED"):
            self.session.approve(
                self.session.csrf, self.session.plan.plan_sha256, NOW)
        self.assertEqual(len(list(self.session.handoff.iterdir())), 1)

    def test_denial_irreversible_and_no_file(self):
        r = self.session.deny(self.session.csrf)
        self.assertEqual(r["status"], "LOCALLY_REJECTED")
        with self.assertRaisesRegex(ui.ReviewDenied, "REVIEW_ALREADY_DECIDED"):
            self.session.approve(
                self.session.csrf, self.session.plan.plan_sha256, NOW)
        self.assertEqual(list(self.session.handoff.iterdir()), [])

    def test_wrong_session_and_fingerprint_denied(self):
        for csrf, fingerprint, code in (
            ("wrong", self.session.plan.plan_sha256, "REVIEW_CSRF_DENIED"),
            (self.session.csrf, "a"*64, "REVIEW_FINGERPRINT_MISMATCH"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(
                    ui.ReviewDenied, code):
                self.session.approve(csrf, fingerprint, NOW)
        self.assertEqual(self.session.state, "PENDING")

    def test_rejects_expired_plan(self):
        with self.assertRaisesRegex(ui.ReviewDenied, "REVIEW_PLAN_EXPIRED"):
            self.session.approve(
                self.session.csrf, self.session.plan.plan_sha256,
                self.session.plan.expires_at)
        self.assertEqual(len(list(self.session.handoff.iterdir())), 0)

    def test_local_directory_must_be_0700(self):
        self.session.handoff.chmod(0o755)
        with self.assertRaises(Exception):
            ui.ReviewSession(plan=plan(), local_secret=SECRET,
                             handoff=self.session.handoff)
        self.session.handoff.chmod(0o700)

    def test_preexisting_path_blocks_handoff(self):
        target = self.session.handoff / (self.session.plan.plan_sha256 + ".json")
        target.write_text("foreign")
        with self.assertRaisesRegex(ui.ReviewDenied,
                                    "REVIEW_HANDOFF_COLLISION"):
            self.session.approve(
                self.session.csrf, self.session.plan.plan_sha256, NOW)
        self.assertEqual(target.read_text(), "foreign")
        self.assertEqual(self.session.state, "PENDING")


class LocalHTTPTests(SessionTests):
    def test_html_is_local_and_never_exposes_secret_or_mac(self):
        with running_ui(self.session) as base:
            status, data, headers = http(base+"/")
            self.assertEqual(status, 200)
            html = data.decode("utf-8")
            self.assertIn("Helyi MCP frissítés", html)
            self.assertIn(self.session.plan.plan_sha256, html)
            self.assertIn("fieldwork_mcp.py", html)
            self.assertNotIn(SECRET.decode("ascii"), html)
            self.assertNotIn("name=\"mac\"", html)
            self.assertIn("Content-Security-Policy", headers)
            self.assertEqual(headers["X-Frame-Options"], "DENY")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("Set-Cookie", headers)
            self.assertNotIn("http://", html)
            self.assertNotIn("<script", html)

    def test_happy_path_browser_post_issues_signed_handoff(self):
        with running_ui(self.session) as base:
            fields = {
                "csrf": self.session.csrf,
                "fingerprint": self.session.plan.plan_sha256,
                "action": "approve",
            }
            # Clock is controlled: the fixture's notional date is stable.
            from unittest.mock import patch
            with patch.object(ui.time, "time", return_value=NOW):
                status, data, headers = http(
                    base+"/decision", method="POST", origin=base,
                    form=fields, fetch_site="same-origin")
            self.assertEqual(status, 200)
            payload = json.loads(data)
            self.assertEqual(payload["status"],
                             "LOCALLY_APPROVED_HANDOFF_PENDING")
            self.assertNotIn("mac", payload)
            self.assertFalse(payload["source_installed"])
            approval = json.loads(
                (self.session.handoff /
                 (self.session.plan.plan_sha256+".json")).read_text())
            gate.verify_local_approval(
                self.session.plan, approval,
                local_secret=SECRET, now=NOW,
                spent_nonces=frozenset())

    def test_csrf_origin_and_dns_rebinding_denied_before_any_action(self):
        with running_ui(self.session) as base:
            fields = {"csrf": self.session.csrf,
                      "fingerprint": self.session.plan.plan_sha256,
                      "action": "approve"}
            cases = [
                {"origin": "https://evil.example", "form": fields},
                {"origin": base, "host": "evil.example", "form": fields},
                {"origin": base, "form": {**fields, "csrf": "forged"}},
                {"origin": base, "fetch_site": "cross-site", "form": fields},
                {"origin": base, "form": {**fields, "unexpected": "1"}},
            ]
            for options in cases:
                with self.subTest(case=options):
                    status, _, _ = http(base+"/decision", method="POST",
                                        **options)
                    self.assertEqual(status, 403)
            self.assertEqual(self.session.state, "PENDING")
            self.assertEqual(len(list(self.session.handoff.iterdir())), 0)

    def test_invalid_action_and_method_do_not_approve(self):
        with running_ui(self.session) as base:
            fields = {"csrf": self.session.csrf,
                      "fingerprint": self.session.plan.plan_sha256,
                      "action": "shell"}
            code, _, _ = http(base+"/decision", method="POST",
                              origin=base, form=fields)
            self.assertEqual(code, 403)
            code, _, _ = http(base+"/not-found")
            self.assertEqual(code, 404)
            self.assertEqual(self.session.state, "PENDING")

    def test_denial_using_browser_is_one_way_and_never_issues_signature(self):
        with running_ui(self.session) as base:
            fields = {"csrf": self.session.csrf,
                      "fingerprint": self.session.plan.plan_sha256,
                      "action": "deny"}
            status, data, _ = http(base+"/decision", method="POST",
                                  origin=base, form=fields)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["status"], "LOCALLY_REJECTED")
            fields["action"] = "approve"
            code, _, _ = http(base+"/decision", method="POST",
                              origin=base, form=fields)
            self.assertEqual(code, 403)
            self.assertEqual(len(list(self.session.handoff.iterdir())), 0)

    def test_bind_is_strictly_loopback(self):
        with running_ui(self.session) as base:
            self.assertTrue(base.startswith("http://127.0.0.1:"))
        for bad in (-1, 65536, "9000", True):
            with self.subTest(value=bad), self.assertRaises(ui.ReviewDenied):
                ui.create_local_server(self.session, port=bad)

    def test_no_external_assets_or_remote_approval_routes(self):
        import inspect
        text = inspect.getsource(ui)
        for forbidden in ("subprocess.run(", "os.system(", "docker stop",
                          "shell=True", "eval(", "exec(", "0.0.0.0",
                          "serve_forever()"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
