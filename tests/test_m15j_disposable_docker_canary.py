"""M15J2 Docker canary negative contracts, complete mock lifecycle, no Pi calls."""
from __future__ import annotations
from unittest.mock import patch
import inspect
import unittest
from updater import m15j_disposable_docker_canary as c

RUN="a"*32
ID="b"*64
IMAGE="docker.io/library/alpine@sha256:"+"c"*64


class CanaryContracts(unittest.TestCase):
    def test_fully_pinned_docker_create_hardening(self):
        argv=c.build_create_argv(run_id=RUN,trusted_image=IMAGE)
        self.assertEqual(argv[:3],("/usr/bin/docker","container","create"))
        self.assertEqual(argv[-1],IMAGE)
        expected=("--network","none","--read-only","--cap-drop","ALL",
                  "--security-opt","no-new-privileges",
                  "--pids-limit","32","--memory","64m",
                  "--cpus","0.50","--user","65534:65534",
                  "--workdir","/","--entrypoint","/bin/true")
        for x in expected:
            self.assertIn(x,argv)
        for flag in ("--privileged","--mount","--volume","-v","-p",
                     "--publish","--network=host","--pid=host",
                     "--device","--cap-add","--security-opt=apparmor:unconfined",
                     "--userns=host"):
            self.assertNotIn(flag,argv)

    def test_run_id_and_mutable_image_denied(self):
        for runid in ("bad","a"*31,"A"*32,"../"+"a"*29,
                      "a"*32+"x",None,True):
            with self.subTest(runid=str(runid)[:35]),self.assertRaises(
                    c.CanaryDenied):
                c.build_create_argv(run_id=runid,trusted_image=IMAGE)
        for image in ("alpine:latest","alpine:3.20","/etc/passwd",
                      "alpine@sha256:"+"f"*63,
                      "alpine@sha256:"+"g"*64,
                      "alpine --privileged@sha256:"+"f"*64,None):
            with self.subTest(image=image),self.assertRaises(c.CanaryDenied):
                c.build_create_argv(run_id=RUN,trusted_image=image)

    def test_never_invoke_host_docker_without_disposable_ci_nonroot(self):
        with patch.object(c.os,"geteuid",return_value=1000):
            for flags in ((False,True),(True,False),(False,False)):
                with patch.object(c,"_run") as backend:
                    with self.assertRaises(c.CanaryDenied):
                        c.run_canary(run_id=RUN,trusted_image=IMAGE,
                           source_locally_trusted=flags[0],
                           ci_disposable_host=flags[1])
                    backend.assert_not_called()
        with patch.object(c.os,"geteuid",return_value=0):
            with patch.object(c,"_run") as backend:
                with self.assertRaises(c.CanaryDenied):
                    c.run_canary(run_id=RUN,trusted_image=IMAGE,
                                  source_locally_trusted=True,
                                  ci_disposable_host=True)
                backend.assert_not_called()

    def test_fixed_argv_match_cannot_be_command_injection(self):
        argv=("/usr/bin/docker","container","rm","--force",ID)
        with self.assertRaises(c.CanaryDenied):
            c._run(argv,expected=("echo","fake"))
        with self.assertRaises(c.CanaryDenied):
            c._run(["/usr/bin/docker","container","rm",ID],
                   expected=argv)
        with self.assertRaises(c.CanaryDenied):
            c._run(argv,expected=argv,timeout=400)

    def test_successful_full_mock_lifecycle_and_cleanup(self):
        calls=[]
        def fake(argv,*,expected,timeout=30):
            self.assertEqual(argv,expected)
            calls.append(argv[2])
            return {"create":ID,"start":ID,"wait":"0","rm":ID}[argv[2]]
        with patch.object(c.os,"geteuid",return_value=1000),\
             patch.object(c,"_run",side_effect=fake),\
             patch.object(c,"_inspect",side_effect=["created","running",
                                                   "exited","exited"]):
            result=c.run_canary(run_id=RUN,trusted_image=IMAGE,
                                source_locally_trusted=True,
                                ci_disposable_host=True)
        self.assertEqual(calls,["create","start","wait","rm"])
        self.assertEqual(result["status"],
          "M15J_CI_ONLY_ISOLATED_DOCKER_LIFECYCLE_PASS")
        self.assertTrue(result["container_removed"])
        self.assertFalse(result["host_mount_used"])
        self.assertFalse(result["cutover_authorized"])

    def test_container_drift_refuses_delete(self):
        def fake(argv,*,expected,timeout=30):
            if argv[2]=="rm":
                self.fail("MUST NOT DELETE UNOWNED CONTAINER")
            return ID
        with patch.object(c.os,"geteuid",return_value=1000),\
             patch.object(c,"_run",side_effect=fake),\
             patch.object(c,"_inspect",side_effect=[
                 "created","running","exited",
                 c.CanaryDenied("M15J_CANARY_CONTAINER_IDENTITY_OR_OWNERSHIP_DRIFT")]):
            with self.assertRaises(c.CanaryDenied):
                c.run_canary(run_id=RUN,trusted_image=IMAGE,
                             source_locally_trusted=True,
                             ci_disposable_host=True)

    def test_failed_canary_rechecks_ownership_and_cleans(self):
        calls=[]
        def fake(argv,*,expected,timeout=30):
            calls.append(argv[2])
            if argv[2]=="create":return ID
            if argv[2]=="start":raise c.CanaryDenied("FORCED_START_FAIL")
            if argv[2]=="rm":return ID
            self.fail("unexpected")
        with patch.object(c.os,"geteuid",return_value=1000),\
             patch.object(c,"_run",side_effect=fake),\
             patch.object(c,"_inspect",side_effect=["created","created"]):
            with self.assertRaisesRegex(c.CanaryDenied,"FORCED_START_FAIL"):
                c.run_canary(run_id=RUN,trusted_image=IMAGE,
                             source_locally_trusted=True,
                             ci_disposable_host=True)
        self.assertEqual(calls,["create","start","rm"])

    def test_no_shell_host_mount_or_arbitrary_command_in_source(self):
        src=inspect.getsource(c)
        for forbidden in ("shell=True","os.system(", "os.chown(",
                          "os.chmod(","docker.sock","systemctl",
                          "--mount=type=bind","--privileged",
                          "subprocess.Popen("):
            with self.subTest(f=forbidden):
                # Some forbidden strings occur in documented deny examples
                # outside the actual command builder; check builder only.
                self.assertNotIn(forbidden,
                  inspect.getsource(c.build_create_argv))
        self.assertIn('shell=False',src)

    def test_pinned_ownership_inspect_only_full_64_id(self):
        for bad in (RUN,"b"*63,True,None,"fieldwork-api-1"):
            with self.subTest(id=bad),self.assertRaises(c.CanaryDenied):
                c._inspect(RUN,bad)

    def test_no_cli_host_executor(self):
        self.assertNotIn("argparse",inspect.getsource(c))
        self.assertNotIn("run_canary(",inspect.getsource(c).split(
            'if __name__ == "__main__":')[-1])


if __name__=="__main__":
    unittest.main()
