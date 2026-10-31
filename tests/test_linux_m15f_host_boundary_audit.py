"""M15F local-only PID audit: tamper/race/permission and native smoke."""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from updater import linux_m15f_host_boundary_audit as audit

PID = 2304
UID = 1001
GID = 1002
START = 729582


def proc_stat(pid=PID, start=START, comm="python3 (worker)", state="S"):
    # Linux /proc/PID/stat: field 3 state, field 22 starttime.
    fields = [state] + ["0"] * 18 + [str(start)] + ["0"] * 24
    return (f"{pid} ({comm}) " + " ".join(fields) + "\n").encode("ascii")


def status(uid=UID, gid=GID, groups=(998,), cap="0000000000000000",
           nnp="1"):
    return (f"Name:\tpython\nUid:\t{uid} {uid} {uid} {uid}\n"
            f"Gid:\t{gid} {gid} {gid} {gid}\n"
            "Groups:\t" + " ".join(str(x) for x in groups) + "\n"
            f"CapEff:\t{cap}\nNoNewPrivs:\t{nnp}\n").encode("ascii")


def sock(mode=0o660, uid=0, gid=998):
    return SimpleNamespace(st_mode=stat.S_IFSOCK | mode, st_uid=uid,
                           st_gid=gid)


def assess(*, before=None, after=None, proc=None, expected_uid=UID,
           socket_metadata=None, socket_unobservable=False):
    return audit.assess_observation(
        pid=PID, expected_uid=expected_uid, expected_starttime=START,
        stat_before=proc_stat() if before is None else before,
        status=status() if proc is None else proc,
        stat_after=proc_stat() if after is None else after,
        docker_socket=socket_metadata,
        docker_socket_unobservable=socket_unobservable)


class PinnedPidAuditTests(unittest.TestCase):
    def test_success_is_never_authorizing_even_with_empty_indicators(self):
        r = assess(proc=status(nnp="1",groups=()),socket_metadata=None)
        self.assertEqual(r["status"], "HOST_BOUNDARY_AUDIT_INCOMPLETE")
        self.assertEqual(r["target"]["starttime_ticks"], START)
        self.assertFalse(r["host_writes"])
        self.assertFalse(r["remote_mcp_tool"])
        self.assertFalse(r["isolation_verified"])
        self.assertFalse(r["safe_to_revoke_legacy_docker_access"])
        self.assertFalse(r["safe_to_install_operator_secret"])
        self.assertFalse(r["production_deployment_authorized"])
        self.assertEqual(r["limits"]["inherited_open_fds"], "NOT_AUDITED")
        self.assertEqual(r["limits"]["sudoers_and_setuid"], "NOT_AUDITED")

    def test_proc_stat_comm_with_space_parenthesis_not_shifted(self):
        raw = proc_stat(comm="worker foo (hello) )")
        self.assertEqual(audit.starttime_from_stat(raw,PID),START)

    def test_target_pid_reuse_or_disappearing_is_refused(self):
        for kwargs in (
            {"before":proc_stat(start=START+1)},
            {"after":proc_stat(start=START+1)},
            {"before":proc_stat(pid=PID+1)},
            {"after":proc_stat(pid=PID+1)},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(
                    audit.HostBoundaryDenied):
                assess(**kwargs)

    def test_zombie_and_invalid_stat_rejected(self):
        for bad in (proc_stat(state="Z"),proc_stat(state="X"),
                    f"{PID} (test) S 0\n".encode(),
                    b"random", b"\xff",b"0"*5000):
            with self.subTest(raw=bad[:30]),self.assertRaises(
                    audit.HostBoundaryDenied):
                assess(before=bad)

    def test_wrong_effective_uid_is_rejected(self):
        with self.assertRaisesRegex(audit.HostBoundaryDenied,
                                    "HOST_TARGET_UID_MISMATCH"):
            assess(expected_uid=UID+1)
        with self.assertRaisesRegex(audit.HostBoundaryDenied,
                                    "HOST_TARGET_UID_MISMATCH"):
            assess(proc=status(uid=0))

    def test_capabilities_root_and_disabled_nnp_are_risk_signals(self):
        result=assess(proc=status(uid=0,gid=0,groups=(0,998),
                                  cap="0000000000002000",nnp="0"),
                      expected_uid=0)
        self.assertIn("TARGET_ROOT_ID_PRESENT",result["risk_indicators"])
        self.assertIn("TARGET_EFFECTIVE_CAPABILITIES",result["risk_indicators"])
        self.assertIn("TARGET_NO_NEW_PRIVS_DISABLED",result["risk_indicators"])
        self.assertFalse(result["isolation_verified"])

    def test_docker_default_socket_dac_write_risk(self):
        r=assess(socket_metadata=sock())
        self.assertEqual(r["default_docker_socket"],"DAC_WRITE_POSSIBLE")
        self.assertIn("DOCKER_DEFAULT_SOCKET_DAC_WRITE",r["risk_indicators"])
        self.assertFalse(r["safe_to_revoke_legacy_docker_access"])

    def test_docker_socket_denial_does_not_prove_absence(self):
        denied=assess(proc=status(groups=()),socket_metadata=sock())
        self.assertEqual(denied["default_docker_socket"],
                         "DAC_WRITE_NOT_OBSERVED_ONLY")
        self.assertFalse(denied["isolation_verified"])
        absent=assess(socket_metadata=None)
        self.assertEqual(absent["default_docker_socket"],
                         "ABSENT_AT_DEFAULT_PATH_ONLY")
        self.assertFalse(absent["safe_to_install_operator_secret"])

    def test_docker_symlink_opaque_and_unexpected_file_block(self):
        opaque=assess(socket_unobservable=True)
        self.assertIn("DOCKER_DEFAULT_SOCKET_UNVERIFIED",
                      opaque["risk_indicators"])
        fake=SimpleNamespace(st_mode=stat.S_IFREG|0o666,
                             st_uid=UID,st_gid=GID)
        r=assess(socket_metadata=fake)
        self.assertIn("DOCKER_DEFAULT_PATH_NOT_SOCKET",r["risk_indicators"])
        with self.assertRaisesRegex(audit.HostBoundaryDenied,
                                    "HOST_SOCKET_INPUT_DENIED"):
            assess(socket_metadata=sock(),socket_unobservable=True)

    def test_malformed_status_or_duplicate_fields_is_denied(self):
        for bad in (status().replace(b"Uid:",b"Unknown:"),
                    status()+b"Uid:\t1001 1001 1001 1001\n",
                    status(cap="NOT-HEX"),status(nnp="9"),
                    status()+b"a"*20000,b"\xff"+status()):
            with self.subTest(raw=bad[:24]),self.assertRaises(
                    audit.HostBoundaryDenied):
                assess(proc=bad)

    def test_wrong_inputs_rejected(self):
        for p,uid,start in ((0,UID,START),(MAX_PID(),UID,START),
                            (True,UID,START),(PID,True,START),
                            (PID,UID,0),(PID,UID,"not-int")):
            with self.subTest(p=p,uid=uid,start=start),self.assertRaises(
                    audit.HostBoundaryDenied):
                audit.assess_observation(
                    pid=p, expected_uid=uid, expected_starttime=start,
                    stat_before=proc_stat(), status=status(),
                    stat_after=proc_stat(),docker_socket=None)

    def test_proc_file_symlink_denied_without_following(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            real=root/"real"
            real.write_bytes(proc_stat())
            alias=root/"alias"
            alias.symlink_to(real)
            with self.assertRaises(audit.HostBoundaryDenied):
                audit._read_proc(alias,audit.MAX_STAT)

    def test_native_proc_self_is_usable_but_not_a_permission_gate(self):
        if os.name != "posix" or not Path("/proc/self/status").exists():
            self.skipTest("Linux procfs only")
        pid=os.getpid()
        raw=audit._read_proc(Path("/proc")/str(pid)/"stat",audit.MAX_STAT)
        start=audit.starttime_from_stat(raw,pid)
        observed=audit.collect_local(
            pid=pid,expected_uid=os.geteuid(),expected_starttime=start)
        self.assertEqual(observed["target"]["pid"],pid)
        self.assertFalse(observed["isolation_verified"])
        self.assertFalse(observed["production_deployment_authorized"])

    def test_cli_refuses_nonexistent_pid_without_false_success(self):
        with patch.object(audit,"collect_local",
                          side_effect=audit.HostBoundaryDenied("HOST_NO_PID")):
            from io import StringIO
            with patch("sys.stdout",new_callable=StringIO) as sink:
                code=audit.main(["--pid","500","--expected-uid","1000",
                                 "--expected-starttime","100"])
            self.assertEqual(code,2)
            result=json.loads(sink.getvalue())
            self.assertFalse(result["production_deployment_authorized"])

    def test_no_subprocess_shell_docker_command_or_mutating_host_logic(self):
        source=inspect.getsource(audit)
        for forbidden in ("import subprocess", "subprocess.run(",
                          "os.system(", "os.remove(", "os.unlink(",
                          "os.chmod(", "os.chown(", "shell=True",
                          "docker run", "sudo -n"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,source)


def MAX_PID():
    return audit.MAX_PID + 1


if __name__=="__main__":
    unittest.main()
