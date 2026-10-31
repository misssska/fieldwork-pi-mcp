"""M14 isolated, loopback-only human approval UI -- no deployment.

This is NOT a FieldWork MCP handler. Run only as a separate operator-owned
local process, with an approver-only key, policy and trusted inbox copy.
No arbitrary bind address, shell, installation, Docker, proxy or external
resource is permitted. Approving issues a short-lived, plan-bound MAC to a
private local handoff directory; the actual installer remains separate.

This UI is a laboratory component. The independently authenticated inbox
handoff, OS service units and publisher trust checks are NOT yet integrated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
import binascii
import hashlib
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import time
from urllib.parse import parse_qs

if __package__:
    from . import linux_upgrade_gate as gate
    from . import linux_upgrade_local_transaction as local
else:
    import linux_upgrade_gate as gate
    import linux_upgrade_local_transaction as local

MAX_POST = 1024


class ReviewDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ReviewDenied(reason)


def _write_approval(handoff: Path, plan_sha256: str,
                    approval: dict) -> None:
    """Atomic, no-overwrite, exact-plan private handoff; never a shell script."""
    local.directory(handoff)
    require(type(plan_sha256) is str and
            gate.HEX64.fullmatch(plan_sha256) is not None,
            "REVIEW_HANDOFF_ID_DENIED")
    target = handoff / (plan_sha256 + ".json")
    require(not target.exists() and not target.is_symlink(),
            "REVIEW_HANDOFF_COLLISION")
    payload = gate.canon(approval)
    require(0 < len(payload) <= 4096, "REVIEW_HANDOFF_SIZE_DENIED")
    fd, tmp_name = tempfile.mkstemp(prefix=".approval-", dir=handoff)
    temporary = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise ReviewDenied("REVIEW_HANDOFF_COLLISION") from exc
        local.sync(handoff)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass
class ReviewSession:
    """A single immutable plan, chosen by LOCAL trusted configuration."""
    plan: gate.ValidatedPlan
    local_secret: bytes = field(repr=False)
    operator_token: bytes = field(repr=False)
    handoff: Path
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32),
                      repr=False)
    state: str = "PENDING"
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        require(type(self.local_secret) is bytes and
                len(self.local_secret) >= 32, "REVIEW_LOCAL_KEY_INVALID")
        require(type(self.operator_token) is bytes and
                len(self.operator_token) >= 32 and
                self.operator_token != self.local_secret and
                all(33 <= c <= 126 and c != 58 for c in self.operator_token),
                "REVIEW_OPERATOR_AUTH_INVALID")
        require(self.state == "PENDING", "REVIEW_STATE_INVALID")
        local.directory(self.handoff)

    def approve(self, csrf: str, fingerprint: str, now: int) -> dict:
        with self.lock:
            require(self.state == "PENDING", "REVIEW_ALREADY_DECIDED")
            require(type(csrf) is str and len(csrf) <= 128 and
                    hmac.compare_digest(csrf, self.csrf),
                    "REVIEW_CSRF_DENIED")
            require(type(fingerprint) is str and
                    hmac.compare_digest(fingerprint, self.plan.plan_sha256),
                    "REVIEW_FINGERPRINT_MISMATCH")
            require(type(now) is int and now < self.plan.expires_at and
                    now >= self.plan.issued_at, "REVIEW_PLAN_EXPIRED")
            approval = gate.issue_local_approval(
                self.plan, local_secret=self.local_secret,
                operator_present=True, now=now)
            # File name is derived exclusively from a validated SHA256;
            # no request-body-selected path or script can be passed.
            _write_approval(self.handoff, self.plan.plan_sha256, approval)
            self.state = "APPROVED"
            return {
                "status": "LOCALLY_APPROVED_HANDOFF_PENDING",
                "host_id": self.plan.host_id,
                "plan_sha256": self.plan.plan_sha256,
                "source_installed": False,
                "service_restarted": False,
            }

    def deny(self, csrf: str) -> dict:
        with self.lock:
            require(self.state == "PENDING", "REVIEW_ALREADY_DECIDED")
            require(type(csrf) is str and len(csrf) <= 128 and
                    hmac.compare_digest(csrf, self.csrf),
                    "REVIEW_CSRF_DENIED")
            self.state = "DENIED"
            return {"status": "LOCALLY_REJECTED",
                    "source_installed": False}


# No remote images, fonts, scripts or CDNs.
_STYLE = """body{background:#0d1424;color:#e7eefb;font:16px/1.55 system-ui,sans-serif;
max-width:760px;padding:44px 22px;margin:auto}h1{font-size:30px;letter-spacing:-.035em}
p{color:#aebfd7}.card{background:#172338;border:1px solid #354861;
border-radius:18px;padding:26px;margin-top:20px}
code{overflow-wrap:anywhere;background:#26344e;padding:3px 6px;border-radius:5px}
dl{display:grid;grid-template-columns:125px 1fr;gap:12px}dt{color:#b9c8df}
dd{margin:0;overflow-wrap:anywhere}.files{margin:16px 0;padding-left:20px}
button{border:0;border-radius:9px;padding:13px 20px;font-weight:650;cursor:pointer}
.approve{background:#76c6ab;color:#071c1c}.deny{background:#33445f;color:white}
form{display:inline-block;margin-right:10px;margin-top:10px}
small{color:#aebfd7;display:block;margin-top:15px}.warn{color:#f6d08e}
"""


def _html(session: ReviewSession) -> bytes:
    plan = session.plan
    rows = "".join(
        "<li><code>" + escape(x["name"]) + "</code> – " +
        escape(x["action"]) + ", SHA256 <code>" +
        escape(x["new_sha256"]) + "</code></li>"
        for x in plan.files)
    buttons = ""
    if session.state == "PENDING":
        for action, label, cls in (
            ("approve", "Jóváhagyom ezt a változtatást", "approve"),
            ("deny", "Elutasítom", "deny")
        ):
            buttons += (
                '<form action="/decision" method="POST">'
                '<input type="hidden" name="csrf" value="' +
                escape(session.csrf, quote=True) + '">'
                '<input type="hidden" name="fingerprint" value="' +
                escape(plan.plan_sha256) + '">'
                '<input type="hidden" name="action" value="' + action + '">'
                '<button class="' + cls + '" type="submit">' + label +
                '</button></form>')
    info = (
        "<h1>Helyi MCP frissítés jóváhagyása</h1>"
        '<p class="warn">Csak helyi gépen. Nem indít telepítést vagy '
        "konténerműveletet.</p><section class='card'>"
        "<dl><dt>Eszköz</dt><dd><code>" + escape(plan.host_id) +
        "</code></dd><dt>Git commit</dt><dd><code>" +
        escape(plan.commit_sha) + "</code></dd>"
        "<dt>Teljes terv SHA</dt><dd><code>" +
        escape(plan.plan_sha256) + "</code></dd>"
        "<dt>Lejárat (Unix)</dt><dd>" + str(plan.expires_at) + "</dd>"
        "<dt>Állapot</dt><dd>" + escape(session.state) + "</dd></dl>"
        "<h2>Érintett MCP-modulok</h2><ul class='files'>" + rows +
        "</ul><small>Az aláírás egy konkrét géphez és változtatási tervhez "
        "kötött. A jóváhagyás nem telepítés; a külön telepítő "
        "újraellenőrzi a fájlokat.</small>" + buttons + "</section>"
    )
    page = ('<!doctype html><html lang="hu"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Linux MCP | Helyi jóváhagyás</title><style>' +
            _STYLE + '</style></head><body>' + info + '</body></html>')
    return page.encode("utf-8")


class _LoopbackServer(ThreadingHTTPServer):
    # SO_REUSEADDR permits a single localhost listener to restart even when
    # prior HTTP connections remain in TCP TIME_WAIT. SO_REUSEPORT stays off:
    # two active local servers must not share the approval port.
    allow_reuse_address = True
    allow_reuse_port = False
    daemon_threads = True


def create_local_server(session: ReviewSession,
                        *, port: int = 0) -> ThreadingHTTPServer:
    """Never bind externally; no configurable address or proxy trust."""
    require(type(port) is int and 0 <= port <= 65535,
            "REVIEW_PORT_INVALID")

    class Handler(BaseHTTPRequestHandler):
        server_version = "M14Review/0"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Suppress request logs, including hidden CSRF form values.
            return

        def _operator_authenticated(self) -> bool:
            """Loopback alone is NOT authentication; remote MCP can open it."""
            auth = self.headers.get("Authorization", "")
            if type(auth) is not str or len(auth) > 256 or not auth.startswith("Basic "):
                return False
            try:
                raw = base64.b64decode(auth[6:].encode("ascii"), validate=True)
            except (ValueError, binascii.Error, UnicodeError):
                return False
            if len(raw) > 192 or not raw.startswith(b"operator:"):
                return False
            return hmac.compare_digest(raw[len(b"operator:"):],
                                       session.operator_token)

        def _authenticate(self) -> bool:
            if self._operator_authenticated():
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="M14 Local Operator"')
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "close")
            self.end_headers()
            return False

        def _safe_origin(self, *, post: bool) -> bool:
            if self.client_address[0] != "127.0.0.1":
                return False
            p = self.server.server_address[1]
            allowed_hosts = {f"127.0.0.1:{p}", f"localhost:{p}"}
            host = self.headers.get("Host", "")
            if host not in allowed_hosts:
                return False
            if post:
                origin = self.headers.get("Origin")
                if origin not in {"http://" + h for h in allowed_hosts}:
                    return False
                if self.headers.get("Sec-Fetch-Site") not in (
                    None, "same-origin", "none"
                ):
                    return False
            return True

        def _reply(self, code: int, content: bytes, *,
                   content_type: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if not self._safe_origin(post=False):
                return self._reply(403, b"FORBIDDEN")
            if self.path != "/":
                return self._reply(404, b"NOT_FOUND")
            if not self._authenticate():
                return
            return self._reply(200, _html(session),
                               content_type="text/html; charset=utf-8")

        def do_POST(self):
            if not self._safe_origin(post=True):
                return self._reply(403, b"FORBIDDEN")
            if self.path != "/decision":
                return self._reply(404, b"NOT_FOUND")
            if not self._authenticate():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != (
                "application/x-www-form-urlencoded"
            ):
                return self._reply(415, b"FORM_ONLY")
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isascii() or not raw_length.isdigit():
                return self._reply(400, b"LENGTH_REQUIRED")
            length = int(raw_length)
            if length <= 0 or length > MAX_POST:
                return self._reply(413, b"FORM_TOO_LARGE")
            try:
                data = self.rfile.read(length).decode("ascii")
                fields = parse_qs(data, keep_blank_values=True,
                                  strict_parsing=True, max_num_fields=4)
                require(set(fields) == {"action", "csrf", "fingerprint"} and
                        all(len(v) == 1 for v in fields.values()),
                        "REVIEW_FORM_SCHEMA_DENIED")
                action = fields["action"][0]
                csrf = fields["csrf"][0]
                fingerprint = fields["fingerprint"][0]
                if action == "approve":
                    result = session.approve(csrf, fingerprint, int(time.time()))
                elif action == "deny":
                    require(hmac.compare_digest(fingerprint,
                                               session.plan.plan_sha256),
                            "REVIEW_FINGERPRINT_MISMATCH")
                    result = session.deny(csrf)
                else:
                    raise ReviewDenied("REVIEW_ACTION_NOT_ALLOWED")
            except (ReviewDenied, gate.UpgradeDenied, ValueError,
                    UnicodeError, KeyError):
                return self._reply(403, b"REVIEW_DENIED")
            # A status only; never send MAC, key, nonce or local file path.
            return self._reply(200, json.dumps(result).encode("ascii"),
                               content_type="application/json; charset=utf-8")

    return _LoopbackServer(("127.0.0.1", port), Handler)
