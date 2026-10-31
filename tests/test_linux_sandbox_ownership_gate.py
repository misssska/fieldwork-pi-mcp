"""M14F sandbox ownership evidence tests; no Docker mutation."""
from __future__ import annotations
import copy
import unittest
from updater import linux_sandbox_ownership_gate as g

NOW = 1793465000
RUN = "a" * 32
PROPOSAL = "b" * 32
SECRET = b"independent-local-helper-creation-receipt-key-material-123"


def manifest(with_db=True):
    resources = []
    for i, template in enumerate(g.expected_resources(RUN,with_db=with_db)):
        resources.append({
            **template,
            "id": f"{i+1:x}"*64,
            "labels": {
                "org.fieldwork.sandbox.run": RUN,
                "org.fieldwork.sandbox.proposal": PROPOSAL,
                "org.fieldwork.sandbox.role": template["role"],
            },
        })
    return {
        "protocol": 1, "host_id": g.HOST,
        "run_id": RUN, "proposal_id": PROPOSAL,
        "with_db": with_db,
        "issued_at": NOW - 10, "expires_at": NOW + 60,
        "resources": resources,
    }


def observations(m):
    return [{
        **row,
        "state": "existing" if row["kind"] == "network" else "running",
        "network_container_ids": [],
    } for row in m["resources"]]


class SandboxOwnershipTests(unittest.TestCase):
    def verify(self,m=None, *, observed=None, now=NOW):
        m=manifest() if m is None else m
        sig=g.sign_creation(m,local_secret=SECRET,
                            local_helper_created=True,now=NOW)
        return g.cleanup_preflight(
            sig,observations=observations(m) if observed is None else observed,
            local_secret=SECRET,now=now)

    def test_good_owned_resources_only_yield_preflight_not_delete(self):
        result=self.verify()
        self.assertEqual(result["status"],"SANDBOX_OWNER_PROVENANCE_PREFLIGHT_PASS")
        self.assertTrue(result["creation_receipt_verified"])
        self.assertFalse(result["cleanup_authorized"])
        self.assertFalse(result["container_removal_authorized"])
        self.assertFalse(result["historical_cleanup_receipt_resolved"])
        self.assertFalse(result["docker_command_executed"])
        self.assertFalse(result["production_modified"])

    def test_no_database_mode_has_only_test_container(self):
        m=manifest(with_db=False)
        self.assertEqual(len(m["resources"]),1)
        self.assertEqual(m["resources"][0]["role"],"test")
        self.assertEqual(self.verify(m)["resource_count"],1)

    def test_network_cannot_have_foreign_attached_containers(self):
        m=manifest()
        obs=observations(m)
        obs[0]["network_container_ids"]=[m["resources"][1]["id"],m["resources"][2]["id"]]
        self.assertEqual(self.verify(m,observed=obs)["resource_count"],3)
        obs[0]["network_container_ids"].append("9"*64)
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_FOREIGN_NETWORK_ENDPOINT_DENIED"):
            self.verify(m,observed=obs)

    def test_malicious_name_project_id_or_label_tamper_denied(self):
        changes=[
            ("name","fieldwork-api-1"),
            ("name","homeassistant"),
            ("kind","volume"),
            ("role","production"),
            ("id","f"*64),
            ("labels",{"org.fieldwork.sandbox.run":RUN,
                       "org.fieldwork.sandbox.proposal":PROPOSAL,
                       "org.fieldwork.sandbox.role":"production"}),
        ]
        for key,value in changes:
            m=manifest()
            m["resources"][-1][key]=value
            with self.subTest(change=(key,value)),self.assertRaises(g.SandboxDenied):
                self.verify(m)

    def test_independent_docker_observation_must_match_signed_receipt(self):
        m=manifest()
        obs=observations(m)
        obs[1]["id"]="f"*64
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_OBSERVED_OWNER_MISMATCH"):
            self.verify(m,observed=obs)

    def test_unknown_endpoints_in_container_are_denied(self):
        m=manifest()
        obs=observations(m)
        obs[2]["network_container_ids"]=["9"*64]
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_UNEXPECTED_CONTAINER_ENDPOINTS"):
            self.verify(m,observed=obs)

    def test_local_creation_only_not_remote_self_approval(self):
        m=manifest()
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_LOCAL_CREATION_REQUIRED"):
            g.sign_creation(m,local_secret=SECRET,
                            local_helper_created=False,now=NOW)
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_SIGNING_SECRET_DENIED"):
            g.sign_creation(m,local_secret=b"too-short",
                            local_helper_created=True,now=NOW)

    def test_mac_drift_and_cross_host_receipt_denied(self):
        m=manifest()
        sig=g.sign_creation(m,local_secret=SECRET,
                            local_helper_created=True,now=NOW)
        sig["mac"]="0"*64
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_ATTESTATION_MAC_DENIED"):
            g.cleanup_preflight(sig,observations=observations(m),
                                local_secret=SECRET,now=NOW)
        m=manifest()
        m["host_id"]="orange-pi"
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_MANIFEST_HOST_OR_PROPOSAL_DENIED"):
            self.verify(m)

    def test_unauthorized_extra_fields_and_expiry_denied(self):
        m=manifest()
        m["arbitrary_docker_command"]="docker rm -f fieldwork-api-1"
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_MANIFEST_SCHEMA_DENIED"):
            self.verify(m)
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_MANIFEST_TIME_DENIED"):
            self.verify(now=NOW+61)

    def test_missing_resource_or_duplicate_full_id_denied(self):
        m=manifest()
        m["resources"].pop()
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_MANIFEST_RESOURCES_DENIED"):
            self.verify(m)
        m=manifest()
        m["resources"][2]["id"]=m["resources"][1]["id"]
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_RESOURCE_IDENTITY_DENIED"):
            self.verify(m)

    def test_invalid_observation_and_daemon_error_fail_closed(self):
        m=manifest()
        obs=observations(m)
        obs[0]["state"]="inspect-error"
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_OBSERVED_STATE_DENIED"):
            self.verify(m,observed=obs)
        obs=observations(m)
        obs[0]["network_container_ids"]=["9"*64,"9"*64]
        with self.assertRaisesRegex(g.SandboxDenied,"SANDBOX_NETWORK_ENDPOINT_SCHEMA_DENIED"):
            self.verify(m,observed=obs)

    def test_no_docker_or_cleanup_implementation_present(self):
        import inspect
        src=inspect.getsource(g)
        for bad in ("import subprocess", "os.system(", "subprocess.run(",
                    "docker rm -f", "docker network rm", "docker stop",
                    "shell=True", ".unlink(", ".write_bytes("):
            self.assertNotIn(bad,src)


if __name__=="__main__":
    unittest.main()
