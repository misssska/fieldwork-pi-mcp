"""M15C disposable CI runner acceptance; never run on a real Pi.

Launch the actually installed local operator as Linux user 'nobody'.
The remote-MCP stand-in is a distinct UID. No systemd activation, Docker
mutation, host software update, or real user approval is performed.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

# Script-mode imports start in tests/, not the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updater import linux_upgrade_gate as gate

ROOT = Path("/var/lib/linux-mcp-operator")
ENTRY = Path("/opt/linux-mcp-operator/linux_upgrade_operator_app.py")
USER = "nobody"
URL = "http://127.0.0.1:8767"


def request(path="/", *, token=None, data=None):
    headers = {}
    if token is not None:
        encoded = base64.b64encode(b"operator:" + token).decode("ascii")
        headers["Authorization"] = "Basic " + encoded
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Origin"] = URL
        headers["Sec-Fetch-Site"] = "same-origin"
    req = Request(URL + path, data=None if data is None else
                  urlencode(data).encode("ascii"), headers=headers)
    try:
        with build_opener(ProxyHandler({})).open(req, timeout=2) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def private_file(name, contents, *, uid, gid):
    p = ROOT / name
    with p.open("xb") as stream:
        stream.write(contents)
    os.chmod(p, 0o600)
    os.chown(p, uid, gid)


def main():
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.geteuid() == 0
    assert ENTRY.is_file() and not ENTRY.is_symlink()
    assert not ROOT.exists()
    user = pwd.getpwnam(USER)
    assert user.pw_uid != 0
    remote = int(os.environ["M15C_REMOTE_UID"])
    assert remote > 0 and remote != user.pw_uid
    assert not subprocess.run(["id", "-u", USER], capture_output=True).returncode
    ROOT.mkdir(mode=0o700)
    os.chown(ROOT, user.pw_uid, user.pw_gid)
    approval_dir = ROOT / "approved"
    approval_dir.mkdir(mode=0o700)
    os.chown(approval_dir, user.pw_uid, user.pw_gid)
    token = secrets.token_hex(32).encode("ascii")
    secret = secrets.token_bytes(48)
    now = int(time.time())
    config = {
        "host_id": "fieldwork-pi", "remote_mcp_euid": remote,
        "allowed_modules": ["fieldwork_mcp.py"], "locked_modules": [],
        "active_hashes": {"fieldwork_mcp.py": "a" * 64},
        "listen_port": 8767,
    }
    proposed = {
        "protocol": 1, "host_id": "fieldwork-pi",
        "commit_sha": os.environ["M15C_COMMIT"],
        "issued_at": now - 10, "expires_at": now + 180,
        "files": [{
            "name": "fieldwork_mcp.py", "action": "replace",
            "old_sha256": "a" * 64, "new_sha256": "b" * 64,
        }],
    }
    for name, content in (
        ("config.json", gate.canon(config)),
        ("request.json", gate.canon(proposed)),
        ("operator_token.key", token),
        ("approval_hmac.key", secret),
    ):
        private_file(name, content, uid=user.pw_uid, gid=user.pw_gid)

    cmd = ["runuser", "-u", USER, "--", "/usr/bin/python3", "-s", str(ENTRY)]
    checked = subprocess.run(cmd + ["--check"], capture_output=True,
                             text=True, timeout=8)
    assert checked.returncode == 0, checked.stderr
    assert "M14C_LOCAL_REVIEW_CONFIG_PASS" in checked.stdout
    assert "M14C_NO_DEPLOYMENT_PERFORMED" in checked.stdout
    print("M15C_DISTINCT_UID_CONFIG_PREFLIGHT_PASS", flush=True)

    # Without the operator secret, the app cannot be authenticated.
    proc = subprocess.Popen(cmd + ["--serve"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            try:
                status, _ = request()
                if status == 401:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("M15C_LOCAL_SERVICE_NOT_READY")
        assert request("/", token=b"wrong-credential")[0] == 401
        code, html = request("/", token=token)
        assert code == 200 and b"fieldwork_mcp.py" in html
        assert secret not in html and token not in html
        assert "127.0.0.1" in URL
        print("M15C_SEPARATE_UID_AUTH_401_AND_200_PASS", flush=True)
        # This CI request is explicitly a synthetic approval, not a
        # human's consent or authorization to activate the Pi.
        plan = gate.validate_plan(
            proposed, gate.HostPolicy("fieldwork-pi", frozenset({"fieldwork_mcp.py"})),
            {"fieldwork_mcp.py": "a" * 64}, int(time.time()))
        from html.parser import HTMLParser
        class ExtractHidden(HTMLParser):
            def __init__(self):
                super().__init__()
                self.fields = {}
            def handle_starttag(self, tag, attrs):
                if tag == "input":
                    d = dict(attrs)
                    if d.get("name") and d.get("value"):
                        self.fields.setdefault(d["name"], d["value"])
        parser = ExtractHidden()
        parser.feed(html.decode("utf-8"))
        fields = {
            "csrf": parser.fields["csrf"],
            "fingerprint": plan.plan_sha256,
            "action": "approve",
        }
        bad = dict(fields, csrf="invalid")
        assert request("/decision", token=token, data=bad)[0] == 403
        code, reply = request("/decision", token=token, data=fields)
        assert code == 200 and json.loads(reply)["status"] == "LOCALLY_APPROVED_HANDOFF_PENDING"
        assert request("/decision", token=token, data=fields)[0] == 403
        ticket_path = approval_dir / (plan.plan_sha256 + ".json")
        ticket = json.loads(ticket_path.read_text())
        assert ticket_path.stat().st_mode & 0o777 == 0o600
        gate.verify_local_approval(
            plan, ticket, local_secret=secret, now=int(time.time()),
            spent_nonces=frozenset())
        print("M15C_SYNTHETIC_LOCAL_SIGNATURE_AND_REPLAY_DENIAL_PASS", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    assert proc.poll() is not None
    print("M15C_NONROOT_PROCESS_EXIT_PASS", flush=True)
    print("M15C_NO_SYSTEMD_DOCKER_OR_LIVE_MCP_CHANGE", flush=True)


if __name__ == "__main__":
    main()
