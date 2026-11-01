"""M15-D privilege evidence: offline negatives plus native self-only smoke.

No test touches the Pi, Docker engine, sudoers, or production files.
"""
from __future__ import annotations

import inspect
import json
import os
import stat
from types import SimpleNamespace
import unittest
from updater import linux_host_privilege_preflight as audit


def proc(*, uid=1001, gid=1001, groups=(998,), caps="0000000000000000",
         nnp="1"):
    return (
        "Name:\\ttest\\n"
        f"Uid:\\t{uid} {uid} {uid} {uid}\\n"
        f"Gid:\\t{gid} {gid} {gid} {gid}\\n"
        "Groups:\\t" + " ".join(str(x) for x in groups) + "\\n"
        f"CapEff:\\t{caps}\\n"
        f"NoNewPrivs:\\t{nnp}\\n"
    ).replace("\\n", "\n").replace("\\t", "\t").encode("ascii")


def socket(*, mode=0o660, uid=0, gid=998):
    return SimpleNamespace(st_mode=stat.S_IFSOCK | mode,
                           st_uid=uid, st_gid=gid)


def evaluate(raw=None, *, euid=1001, egid=1001, groups=(998,),
             sock=None, opaque=False):
    if raw is None:
        raw = proc(uid=euid, gid=egid, groups=groups)
    return audit.evaluate(raw, euid=euid, egid=egid,
                          supplementary_groups=groups,
                          docker_socket_stat=sock,
                          socket_unobservable=opaque)


class LocalPrivilegeEvidenceTests(unittest.TestCase):
    def test_unprivileged_self_still_never_authorizes(self):
        result = evaluate()
        self.assertEqual(result["status"], "SELF_PRIVILEGE_EVIDENCE_INCOMPLETE")
        self.assertEqual(result["scope"], "INVOKING_PROCESS_ONLY")
        self.assertEqual(result["docker_socket"], "ABSENT_AT_FIXED_PATH")
        self.assertFalse(result["activation_authorized"])
        self.assertFalse(result["privilege_separation_verified"])
        self.assertEqual(result["sudo_policy"], "NOT_AUDITED")
        self.assertEqual(result["inherited_file_descriptors"], "NOT_AUDITED")
        self.assertEqual(result["user_namespace_host_mapping"], "NOT_AUDITED")

    def test_effective_root_always_risk(self):
        result = evaluate(euid=0, egid=0, groups=())
        self.assertIn("EFFECTIVE_ROOT", result["indicators"])
        self.assertFalse(result["activation_authorized"])

    def test_effective_capability_is_detected_without_claiming_root(self):
        raw = proc(caps="0000000000200000")
        result = evaluate(raw)
        self.assertIn("EFFECTIVE_LINUX_CAPABILITIES", result["indicators"])
        self.assertTrue(result["cap_eff_nonzero"])
        self.assertFalse(result["privilege_separation_verified"])

    def test_no_new_privs_disabled_cannot_clear_gate(self):
        result = evaluate(proc(nnp="0"))
        self.assertIn("NO_NEW_PRIVS_DISABLED", result["indicators"])
        self.assertFalse(result["activation_authorized"])

    def test_docker_socket_group_write_detected(self):
        result = evaluate(sock=socket())
        self.assertEqual(result["docker_socket"], "DAC_WRITE_POSSIBLE")
        self.assertIn("DOCKER_SOCKET_WRITE_POSSIBLE", result["indicators"])

    def test_socket_owner_and_world_write_are_detected(self):
        for kwargs, groups in (({"mode":0o600,"uid":1001,"gid":999},()),
                               ({"mode":0o002,"uid":0,"gid":999},())):
            with self.subTest(kwargs=kwargs):
                result = evaluate(groups=groups, sock=socket(**kwargs))
                self.assertEqual(result["docker_socket"], "DAC_WRITE_POSSIBLE")

    def test_socket_without_dac_rights_is_not_trusted_absence_proof(self):
        result = evaluate(groups=(), sock=socket(gid=998,mode=0o660))
        self.assertEqual(result["docker_socket"], "DAC_WRITE_NOT_OBSERVED")
        self.assertFalse(result["activation_authorized"])
        self.assertEqual(result["acl_lsm_socket_rights"], "NOT_AUDITED")

    def test_non_socket_and_symlink_are_fail_closed(self):
        foreign = SimpleNamespace(st_mode=stat.S_IFREG | 0o666,
                                  st_uid=1001, st_gid=1001)
        out = evaluate(sock=foreign)
        self.assertIn("DOCKER_PATH_NOT_A_SOCKET", out["indicators"])
        out = evaluate(opaque=True)
        self.assertEqual(out["docker_socket"], "UNVERIFIED_ACCESS_OR_SYMLINK")
        self.assertIn("DOCKER_SOCKET_UNVERIFIED", out["indicators"])

    def test_invalid_pid_identity_and_groups_rejected(self):
        with self.assertRaisesRegex(audit.PrivilegePreflightDenied,
                                    "PROC_PROCESS_IDENTITY_MISMATCH"):
            evaluate(proc(uid=0))
        with self.assertRaisesRegex(audit.PrivilegePreflightDenied,
                                    "PROC_PROCESS_IDENTITY_MISMATCH"):
            evaluate(proc(groups=(5,)))
        with self.assertRaisesRegex(audit.PrivilegePreflightDenied,
                                    "PROCESS_ID_INPUT_DENIED"):
            audit.evaluate(proc(),euid=True,egid=1001,
                           supplementary_groups=(998,),docker_socket_stat=None)

    def test_missing_duplicate_malformed_and_overlong_status_rejected(self):
        cases = (
            proc().replace(b"CapEff:", b"Other:"),
            proc() + b"Uid: 1001 1001 1001 1001\n",
            proc(caps="nothex"),
            proc(nnp="yes"),
            proc(groups=(998,998)),
            proc() + b"X:" + b"a" * 20000,
            b"\xff" + proc(),
        )
        for raw in cases:
            with self.subTest(case=raw[:32]), self.assertRaises(
                    audit.PrivilegePreflightDenied):
                evaluate(raw)

    def test_current_linux_process_can_only_produce_evidence(self):
        if os.name != "posix" or not os.path.exists("/proc/self/status"):
            self.skipTest("Linux procfs only")
        observed = audit.collect()
        self.assertEqual(observed["scope"], "INVOKING_PROCESS_ONLY")
        self.assertFalse(observed["activation_authorized"])
        self.assertFalse(observed["privilege_separation_verified"])
        self.assertFalse(observed["host_modified"])
        self.assertTrue(json.dumps(observed))

    def test_no_shell_docker_subprocess_or_mutation_entrypoint(self):
        source = inspect.getsource(audit)
        for forbidden in ("subprocess", "os.system(", "os.chmod(",
                          "os.chown(", "os.unlink(", "os.remove(",
                          "docker run", "sudo -n", "shell=True"):
            with self.subTest(forbidden=forbidden):
                # The docstring may mention the word subprocess by design;
                # block importing and calling execution capabilities instead.
                if forbidden == "subprocess":
                    self.assertNotIn("import subprocess", source)
                else:
                    self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
