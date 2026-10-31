"""M15G stage operator-only bridge: offline fake Docker with real M14E rollback."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from updater import linux_stage_existing_lifecycle as stage
from updater import linux_m15g_stage_operator_bridge as bridge

KEY = b"m15g-only-disposable-ci-operator" + b"X" * 32


class FakeDocker:
    def __init__(self):
        self.rows = {
            service: {
                "id": chr(97 + i) * 64, "service": service,
                "name": f"/fieldwork-stage-{service}-1",
                "project": "fieldwork-stage", "number": "1",
                "state": "running",
            }
            for i,service in enumerate(stage.SERVICES)
        }
        self.commands = []
        self.fail_once = None

    def __call__(self, argv, *, timeout=15):
        self.commands.append(tuple(argv))
        if argv[0:2] != [stage.DOCKER,"container"]:
            raise AssertionError("Forbidden Docker command")
        verb = argv[2]
        identifier = argv[-1]
        match = [r for r in self.rows.values() if identifier in (
                 r["id"],r["name"].lstrip("/"))]
        if len(match) != 1:raise stage.StageDenied("FAKE_NOT_FOUND")
        row = match[0]
        if verb == "inspect":
            if argv[3:5] != ["--format",stage.DETAIL_FMT]:
                raise AssertionError("bad inspect")
            return "|".join((row["id"],row["name"],row["project"],
                             row["service"],row["number"],row["state"]))
        if verb not in ("start","stop") or len(argv) != 4:
            raise AssertionError("Unknown Docker verb")
        row["state"] = "running" if verb == "start" else "exited"
        if self.fail_once == row["service"]:
            self.fail_once = None
            raise stage.StageDenied("FAKE_TIMEOUT_AFTER_MUTATION")
        return row["id"]

    def assert_scope(self):
        self_owner = stage.fixed_names()
        ids = {r["id"] for r in self.rows.values()}
        for argv in self.commands:
            assert argv[:2] == (stage.DOCKER,"container")
            assert argv[2] in ("inspect","start","stop")
            assert argv[-1] in self_owner | ids


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)/"state"
        self.state.mkdir(mode=0o700)
        self.docker=FakeDocker()
        self.patcher=patch.object(stage,"_docker",self.docker)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.now=int(time.time())
        self.plan=stage.plan_action("stop",now=self.now)
        self.sha=stage.validate_plan(self.plan,now=self.now)
        self.helper_uid=os.geteuid()
        if self.helper_uid == 0:self.skipTest("helpers run as nonroot")
        self.operator_uid=self.helper_uid+4000
        self.mcp_uid=self.helper_uid+5000
        self.bridge=bridge.OperatorOnlyExistingStage(
            plan=self.plan, plan_sha256=self.sha,
            helper_secret=KEY,state_root=self.state,
            helper_uid=self.helper_uid,
            operator_uid=self.operator_uid,mcp_uid=self.mcp_uid)
        self.original_calls=len(self.docker.commands)

    def packet(self,sha=None):
        return json.dumps({"plan_sha256":self.sha if sha is None else sha,
                           "version":1},
                          separators=(",",":"),sort_keys=True).encode()+b"\n"

    def run(self, **kwargs):
        return self.bridge._mutate(
            payload=kwargs.pop("payload",self.packet()),
            uid=kwargs.pop("uid",self.operator_uid),
            now=kwargs.pop("now",self.now),**kwargs)

    def test_local_operator_can_stop_only_existing_stage_with_durable_journal(self):
        result=self.run()
        self.assertEqual(result["status"],"M15G_STAGE_EXISTING_ONLY_APPLIED")
        self.assertEqual(result["changed_count"],3)
        self.assertFalse(result["production_modified"])
        self.assertTrue(result["no_create_or_delete"])
        self.assertTrue(all(row["state"]=="exited"
                            for row in self.docker.rows.values()))
        self.docker.assert_scope()
        journal=[p for p in self.state.iterdir()
                 if p.name!="lock"]
        self.assertEqual(len(journal),1)
        self.assertEqual(json.loads(journal[0].read_bytes())["state"],
                         "COMMITTED")

    def test_no_remote_mcp_root_or_helper_uid(self):
        for uid in (self.mcp_uid, self.helper_uid, 0,True,self.operator_uid+1):
            with self.subTest(uid=uid),self.assertRaises(
                    bridge.StageBridgeDenied):
                self.run(uid=uid)
        self.assertEqual(len(self.docker.commands),self.original_calls)

    def test_canonical_input_only_and_no_extra_keys(self):
        bad=[
            self.packet("f"*64),b"",b"{}\n",
            self.packet().strip(), self.packet()+b"\n",
            b'{"version":1,"plan_sha256":"'+self.sha.encode()+
            b'","action":"stop"}\n',
            b'{"version":1,"version":1,"plan_sha256":"'+
            self.sha.encode()+b'"}\n',
            b'{"version":true,"plan_sha256":"'+self.sha.encode()+b'"}\n',
            self.packet()+b"x"*500,
        ]
        for payload in bad:
            with self.subTest(packet=payload[:20]),self.assertRaises(
                    bridge.StageBridgeDenied):
                self.run(payload=payload)
        self.assertEqual(len(self.docker.commands),self.original_calls)

    def test_docker_container_id_change_blocks_before_mutation(self):
        self.docker.rows["api"]["id"]="f"*64
        with self.assertRaisesRegex(bridge.StageBridgeDenied,
                                    "M15G_STAGE_CHANGED_AFTER_REVIEW"):
            self.run()
        self.assertTrue(all(row["state"]=="running"
                            for row in self.docker.rows.values()))
        self.docker.assert_scope()

    def test_expired_plan_denied(self):
        with self.assertRaises(stage.StageDenied):
            self.run(now=self.now+181)

    def test_midflight_docker_timeout_rolls_back_three_stage_containers(self):
        self.docker.fail_once="db"
        with self.assertRaises(stage.StageDenied):
            self.run()
        self.assertTrue(all(row["state"]=="running"
                            for row in self.docker.rows.values()))
        states=[json.loads(p.read_bytes())["state"]
                for p in self.state.iterdir() if p.name!="lock"]
        self.assertEqual(states,["ROLLED_BACK"])
        self.docker.assert_scope()

    def test_replay_same_plan_fails_after_committed_state_changes(self):
        self.run()
        with self.assertRaises(bridge.StageBridgeDenied):
            self.run()
        self.docker.assert_scope()

    def test_socket_same_uid_is_denied_by_real_so_peercred(self):
        a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        with a,b:
            self.assertEqual(bridge.peer_uid(a),os.geteuid())
            worker=threading.Thread(target=self.bridge.serve_connection,
                                    args=(a,),daemon=True)
            worker.start()
            b.sendall(self.packet())
            raw=b.recv(1024)
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(raw,bridge.DENIED)
        self.assertEqual(len(self.docker.commands),self.original_calls)

    def test_policy_requires_all_separate_nonroot_identities(self):
        for bad in ((self.helper_uid,self.mcp_uid,self.helper_uid),
                    (self.operator_uid,self.operator_uid,self.helper_uid),
                    (0,self.mcp_uid,self.helper_uid),
                    (self.operator_uid,self.mcp_uid,0)):
            with self.subTest(ids=bad),self.assertRaises(
                    bridge.StageBridgeDenied):
                bridge.OperatorOnlyExistingStage(
                    plan=self.plan,plan_sha256=self.sha,
                    helper_secret=KEY,state_root=self.state,
                    operator_uid=bad[0],mcp_uid=bad[1],helper_uid=bad[2])

    def test_service_never_registers_mcp_or_any_arbitrary_docker_api(self):
        from inspect import getsource
        src=getsource(bridge)
        for token in ("subprocess.run(", "import subprocess", "docker run",
                      "docker rm", "docker compose", "os.system(",
                      "shell=True", "os.exec", "os.chown("):
            with self.subTest(token=token):
                self.assertNotIn(token,src)


if __name__=="__main__":
    unittest.main()
