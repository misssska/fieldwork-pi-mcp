"""M15I independent local host privilege evidence tests, no host mutation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from updater import m15i_local_privilege_audit as audit


class M15IHostAuditTests(unittest.TestCase):
    def test_exact_standalone_process_argv_only(self):
        good=[
            b"/usr/bin/python3\0/opt/pi-mcp/fieldwork_mcp.py\0",
            b"python3\0fieldwork_mcp.py\0",
        ]
        for x in good:
            self.assertTrue(audit.is_mcp_script_argv(x))
        bad=[
            b"", b"python3\0-c\0print('fieldwork_mcp.py')\0",
            b"bash\0echo fieldwork_mcp.py\0",
            b"python3\0fieldwork_mcp.py.old\0",
            b"python3\0-m\0fieldwork_mcp.py\0",
            b"python3\0x/fieldwork_mcp.py/other\0",
            b"python3\0x"*5000,
        ]
        for x in bad:
            with self.subTest(x=x[:36]):
                self.assertFalse(audit.is_mcp_script_argv(x))

    def test_fixed_units_and_no_arbitrary_service(self):
        with self.assertRaises(audit.M15IAuditDenied):
            audit.read_unit_summary("ssh.service")
        with self.assertRaises(audit.M15IAuditDenied):
            audit.read_unit_summary("../production.service")

    def test_systemd_output_is_sanitized_and_fixed_query(self):
        p=subprocess.CompletedProcess(
            args=[],returncode=0,
            stdout=b"LoadState=loaded\nActiveState=active\n"
                   b"MainPID=177\nUser=fieldwork\nGroup=fieldwork\n",
            stderr=b"")
        with patch.object(audit.Path, "is_file", return_value=True):
            with patch.object(audit.subprocess, "run", return_value=p) as call:
                result=audit.read_unit_summary(
                    "fieldwork-pi-tunnel.service")
        self.assertEqual(result["pid"],177)
        self.assertEqual(result["state"],"ACTIVE")
        self.assertEqual(result["user"],"fieldwork")
        argv=call.call_args.args[0]
        self.assertEqual(argv[:3],
                         ["/usr/bin/systemctl","show","--no-pager"])
        self.assertNotIn("status",argv)
        self.assertNotIn("ExecStart",argv)

    def test_systemd_bad_duplicate_fields_deny(self):
        raw=b"LoadState=loaded\nActiveState=active\nMainPID=1\n"
        raw+=b"MainPID=2\nUser=fieldwork\nGroup=fieldwork\n"
        with patch.object(audit.Path,"is_file",return_value=True):
            with patch.object(audit.subprocess,"run",
                              return_value=subprocess.CompletedProcess(
                                  [],0,raw,b"")):
                result=audit.read_unit_summary(
                    "fieldwork-pi-tunnel.service")
        self.assertEqual(result["state"],"UNIT_UNOBSERVABLE")

    def test_no_privilege_or_work_without_local_root(self):
        with patch.object(audit.os,"geteuid",return_value=1000):
            with patch.object(audit,"discover_candidate_pids") as found:
                with self.assertRaisesRegex(audit.M15IAuditDenied,
                                            "M15I_LOCAL_ROOT_AUDIT_REQUIRED"):
                    audit.audit()
                found.assert_not_called()

    def test_no_candidates_is_incomplete_not_safe(self):
        with patch.object(audit.os,"geteuid",return_value=0):
            with patch.object(audit,"discover_candidate_pids",
                              return_value=[]):
                with patch.object(audit,"read_unit_summary",
                                  return_value={"state":"UNIT_UNOBSERVABLE"}):
                    with patch.object(audit,"installed_m15e_snapshot",
                                      return_value={"status":"UNOBSERVABLE"}):
                        result=audit.audit()
        self.assertEqual(result["candidate_count"],0)
        self.assertFalse(result["safe_to_activate_service"])
        self.assertFalse(result["safe_to_revoke_legacy_docker_access"])
        self.assertFalse(result["safe_to_install_operator_secret"])
        self.assertFalse(result["independent_mcp_binary_identity_verified"])

    def test_m15e_file_state_is_always_only_metadata(self):
        with patch.object(audit.Path, "lstat") as fake:
            fake.side_effect=FileNotFoundError()
            status=audit.installed_m15e_snapshot()
            self.assertEqual(status["status"],"M15E_INACTIVE_NOT_PRESENT")
        # No attempt to read the source or private key.

    def test_sudo_no_assurance_from_nonzero_exit(self):
        with patch.object(audit.pwd,"getpwuid",
                          return_value=type("Pw",(),{"pw_name":"fieldwork"})()):
            with patch.object(audit.Path,"is_file",return_value=True):
                with patch.object(audit.subprocess,"run",
                                  return_value=subprocess.CompletedProcess(
                                      [],1,b"",b"")):
                    self.assertEqual(audit.sudo_policy_probe(1000),
                                     "SUDO_POLICY_UNVERIFIED")

    def test_existing_sudo_rules_never_mean_safe(self):
        with patch.object(audit.pwd,"getpwuid",
                          return_value=type("Pw",(),{"pw_name":"fieldwork"})()):
            with patch.object(audit.Path,"is_file",return_value=True):
                with patch.object(audit.subprocess,"run",
                                  return_value=subprocess.CompletedProcess(
                                      [],0,b"User may run commands",b"")) as call:
                    self.assertEqual(audit.sudo_policy_probe(1000),
                                     "SUDO_POLICY_LISTED_REVIEW_REQUIRED")
        self.assertEqual(call.call_args.args[0][:4],
                         ["/usr/bin/sudo","-n","-l","-U"])

    def test_candidate_root_equivalent_is_not_approved(self):
        dummy={
            "target":{"observed_effective_uid":1000,
                      "observed_effective_gid":1000,
                      "supplementary_gids":[1000,998]},
            "default_docker_socket":"DAC_WRITE_POSSIBLE",
            "observed_capabilities_nonzero":False,
            "observed_no_new_privileges":False,
        }
        with patch.object(audit,"_fixed_proc_file",side_effect=[
                b"stat",b"status"]):
            with patch.object(audit.m15f,"starttime_from_stat",
                              return_value=23456):
                with patch.object(audit.preflight,"_parse_status",
                                  return_value={"uids":(1000,1000,1000,1000)}):
                    with patch.object(audit.m15f,"collect_local",
                                      return_value=dummy):
                        with patch.object(audit.grp,"getgrnam",
                                          return_value=type("Gr",(),{"gr_gid":998})()):
                            with patch.object(audit,"sudo_policy_probe",
                                              return_value="SUDO_POLICY_UNVERIFIED"):
                                result=audit.assess_candidate(
                                    234,units=[{"unit":"fieldwork-pi-mcp.service",
                                                "pid":234,"state":"ACTIVE"}])
        self.assertTrue(result["root_equivalent_indicator_present"])
        self.assertTrue(result["docker_group_membership_observed"])
        self.assertEqual(result["systemd_mainpid_match"],
                         ["fieldwork-pi-mcp.service"])
        self.assertFalse(result["privilege_separation_verified"])
        self.assertFalse(result["safe_to_install_operator_secret"])

    def test_no_host_mutation_or_docker_api_in_source(self):
        import inspect
        source=inspect.getsource(audit)
        for forbidden in ("docker run","docker stop","docker compose",
                          "docker exec","subprocess.Popen(","shell=True",
                          "systemctl restart","systemctl enable","os.chmod(",
                          "os.chown(","os.setuid(","os.remove(",
                          "unlink(","rmtree(","os.mkdir("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,source)

    def test_native_root_report_is_non_authorizing(self):
        # No host-specific assumptions on CI. Test the executing process's
        # kernel metadata separately in M15F; this report is NEVER an approval.
        with patch.object(audit.os,"geteuid",return_value=0),\
             patch.object(audit,"discover_candidate_pids",return_value=[111]),\
             patch.object(audit,"assess_candidate",
                          return_value={"root_equivalent_indicator_present":True}),\
             patch.object(audit,"read_unit_summary",
                          return_value={"pid":0,"state":"UNIT_UNOBSERVABLE"}),\
             patch.object(audit,"installed_m15e_snapshot",
                          return_value={"status":"M15E_INACTIVE_NOT_PRESENT"}):
            result=audit.audit()
        self.assertTrue(result["potential_root_equivalent_runtime"])
        self.assertFalse(result["safe_to_activate_service"])
        self.assertFalse(result["safe_to_revoke_legacy_docker_access"])


if __name__ == "__main__":
    unittest.main()
