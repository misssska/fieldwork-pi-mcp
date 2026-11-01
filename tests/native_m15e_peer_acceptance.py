"""M15E disposable GitHub Linux only: REAL different UID Unix peer acceptance.

Never run on a Pi: creates temporary synthetic approval, local OS users supplied
by the dedicated CI workflow, no Docker, no sudoers access, no deployments.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import socket

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from updater import linux_approval_redeemer as redemption
from updater import linux_upgrade_gate as gate

SECRET = b"m15e-synthetic-hmac-only-ci-" + b"Z" * 48
BEFORE = "a" * 64
AFTER = "b" * 64


def fixture_plan(root: Path):
    request = json.loads((root / "plan.json").read_text())
    policy = gate.HostPolicy("fieldwork-pi", frozenset({"fieldwork_mcp.py"}))
    return gate.validate_plan(
        request, policy, {"fieldwork_mcp.py": BEFORE}, int(time.time()))


def serve(root: Path, index: int, *, executor_uid: int, executor_gid: int):
    plan = fixture_plan(root)
    key = (root / "approved" / "secret.key").read_bytes()
    engine = redemption.LocalRedeemer(
        plan=plan, local_secret=key,
        approval_root=root / "approved" / "tickets",
        spent_root=root / "spent",
        socket_root=root / ("socket" + str(index)),
        expected_executor_uid=executor_uid,
        expected_executor_gid=executor_gid,
    )
    engine.serve_one()


def client(root: Path, index: int, expected_sha: str):
    req = gate.canon({"protocol": 1, "plan_sha256": expected_sha}) + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect(str(root / ("socket"+str(index)) / "handoff.sock"))
        conn.sendall(req)
        conn.shutdown(socket.SHUT_WR)
        data = conn.recv(1024)
    result = json.loads(data)
    print(json.dumps(result,sort_keys=True))
    return 0


def root_test():
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.geteuid() == 0
    operator_uid = int(os.environ["M15E_OPERATOR_UID"])
    executor_uid = int(os.environ["M15E_EXECUTOR_UID"])
    executor_gid = int(os.environ["M15E_EXECUTOR_GID"])
    assert operator_uid > 0 and executor_uid > 0
    assert executor_uid != operator_uid

    with tempfile.TemporaryDirectory(prefix="m15e-ci-",dir="/tmp") as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        src = root / "src"
        (src / "updater").mkdir(parents=True)
        src.chmod(0o755)
        (src / "updater").chmod(0o755)
        repo = Path(os.environ["GITHUB_WORKSPACE"])
        for name in ("__init__.py","linux_approval_redeemer.py",
                     "linux_upgrade_gate.py"):
            origin = repo / "updater" / name
            target = src / "updater" / name
            if name == "__init__.py" and not origin.exists():
                target.write_bytes(b"")
            else:
                shutil.copyfile(origin,target)
            target.chmod(0o644)
        worker = src / "native.py"
        shutil.copyfile(Path(__file__),worker)
        worker.chmod(0o644)
        now = int(time.time())
        request = {
            "protocol":1,"host_id":"fieldwork-pi",
            "commit_sha":"c"*40,"issued_at":now-5,"expires_at":now+300,
            "files":[{"name":"fieldwork_mcp.py","action":"replace",
                      "old_sha256":BEFORE,"new_sha256":AFTER}],
        }
        policy = gate.HostPolicy("fieldwork-pi",frozenset({"fieldwork_mcp.py"}))
        plan = gate.validate_plan(request,policy,{"fieldwork_mcp.py":BEFORE},now)
        (root/"plan.json").write_bytes(gate.canon(request))
        (root/"plan.json").chmod(0o644)
        for name,mode in (("approved",0o700),("approved/tickets",0o700),
                          ("spent",0o700),("socket1",0o710),
                          ("socket2",0o710),("socket3",0o710)):
            p=root/name
            p.mkdir(mode=mode)
            os.chown(p,operator_uid,executor_gid)
            p.chmod(mode)
        key = root/"approved"/"secret.key"
        key.write_bytes(SECRET)
        os.chown(key,operator_uid,executor_gid)
        key.chmod(0o600)
        ticket = gate.issue_local_approval(
            plan,local_secret=SECRET,operator_present=True,now=now)
        approval_path=root/"approved"/"tickets"/(plan.plan_sha256+".json")
        approval_path.write_bytes(gate.canon(ticket))
        os.chown(approval_path,operator_uid,executor_gid)
        approval_path.chmod(0o600)

        def under(uid: int,mode: str,seq: int):
            return [
                "setpriv","--reuid",str(uid),"--regid",str(executor_gid),
                "--clear-groups","/usr/bin/python3","-s",str(worker),
                mode,str(root),str(seq),plan.plan_sha256,
                str(executor_uid),str(executor_gid),
            ]

        def one(seq:int,caller_uid:int,expected_status:str):
            proc=subprocess.Popen(
                under(operator_uid,"server",seq),
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,text=True)
            try:
                path=root/("socket"+str(seq))/"handoff.sock"
                for _ in range(100):
                    if path.exists():
                        break
                    if proc.poll() is not None:
                        raise AssertionError("M15E_SERVER_EXITED_BEFORE_CONNECT")
                    time.sleep(0.05)
                else:
                    raise AssertionError("M15E_SERVER_SOCKET_MISSING")
                c=subprocess.run(under(caller_uid,"client",seq),
                                 capture_output=True,text=True,timeout=7)
                assert c.returncode==0, (c.stdout,c.stderr)
                payload=json.loads(c.stdout.strip())
                assert payload["status"]==expected_status,payload
                assert payload["execution_authorized"] is False
                proc.wait(timeout=7)
                assert proc.returncode==0,proc.stderr.read()
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
            return payload

        # Executor cannot read the operator's secret at all.
        check=subprocess.run(
            ["setpriv","--reuid",str(executor_uid),"--regid",
             str(executor_gid),"--clear-groups","/usr/bin/python3","-c",
             "from pathlib import Path;Path("+repr(str(key))+").read_bytes()"],
             capture_output=True,text=True,timeout=3)
        assert check.returncode!=0
        print("M15E_REAL_DIFFERENT_UID_SECRET_DENIAL_PASS",flush=True)
        first=one(1,executor_uid,"LOCAL_APPROVAL_REDEEMED_NOT_EXECUTED")
        assert first["approval_consumed"] is True
        print("M15E_REAL_PEERCRED_POSITIVE_PASS",flush=True)
        one(2,executor_uid,"LOCAL_APPROVAL_REDEMPTION_DENIED")
        print("M15E_DURABLE_REPLAY_DENIED_PASS",flush=True)
        one(3,operator_uid,"LOCAL_APPROVAL_REDEMPTION_DENIED")
        print("M15E_WRONG_PEER_UID_DENIED_PASS",flush=True)
        assert len(list((root/"spent").iterdir()))==1
        assert (root/"spent"/ticket["nonce"]).stat().st_mode & 0o777 == 0o600
        print("M15E_NO_DOCKER_NO_DEPLOY_NO_PI_CHANGES_PASS",flush=True)


def main():
    if len(sys.argv)==1:
        root_test()
    else:
        _,mode,r,seq,plan_sha,executor_uid,executor_gid=sys.argv
        root=Path(r)
        if mode=="server":
            serve(root,int(seq),executor_uid=int(executor_uid),
                  executor_gid=int(executor_gid))
        elif mode=="client":
            client(root,int(seq),plan_sha)
        else:
            raise RuntimeError("M15E_MODE_DENIED")


if __name__=="__main__":
    main()
