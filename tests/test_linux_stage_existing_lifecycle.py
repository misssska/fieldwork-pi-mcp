"""M14E stage-existing lifecycle policy + rollback, wholly offline fake Docker.

Full-id and compose labels checked before touching exactly 3 stage containers.
No production Pi or Docker called by this suite.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from updater import linux_stage_existing_lifecycle as m

NOW = 1793459000
SECRET = b"independently-secured-local-only-test-operator-key"


class FakeDocker:
    def __init__(self):
        self.rows = {
            service: {
                "service": service,
                "id": (f"{i:x}" * 64),
                "state": "running",
                "name": f"/fieldwork-stage-{service}-1",
                "project": "fieldwork-stage",
                "number": "1",
            } for i, service in enumerate(m.SERVICES, 10)
        }
        self.log = []
        self.fail_once = None
        self.reject_probe_for = None

    def lookup(self, identifier):
        for row in self.rows.values():
            if identifier in (row["id"], row["name"].lstrip("/")):
                return row
        raise m.StageDenied("FAKE_NOT_FOUND")

    def __call__(self, argv, *, timeout=15):
        self.log.append(tuple(argv))
        if argv[0:2] != [m.DOCKER, "container"]:
            raise AssertionError("Unknown Docker command")
        verb = argv[2]
        if verb == "inspect":
            row = self.lookup(argv[-1])
            if self.reject_probe_for == row["service"]:
                raise m.StageDenied("FAKE_PROBE_FAILURE")
            return "|".join([
                row["id"], row["name"], row["project"],
                row["service"], row["number"], row["state"]
            ])
        if verb not in ("start", "stop"):
            raise AssertionError("Only start or stop")
        row = self.lookup(argv[-1])
        row["state"] = "exited" if verb == "stop" else "running"
        if self.fail_once == row["service"]:
            self.fail_once = None
            # Simulate socket/client timeout AFTER a completed Docker action.
            raise m.StageDenied("FAKE_DOCKER_TIMEOUT_AFTER_MUTATION")
        return row["id"]


class StageLifecyclePolicyTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDocker()
        self.patch = patch.object(m, "_docker", side_effect=self.fake)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)

    def proposal(self, action="stop", nonce="1"*32):
        plan = m.plan_action(action, now=NOW)
        ticket = m.issue_local_ticket(
            plan, secret=SECRET,
            local_operator_present=True, now=NOW,
            nonce=nonce,
        )
        return plan, ticket

    def test_only_exact_service_names_and_container_labels(self):
        rows=m.snapshot()
        self.assertEqual([x["service"] for x in rows],list(m.SERVICES))
        self.assertEqual(len({x["id"] for x in rows}),3)
        self.assertTrue(all(x["state"]=="running" for x in rows))
        self.assertEqual(set(self.fake.rows),set(m.SERVICES))
        self.assertEqual([a[-1] for a in self.fake.log],
                         [f"fieldwork-stage-{s}-1" for s in m.SERVICES])

    def test_no_arbitrary_name_or_production_container_allowed(self):
        bad="fieldwork-api-1"
        with self.assertRaisesRegex(m.StageDenied,"STAGE_INSPECT_IDENTITY_DENIED"):
            m._parse_inspect(
                f"{'a'*64}|/{bad}|fieldwork|api|1|running", "api"
            )
        for raw in (
            f"{'a'*64}|/fieldwork-stage-api-1|fieldwork|api|1|running",
            f"{'a'*64}|/fieldwork-stage-api-1|fieldwork-stage|nginx|1|running",
            f"{'a'*64}|/fieldwork-stage-api-1|fieldwork-stage|api|2|running",
            f"{'a'*64}|/fieldwork-stage-api-1|fieldwork-stage|api|1|paused",
        ):
            with self.subTest(raw=raw),self.assertRaises(m.StageDenied):
                m._parse_inspect(raw,"api")

    def test_successful_approved_stop_and_start(self):
        plan,ticket=self.proposal()
        result=m.execute_approved(
            plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertEqual(result["status"],
                         "STAGE_APPROVED_EXISTING_CONTAINERS_CHANGED")
        self.assertEqual(result["changed_count"],3)
        self.assertFalse(result["volume_deleted"])
        self.assertFalse(result["production_modified"])
        self.assertEqual([x["state"] for x in m.snapshot()],
                         ["exited"]*3)
        mark=m.hashlib.sha256(m.DOMAIN+ticket["nonce"].encode()).hexdigest()
        self.assertEqual(json.loads((self.root/mark).read_text())["state"],
                         "COMMITTED")
        plan,ticket=self.proposal("start","2"*32)
        m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertEqual([x["state"] for x in m.snapshot()],
                         ["running"]*3)
        self.assertEqual(len([x for x in self.fake.log
                              if x[2] in ("start","stop")]),6)

    def test_replay_after_return_to_same_state_never_executes(self):
        plan,ticket=self.proposal()
        m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        for row in self.fake.rows.values():
            row["state"]="running"
        before=len([x for x in self.fake.log if x[2] in ("start","stop")])
        with self.assertRaisesRegex(m.StageDenied,"STAGE_RECEIPT_REPLAY_DENIED"):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertEqual(len([x for x in self.fake.log
                              if x[2] in ("start","stop")]),before)

    def test_no_operator_approval_or_invalid_hmac(self):
        plan=m.plan_action("stop",now=NOW)
        with self.assertRaisesRegex(m.StageDenied,"STAGE_LOCAL_OPERATOR_REQUIRED"):
            m.issue_local_ticket(plan,secret=SECRET,
                                 local_operator_present=False,now=NOW,nonce="1"*32)
        ticket=m.issue_local_ticket(plan,secret=SECRET,
                                    local_operator_present=True,now=NOW,nonce="1"*32)
        ticket["mac"]="0"*64
        with self.assertRaisesRegex(m.StageDenied,"STAGE_TICKET_MAC_DENIED"):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertFalse([x for x in self.fake.log if x[2] in ("start","stop")])

    def test_tampered_cross_host_or_production_project_denied(self):
        plan,ticket=self.proposal()
        for field,value in (("host_id","orange-pi"),("project","fieldwork"),
                            ("action","delete"),("expires_at",NOW-1)):
            modified={**plan,field:value}
            with self.subTest(field=field),self.assertRaises(m.StageDenied):
                m.execute_approved(
                    modified,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertFalse([x for x in self.fake.log if x[2] in ("start","stop")])

    def test_full_id_drift_blocks_all_writes(self):
        plan,ticket=self.proposal()
        self.fake.rows["db"]["id"]="f"*64
        with self.assertRaisesRegex(m.StageDenied,"STAGE_CONTAINER_CHANGED_AFTER_REVIEW"):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertFalse([x for x in self.fake.log if x[2] in ("start","stop")])

    def test_wrong_label_blocks_before_any_write(self):
        plan,ticket=self.proposal()
        self.fake.rows["db"]["project"]="fieldwork"
        with self.assertRaises(m.StageDenied):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertFalse([x for x in self.fake.log if x[2] in ("start","stop")])

    def test_rollback_after_docker_timeout_after_mutation(self):
        plan,ticket=self.proposal()
        self.fake.fail_once="db"
        with self.assertRaisesRegex(
                m.StageDenied,"STAGE_EXECUTION_FAILED_CHECK_LOCAL_STATE"):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.assertEqual([x["state"] for x in m.snapshot()],["running"]*3)
        mark=m.hashlib.sha256(m.DOMAIN+ticket["nonce"].encode()).hexdigest()
        self.assertEqual(json.loads((self.root/mark).read_text())["state"],
                         "ROLLED_BACK")

    def test_uncertain_rollback_blocks_next_operation(self):
        plan,ticket=self.proposal()
        self.fake.fail_once="db"
        # Fail all DB subsequent inspections after initial action attempt
        # by converting the failure into a persistent probe refusal.
        original=self.fake.__call__
        def poisoned(argv,*,timeout=15):
            try:
                return original(argv,timeout=timeout)
            except m.StageDenied as e:
                if "TIMEOUT" in str(e):
                    self.fake.reject_probe_for="db"
                raise
        with patch.object(m,"_docker",side_effect=poisoned):
            with self.assertRaisesRegex(m.StageDenied,"STAGE_EXECUTION_FAILED_CHECK_LOCAL_STATE"):
                m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        mark=m.hashlib.sha256(m.DOMAIN+ticket["nonce"].encode()).hexdigest()
        self.assertEqual(json.loads((self.root/mark).read_text())["state"],
                         "ROLLBACK_UNCERTAIN")
        self.fake.reject_probe_for=None
        # Even a distinct nonce and matching live state is blocked.
        self.fake.rows["db"]["state"]="running"
        next_plan,next_ticket=self.proposal("stop","2"*32)
        with self.assertRaisesRegex(m.StageDenied,"STAGE_PENDING_MANUAL_RECOVERY"):
            m.execute_approved(
                next_plan,next_ticket,secret=SECRET,state=self.root,now=NOW)

    def test_prepared_crash_journal_blocks_new_approval(self):
        marker="f"*64
        (self.root/marker).write_bytes(m.canon({
            "plan":"0"*64,"action":"stop","state":"APPLYING"
        }))
        (self.root/marker).chmod(0o600)
        plan,ticket=self.proposal()
        with self.assertRaisesRegex(m.StageDenied,"STAGE_PENDING_MANUAL_RECOVERY"):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)

    def test_bad_state_permissions_and_root_execution_denied(self):
        plan,ticket=self.proposal()
        self.root.chmod(0o755)
        with self.assertRaisesRegex(m.StageDenied,"STAGE_STATE_PERMISSIONS_DENIED"):
            m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)
        self.root.chmod(0o700)
        with patch.object(m.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(m.StageDenied,"STAGE_ROOT_EXECUTION_DENIED"):
                m.execute_approved(plan,ticket,secret=SECRET,state=self.root,now=NOW)

    def test_no_docker_run_rm_compose_or_any_command_in_fixed_builder(self):
        for raw in (
            [m.DOCKER,"container","rm","a"*64],
            [m.DOCKER,"container","stop","fieldwork-api-1"],
            [m.DOCKER,"container","inspect","--format",
             m.DETAIL_FMT,"fieldwork-api-1"],
            [m.DOCKER,"container","run","--privileged"],
        ):
            with self.subTest(raw=raw),self.assertRaises(m.StageDenied):
                m._docker(raw)
        import inspect
        src=inspect.getsource(m)
        self.assertNotIn("shell=True",src)
        self.assertNotIn("docker compose",src)
        self.assertNotIn("volume rm",src)


if __name__ == "__main__":
    unittest.main()
