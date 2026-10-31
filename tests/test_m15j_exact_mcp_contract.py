"""M15-J1 exact live catalog, rootful-Docker segregation, shadow gate tests."""
from __future__ import annotations
import copy
import hashlib
import inspect
import json
import unittest

from updater import m15j_exact_mcp_contract as c


def evidence():
    return [{
        "tool": n, "route": c.route(n), "outcome": "PASS",
        "evidence_sha256": hashlib.sha256(n.encode("ascii")).hexdigest(),
    } for n in c.EXPECTED]


class ExactMCPMigrationTests(unittest.TestCase):
    def test_all_exact_thirty_six_names_are_individually_accounted_for(self):
        m=c.tool_manifest()
        self.assertEqual(len(c.EXPECTED),36)
        self.assertEqual(m["count"],36)
        self.assertEqual(len(set(x["name"] for x in m["tools"])),36)
        self.assertEqual(sum(m["counts"].values()),36)
        self.assertFalse(m["cutover_authorized"])
        self.assertFalse(m["legacy_mcp_docker_restrictions_changed"])

    def test_actual_docker_coupling_not_misclassified_as_read_only(self):
        for name in ("fieldwork_stage_full_test","fieldwork_stage_start",
                     "fieldwork_stage_stop"):
            self.assertEqual(c.route(name),"stage_compose_helper")
        for name in ("fieldwork_sandbox_command",
                     "fieldwork_sandbox_runtime_test"):
            self.assertEqual(c.route(name),"sandbox_helper")
        for name in ("fieldwork_mcp_docker_inventory",
                     "fieldwork_stage_logs","fieldwork_compose_ps"):
            self.assertEqual(c.route(name),"docker_read_proxy")

    def test_inert_artifact_and_source_work_not_promoted_to_docker(self):
        for name in ("fieldwork_artifact_begin","fieldwork_artifact_append",
                     "fieldwork_artifact_finalize","fieldwork_artifact_qualify",
                     "fieldwork_artifact_retire","fieldwork_stage_patch",
                     "fieldwork_sandbox_apply","fieldwork_stage_prepare",
                     "fieldwork_mcp_source_review",
                     "fieldwork_stage_credentials"):
            self.assertEqual(c.route(name),"no_docker")

    def test_unknown_tool_and_arbitrary_shell_cannot_be_admitted(self):
        for name in ("docker","fieldwork_shell","fieldwork_host_exec",
                     "fieldwork_stage_delete","fieldwork_production_deploy",
                     "",0,True,None):
            with self.subTest(name=name),self.assertRaises(c.CompatibilityDenied):
                c.route(name)

    def test_live_catalog_same_names_any_order_accepted_as_inventory_only(self):
        names=list(reversed(c.EXPECTED))
        out=c.verify_live_inventory(names,c.SOURCE_PIN)
        self.assertEqual(out["tool_count"],36)
        self.assertEqual(out["status"],"M15J_EXACT_LEGACY_INVENTORY_PASS")
        self.assertFalse(out["cutover_authorized"])
        self.assertFalse(out["privilege_separation_verified"])

    def test_missing_extra_duplicate_catalog_denied(self):
        for names in (list(c.EXPECTED[:-1]),
                      list(c.EXPECTED)+["fieldwork_root_shell"],
                      list(c.EXPECTED[:-1])+[c.EXPECTED[0]],
                      ["fieldwork_status"]*36, "fieldwork_status",None):
            with self.subTest(names=str(names)[:40]),self.assertRaisesRegex(
                    c.CompatibilityDenied,"M15J_LIVE_TOOL_CATALOG_DRIFT"):
                c.verify_live_inventory(names,c.SOURCE_PIN)

    def test_source_pin_missing_changed_invalid_is_fail_closed(self):
        for variants in (
            {k:v for k,v in c.SOURCE_PIN.items() if k!="stage_manager.py"},
            {**c.SOURCE_PIN,"runtime_runner.py":"0"*64},
            {**c.SOURCE_PIN,"stage_manager.py":"g"*64},
            {**c.SOURCE_PIN,"extra.py":"0"*64},
            None,
        ):
            with self.subTest(pins=str(variants)[:30]),self.assertRaisesRegex(
                    c.CompatibilityDenied,"M15J_LIVE_SOURCE_BYTES_CHANGED"):
                c.verify_live_inventory(list(c.EXPECTED),variants)

    def invoke(self,receipts,**overrides):
        params=dict(live_names=list(c.EXPECTED),
                    live_hashes=dict(c.SOURCE_PIN),
                    route_receipts=receipts,
                    remote_mcp_without_rootful_docker=True,
                    independent_host_audit=True,
                    operator_authentication=True)
        params.update(overrides)
        return c.evaluate_shadow_cutover(**params)

    def test_missing_receipt_and_duplicate_denied(self):
        receipt=evidence()
        for bad in ([],receipt[:-1],receipt+[receipt[0]],
                    receipt[:-1]+[receipt[0]]):
            with self.subTest(total=len(bad)),self.assertRaises(
                    c.CompatibilityDenied):
                self.invoke(bad)

    def test_wrong_route_or_outcome_denied(self):
        for key,value in (("route","no_docker"),("outcome","FAIL"),
                          ("outcome","BLOCKED"),
                          ("evidence_sha256","g"*64),
                          ("evidence_sha256","0"*63)):
            rows=evidence()
            target=next(i for i,r in enumerate(rows)
                        if r["tool"]=="fieldwork_stage_start")
            rows[target][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(
                    c.CompatibilityDenied):
                self.invoke(rows)

    def test_extra_fields_untrusted_parameters_denied(self):
        rows=evidence()
        for injected in ("shell","docker_socket","host_path",
                         "approval_hmac","container_id"):
            bad=copy.deepcopy(rows)
            bad[0][injected]="untrusted"
            with self.subTest(key=injected),self.assertRaises(
                    c.CompatibilityDenied):
                self.invoke(bad)

    def test_no_bypass_if_independent_rootful_or_consent_undone(self):
        for key in ("remote_mcp_without_rootful_docker",
                    "independent_host_audit","operator_authentication"):
            with self.subTest(key=key),self.assertRaisesRegex(
                    c.CompatibilityDenied,
                    "M15J_PRIVILEGE_AND_CONSENT_NOT_ATTESTED"):
                self.invoke(evidence(),**{key:False})

    def test_even_full_receipt_contract_never_approves_real_cutover(self):
        result=self.invoke(evidence())
        self.assertEqual(result["shadow_receipts_present"],36)
        self.assertFalse(result["cutover_authorized"])
        self.assertFalse(result["docker_group_revoke_authorized"])
        self.assertFalse(result["m15e_activation_authorized"])
        self.assertFalse(result["actual_host_privilege_verified_by_this_module"])

    def test_no_docker_subprocess_or_system_mutation(self):
        src=inspect.getsource(c)
        for forbidden in ("import subprocess","import socket",
                          "docker run","docker compose up",
                          "os.system(","os.chmod(","os.chown(",
                          "shell=True","subprocess.run(",
                          "systemctl enable","sudo "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,src)


if __name__=="__main__":
    unittest.main()
