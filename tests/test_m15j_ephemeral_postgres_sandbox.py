"""M15J3 fixed real PostgreSQL network sandbox: negative + mock cleanup gates."""
from __future__ import annotations
from unittest.mock import patch
import inspect
import json
import unittest
from updater import m15j_ephemeral_postgres_sandbox as m

RUN="a"*32
ID_DB="b"*64
ID_TEST="c"*64
ID_NET="d"*64
IMAGE="docker.io/library/postgres@sha256:"+"e"*64


class PostgresSandboxTests(unittest.TestCase):
    def test_valid_fixed_internal_network_and_postgres_only(self):
        n=m.argv_network(RUN)
        self.assertEqual(n[:3],("/usr/bin/docker","network","create"))
        self.assertIn("--internal",n)
        self.assertEqual(n[-1],m.names(RUN)["network"])
        db=m.argv_db(RUN,IMAGE)
        test=m.argv_test(RUN,IMAGE)
        self.assertEqual(db[0:3],("/usr/bin/docker","container","create"))
        self.assertEqual(test[0:3],("/usr/bin/docker","container","create"))
        self.assertIn("--read-only",db)
        self.assertIn("--read-only",test)
        self.assertIn("--cap-drop",db)
        self.assertIn("--cap-drop",test)
        self.assertEqual(test[-7:],("psql","-h",m.names(RUN)["db"],
                                    "-U","postgres","-X","-tAc","SELECT 1")[-7:])
        for forbidden in ("--privileged","-v","--volume","--mount",
                          "--publish","--network=host","--pid=host",
                          "--cap-add","--device","--userns=host"):
            self.assertNotIn(forbidden,db)
            self.assertNotIn(forbidden,test)

    def test_invalid_identifier_or_image_denied(self):
        for run in ("",RUN[:-1],"A"*32,"../../fieldwork",True,None):
            with self.subTest(run=run),self.assertRaises(m.SandboxDenied):
                m.argv_db(run,IMAGE)
        for image in ("postgres:16-alpine","alpine@sha256:"+"a"*64,
                      "postgres@sha256:"+"g"*64,
                      "postgres@sha256:"+"a"*63,
                      "evil;postgres@sha256:"+"a"*64,None):
            with self.subTest(image=image),self.assertRaises(m.SandboxDenied):
                m.argv_db(RUN,image)

    def test_no_docker_before_disposable_nonroot_confirmation(self):
        with patch.object(m.os,"geteuid",return_value=0):
            with patch.object(m,"_checked") as docker:
                with self.assertRaises(m.SandboxDenied):
                    m.run_isolated_database(run_id=RUN,image=IMAGE,
                        source_locally_trusted=True,ci_disposable_host=True)
                docker.assert_not_called()
        with patch.object(m.os,"geteuid",return_value=1000):
            for flags in ((False,True),(True,False),(False,False)):
                with patch.object(m,"_checked") as docker:
                    with self.assertRaises(m.SandboxDenied):
                        m.run_isolated_database(run_id=RUN,image=IMAGE,
                            source_locally_trusted=flags[0],
                            ci_disposable_host=flags[1])
                    docker.assert_not_called()

    def test_exact_container_identity_blocks_foreign_id(self):
        wrong=(ID_DB+"|/fieldwork-api-1|"+RUN+"|db|running|false")
        with patch.object(m,"_checked",return_value=wrong):
            with self.assertRaisesRegex(m.SandboxDenied,"ID_LABEL"):
                m.observe_container(RUN,ID_DB,"db")
        with self.assertRaises(m.SandboxDenied):
            m.observe_container(RUN,"b"*63,"db")

    def test_network_disallows_foreign_attached_container(self):
        fmt=(ID_NET+"|"+m.names(RUN)["network"]+"|"+RUN+"|true")
        with patch.object(m,"_checked",side_effect=[
               fmt,json.dumps({"f"*64:{"Name":"other"}})]):
            with self.assertRaisesRegex(m.SandboxDenied,
                                        "FOREIGN_NETWORK_ENDPOINT"):
                m.observe_network(RUN,ID_NET,allowed_ids={ID_DB,ID_TEST})

    def test_network_wrong_internal_state_denied(self):
        fmt=(ID_NET+"|"+m.names(RUN)["network"]+"|"+RUN+"|false")
        with patch.object(m,"_checked",return_value=fmt):
            with self.assertRaisesRegex(m.SandboxDenied,"NETWORK_ID"):
                m.observe_network(RUN,ID_NET,allowed_ids=set())

    def test_no_permission_to_probe_unknown_docker_command(self):
        argv=(m.DOCKER,"system","prune","--all")
        with self.assertRaises(m.SandboxDenied):
            m._call(argv,expected=(m.DOCKER,"network","ls"))
        with self.assertRaises(m.SandboxDenied):
            m._call(argv,expected=argv,timeout=600)

    def test_all_owned_three_resources_removed_in_reverse_order(self):
        calls=[]
        def fake(argv,timeout=35):
            calls.append(argv)
            if argv[1:3]==("network","create"):return ID_NET
            if argv[1:3]==("container","create"):
                return ID_DB if argv[argv.index("--name")+1].endswith("-db") else ID_TEST
            if argv[1:3]==("container","start"):return argv[-1]
            if argv[1:3]==("container","wait"):return "0"
            if argv[1:3]==("container","logs"):return "1"
            if argv[1:3]==("container","rm"):return argv[-1]
            if argv[1:3]==("network","rm"):return ID_NET
            raise AssertionError(argv)
        def inspect_container(run_id,cid,role):
            return ("created" if cid == ID_TEST else "running")
        with patch.object(m.os,"geteuid",return_value=1000),\
             patch.object(m,"_checked",side_effect=fake),\
             patch.object(m,"_call",return_value=(0,"ready")),\
             patch.object(m,"observe_container",side_effect=[
                 "created","running","created","exited","exited",
                 "exited","running"]),\
             patch.object(m,"observe_network") as net:
            result=m.run_isolated_database(
                 run_id=RUN,image=IMAGE,ci_disposable_host=True,
                 source_locally_trusted=True)
        self.assertEqual(result["status"],"M15J3_EPHEMERAL_POSTGRES_SQL_PASS")
        self.assertEqual(result["m12_parity_verified"],False)
        self.assertEqual(result["m15e_activation_authorized"],False)
        self.assertEqual([x[1:3] for x in calls if x[2]=="rm"],
                         [("container","rm"),("container","rm"),("network","rm")])
        self.assertGreaterEqual(net.call_count,3)

    def test_failure_still_attempts_scoped_cleanup(self):
        calls=[]
        def fake(argv,timeout=35):
            calls.append(argv)
            if argv[1:3]==("network","create"):return ID_NET
            if argv[1:3]==("container","create"):return ID_DB
            if argv[1:3]==("container","start"):
                raise m.SandboxDenied("M15J3_FORCED_DB_START_FAIL")
            if argv[1:3]==("container","rm"):return ID_DB
            if argv[1:3]==("network","rm"):return ID_NET
            raise AssertionError(argv)
        with patch.object(m.os,"geteuid",return_value=1000),\
             patch.object(m,"_checked",side_effect=fake),\
             patch.object(m,"observe_container",side_effect=[
                 "created","created"]),\
             patch.object(m,"observe_network") as net:
            with self.assertRaisesRegex(m.SandboxDenied,"FORCED_DB_START_FAIL"):
                m.run_isolated_database(
                    run_id=RUN,image=IMAGE,ci_disposable_host=True,
                    source_locally_trusted=True)
        self.assertEqual([x[1:3] for x in calls if x[2]=="rm"],
                         [("container","rm"),("network","rm")])
        self.assertEqual(net.call_count,2)

    def test_no_host_shell_or_unrestricted_docker(self):
        source=inspect.getsource(m)
        self.assertIn("shell=False",source)
        self.assertNotIn("subprocess.Popen(",source)
        self.assertNotIn("os.system(",source)
        self.assertNotIn("import socket",source)
        for argv in (m.argv_db(RUN,IMAGE),m.argv_test(RUN,IMAGE)):
            self.assertNotIn("--mount",argv)
            self.assertNotIn("/var/run/docker.sock",argv)
            self.assertNotIn("fieldwork-db-1",argv)

    def test_false_or_malformed_network_endpoints_denied(self):
        fmt=(ID_NET+"|"+m.names(RUN)["network"]+"|"+RUN+"|true")
        for raw in ("[]","broken",json.dumps({ID_DB:"anything",ID_TEST:"anything",
                                              "0"*64:"anything"})):
            with self.subTest(raw=raw[:20]),\
                 patch.object(m,"_checked",side_effect=[fmt,raw]),\
                 self.assertRaises(m.SandboxDenied):
                m.observe_network(RUN,ID_NET,allowed_ids={ID_DB,ID_TEST})

    def test_audit_data_is_explicitly_non_authorizing(self):
        self.assertTrue(m.PROJECT.startswith("fieldwork-m15jdb-"))
        self.assertNotEqual(m.PROJECT,"fieldwork-stage")
        self.assertNotEqual(m.PROJECT,"fieldwork-")
        self.assertTrue(m.NAME_FMT.find("Privileged")>=0)


if __name__=="__main__":
    unittest.main()
