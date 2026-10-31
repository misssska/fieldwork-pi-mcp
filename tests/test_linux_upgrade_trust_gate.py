"""M14C privilege boundary checks: negative-first, no host mutation."""
from pathlib import Path
import stat
import unittest
from unittest.mock import patch, MagicMock
from updater import linux_upgrade_trust_gate as m


class TrustBoundaryTests(unittest.TestCase):
    def test_unprivileged_socket_user_still_blocked(self):
        r = m.evaluate_remote_mcp(m.ProcessProbe(1000,1000,(1000,998),True,True,True))
        self.assertIn("REMOTE_MCP_DOCKER_SOCKET_WRITE_ACCESS",r["blockers"])
        self.assertFalse(r["ready_for_local_approval_secret"])
        self.assertFalse(r["write_performed"])

    def test_root_process_blocked_without_docker(self):
        r = m.evaluate_remote_mcp(m.ProcessProbe(0,0,(0,),False,False,False))
        self.assertIn("REMOTE_MCP_ROOT_CAPABILITY",r["blockers"])

    def test_even_socket_inaccessible_does_not_claim_secure_separation(self):
        r = m.evaluate_remote_mcp(m.ProcessProbe(1001,1001,(1001,),True,False,True))
        self.assertEqual(r["status"],"PRIVILEGE_ISOLATION_BLOCKED")
        self.assertIn("OTHER_PRIVILEGED_PATHS_NOT_INDEPENDENTLY_AUDITED",r["blockers"])
        self.assertFalse(r["ready_for_local_approval_secret"])

    def test_suspicious_socket_type_fails(self):
        r=m.evaluate_remote_mcp(m.ProcessProbe(1001,1001,(),True,False,False))
        self.assertIn("DOCKER_SOCKET_UNEXPECTED_TYPE",r["blockers"])

    def test_same_uid_or_readable_key_blocks_local_approver(self):
        r=m.compare_operator_boundary(remote_mcp_euid=1000,operator_euid=1000,operator_secret_readable_by_mcp=False)
        self.assertEqual(r["status"],"ROLE_BOUNDARY_BLOCKED")
        r=m.compare_operator_boundary(remote_mcp_euid=1000,operator_euid=1002,operator_secret_readable_by_mcp=True)
        self.assertEqual(r["status"],"ROLE_BOUNDARY_BLOCKED")
        self.assertIn("REMOTE_MCP_CAN_READ_OPERATOR_SECRET",r["blockers"])
        r=m.compare_operator_boundary(remote_mcp_euid=1000,operator_euid=1002,operator_secret_readable_by_mcp=False)
        self.assertEqual(r["status"],"ROLE_BOUNDARY_PRELIMINARY_PASS")
        self.assertFalse(r["local_approval_enabled"])

    def test_invalid_forged_probe_fails(self):
        for fake in [
            {"euid":0}, "ok", None,
            m.ProcessProbe(True,1000,(),True,False,True),
            m.ProcessProbe(1000,1000,(True,),True,False,True),
            m.ProcessProbe(1000,1000,(),"yes",False,True),
        ]:
            with self.subTest(fake=fake),self.assertRaises(m.TrustDenied):
                m.evaluate_remote_mcp(fake)

    def test_probe_exact_socket_and_no_mutating_calls(self):
        with self.assertRaisesRegex(m.TrustDenied,"TRUST_SOCKET_PATH_DENIED"):
            m.probe_mcp_process(docker_socket=Path("/tmp/malicious"))
        import inspect
        src=inspect.getsource(m)
        for forbidden in ("import subprocess","subprocess.run(","os.system(","docker stop","sudo -n",
                          "os.chmod(",".write_bytes(",".unlink(","shell=True"):
            self.assertNotIn(forbidden,src)

    def test_probe_rootless_or_missing_socket_not_asserted_safe(self):
        fake_path=MagicMock(spec=Path)
        fake_path.is_absolute.return_value=True
        fake_path.__str__.return_value="/var/run/docker.sock"
        fake_path.stat.side_effect=FileNotFoundError()
        with patch.object(m.os,"geteuid",return_value=1000), patch.object(m.os,"getegid",return_value=1000),patch.object(m.os,"getgroups",return_value=[1000]):
            r=m.probe_mcp_process(docker_socket=fake_path)
        result=m.evaluate_remote_mcp(r)
        self.assertFalse(result["docker_socket_present"])
        self.assertEqual(result["status"],"PRIVILEGE_ISOLATION_BLOCKED")


if __name__=="__main__":
    unittest.main()
