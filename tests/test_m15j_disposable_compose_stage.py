"""M15J4 fixed Compose staging fixture contract and failure cleanup."""
from __future__ import annotations
import copy
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import m15j_disposable_compose_stage as s

RUN="a"*32
N="docker.io/library/nginx@sha256:"+"b"*64
P="docker.io/library/postgres@sha256:"+"c"*64
PROJECT="fieldwork-m15jstage-"+RUN


class StageComposeTests(unittest.TestCase):
    def test_exact_images_and_project_only(self):
        self.assertEqual(s.qualify(RUN,N,P),PROJECT)
        for bad in ("main","../opt","A"*32,"d"*31,True,None):
            with self.subTest(id=bad),self.assertRaises(s.StageFixtureDenied):
                s.qualify(bad,N,P)
        for bad in ("nginx:latest","postgres@sha256:"+"b"*64,
                    "nginx@sha256:"+"X"*64):
            with self.subTest(image=bad),self.assertRaises(s.StageFixtureDenied):
                s.qualify(RUN,bad,P)
        with self.assertRaises(s.StageFixtureDenied):
            s.qualify(RUN,N,"postgres:16-alpine")

    def test_no_mount_port_privileged_or_extra_service_in_generated_model(self):
        d=s.compose_model(project=PROJECT,nginx_image=N,pg_image=P)
        self.assertEqual(set(d["services"]),{"api","db","nginx"})
        self.assertTrue(d["networks"]["default"]["internal"])
        for name,service in d["services"].items():
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"],["ALL"])
            self.assertEqual(service["security_opt"],["no-new-privileges:true"])
            for banned in ("ports","privileged","devices","volumes",
                           "network_mode","pid","ipc","extra_hosts",
                           "volumes_from","userns_mode","container_name",
                           "env_file","restart","cap_add"):
                self.assertNotIn(banned,service)
        self.assertNotIn("volumes",d)
        self.assertEqual(set(d["services"]["nginx"]["depends_on"]),{"api"})
        self.assertEqual(set(d["services"]["api"]["depends_on"]),{"db"})

    def test_fixture_uses_pinned_base_images_and_no_external_context(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            file=s._write_fixture(root,project=PROJECT,nginx_image=N,pg_image=P)
            self.assertEqual(file.name,"compose.json")
            for name in ("api","nginx"):
                docker=(root/name/"Dockerfile").read_text()
                self.assertTrue(docker.startswith("FROM "+N+"\n"))
                self.assertIn("COPY default.conf",docker)
                self.assertNotIn("RUN ",docker)
                self.assertNotIn("ARG ",docker)
                self.assertNotIn("ADD ",docker)

    def test_composed_actions_are_fixed_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"compose.json"
            file.write_text("{}")
            for action in (("build",),("down",),
                           ("up","--detach","--wait","--wait-timeout","90")):
                a=s._compose_args(PROJECT,file,*action)
                self.assertEqual(a[:4],(s.DOCKER,"compose","-p",PROJECT))
            for bad in (("up","--build"),("exec","-T","db","sh"),
                        ("down","--volumes"),("rm","--force"),
                        ("build","--no-cache","--build-arg","X=Y")):
                with self.subTest(action=bad),self.assertRaises(s.StageFixtureDenied):
                    s._compose_args(PROJECT,file,*bad)

    def test_stop_if_foreign_compose_project_container_seen(self):
        with patch.object(s,"_docker",return_value=
                          "fieldwork-api-1|api"):
            with self.assertRaisesRegex(s.StageFixtureDenied,"FOREIGN_CONTAINER"):
                s._project_containers(PROJECT)
        with patch.object(s,"_docker",return_value=
                          PROJECT+"-api-1|api\n"+PROJECT+"-api-1|api"):
            with self.assertRaisesRegex(s.StageFixtureDenied,"DUPLICATE_CONTAINER"):
                s._project_containers(PROJECT)

    def test_root_or_untrusted_source_denied_before_io(self):
        with patch.object(s.os,"geteuid",return_value=0),\
             patch.object(s,"_docker") as docker:
            with self.assertRaises(s.StageFixtureDenied):
                s.run_fixed_stage(run_id=RUN,nginx_image=N,pg_image=P,
                    source_locally_trusted=True,ci_disposable_host=True)
            docker.assert_not_called()
        with patch.object(s.os,"geteuid",return_value=1000),\
             patch.object(s,"_docker") as docker:
            with self.assertRaises(s.StageFixtureDenied):
                s.run_fixed_stage(run_id=RUN,nginx_image=N,pg_image=P,
                    source_locally_trusted=False,ci_disposable_host=True)
            docker.assert_not_called()

    def test_full_mock_build_up_http_sql_down_and_no_residue(self):
        operations=[]
        def fake(argv,*,timeout=120):
            operations.append(argv)
            if argv[-1:] == ("build",):return ""
            if argv[-5:] == ("up","--detach","--wait","--wait-timeout","90"):return ""
            if argv[-1:] == ("down",):return ""
            if "wget" in argv:return "ok"
            if "psql" in argv:return "1"
            raise AssertionError(argv)
        with patch.object(s.os,"geteuid",return_value=1000),\
             patch.object(s,"_docker",side_effect=fake),\
             patch.object(s,"_project_containers",
                          side_effect=[[("a","api")],[("a","api")],[]]):
            r=s.run_fixed_stage(run_id=RUN,nginx_image=N,pg_image=P,
                 source_locally_trusted=True,ci_disposable_host=True)
        self.assertEqual(r["status"],
            "M15J4_NATIVE_COMPOSE_BUILD_UP_HTTP_SQL_DOWN_PASS")
        self.assertTrue(r["compose_resources_cleaned"])
        self.assertFalse(r["real_fieldwork_stage_release_parity"])
        self.assertEqual(sum(x[-1:] == ("down",) for x in operations),1)

    def test_error_also_runs_down(self):
        operations=[]
        def fake(argv,*,timeout=120):
            operations.append(argv)
            if argv[-1:] == ("build",):return ""
            if argv[-5:] == ("up","--detach","--wait","--wait-timeout","90"):
                raise s.StageFixtureDenied("STAGE_UP_FAIL")
            if argv[-1:] == ("down",):return ""
            raise AssertionError(argv)
        with patch.object(s.os,"geteuid",return_value=1000),\
             patch.object(s,"_docker",side_effect=fake),\
             patch.object(s,"_project_containers",return_value=[]):
            with self.assertRaisesRegex(s.StageFixtureDenied,"STAGE_UP_FAIL"):
                s.run_fixed_stage(run_id=RUN,nginx_image=N,pg_image=P,
                    source_locally_trusted=True,ci_disposable_host=True)
        self.assertTrue(any(x[-1:] == ("down",) for x in operations))

    def test_no_arbitrary_shell_or_mcp_activation(self):
        source=inspect.getsource(s)
        self.assertIn("shell=False",source)
        for bad in ("import shlex","os.system(","subprocess.Popen(",
                    "systemctl enable","docker.sock","/opt/fieldwork"):
            self.assertNotIn(bad,source)

    def test_wrong_project_container_service_denied(self):
        with patch.object(s,"_docker",
                          return_value=PROJECT+"-redis-1|redis"):
            with self.assertRaises(s.StageFixtureDenied):
                s._project_containers(PROJECT)


if __name__=="__main__":
    unittest.main()
