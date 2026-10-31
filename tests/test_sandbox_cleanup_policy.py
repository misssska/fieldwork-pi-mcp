"""M11 cleanup receipt interpretation: negative-first pure policy regression."""
import unittest

from updater.sandbox_cleanup_policy import (
    decide_container_absence as decide, CleanupDecisionDenied,
)


def check(observations, code=0, *, timeout=False, attempted=True):
    return decide(
        remove_attempted=attempted,
        remove_exit_code=code,
        observations=observations,
        docker_timeout=timeout,
    )


class CleanupVerificationTests(unittest.TestCase):
    def test_successful_rm_without_inventory_is_not_enough(self):
        r = check([], code=0)
        self.assertEqual(r["status"], "CLEANUP_VERIFICATION_INCOMPLETE")
        self.assertFalse(r["current_container_absence_verified"])

    def test_nonzero_rm_and_nonzero_inspect_are_never_proof(self):
        r = check(["QUERY_ERROR"], code=1)
        self.assertFalse(r["current_container_absence_verified"])
        self.assertTrue(r["docker_probe_error_seen"])

    def test_rm_timeout_then_failed_docker_query_stays_blocked(self):
        r = check(["QUERY_ERROR", "ABSENT", "ABSENT"], code=None,
                  timeout=True)
        self.assertFalse(r["current_container_absence_verified"])
        self.assertTrue(r["docker_run_timed_out"])
        self.assertFalse(r["historical_cleanup_receipt_resolved"])

    def test_only_one_absence_not_sufficient(self):
        self.assertFalse(check(["ABSENT"], code=1)[
            "current_container_absence_verified"])

    def test_late_present_not_sufficient(self):
        r = check(["ABSENT", "PRESENT"], code=1)
        self.assertFalse(r["current_container_absence_verified"])
        self.assertTrue(r["exact_name_present_seen"])

    def test_two_confirmed_absences_verify_only_current_state(self):
        r = check(["ABSENT", "ABSENT"], code=0)
        self.assertTrue(r["current_container_absence_verified"])
        self.assertEqual(r["status"], "CURRENT_CONTAINER_ABSENCE_VERIFIED")
        self.assertFalse(r["historical_cleanup_receipt_resolved"])
        self.assertFalse(r["sandbox_test_retry_authorized"])
        self.assertFalse(r["container_removal_authorized"])

    def test_rm_failure_with_two_confirmed_absences_is_not_historical_pass(self):
        r = check(("PRESENT", "ABSENT", "ABSENT"), code=1,
                  timeout=True)
        self.assertTrue(r["current_container_absence_verified"])
        self.assertFalse(r["remove_success_observed"])
        self.assertFalse(r["historical_cleanup_receipt_resolved"])

    def test_missing_rm_attempt_not_verified_even_with_two_absences(self):
        r = check(["ABSENT", "ABSENT"], code=None, attempted=False)
        self.assertFalse(r["current_container_absence_verified"])

    def test_no_rm_attempt_cannot_claim_rc(self):
        with self.assertRaisesRegex(
                CleanupDecisionDenied,
                "CLEANUP_REMOVE_EVIDENCE_CONTRADICTORY"):
            check(["ABSENT", "ABSENT"], code=0, attempted=False)

    def test_probe_error_anywhere_fails_closed(self):
        r = check(["ABSENT", "QUERY_ERROR", "ABSENT", "ABSENT"])
        self.assertFalse(r["current_container_absence_verified"])

    def test_empty_then_present_then_absent_is_not_twice(self):
        r = check(["ABSENT", "PRESENT", "ABSENT"])
        self.assertFalse(r["current_container_absence_verified"])

    def test_every_decision_denies_deploy_and_runtime_retry(self):
        scenarios = [
            ([], None), (["QUERY_ERROR"], 0), (["PRESENT"], 1),
            (["ABSENT", "ABSENT"], 0),
        ]
        for probes, code in scenarios:
            with self.subTest(probes=probes):
                r = check(probes, code=code)
                self.assertFalse(r["historical_cleanup_receipt_resolved"])
                self.assertFalse(r["sandbox_test_retry_authorized"])
                self.assertFalse(r["container_removal_authorized"])
                self.assertFalse(r["mcp_activation_authorized"])
                self.assertFalse(r["production_modified"])

    def test_invalid_observations_denied(self):
        for bad in (None, "ABSENT", {}, ["UNKNOWN"], [0], [True],
                    ["ABSENT"] * 9):
            with self.subTest(bad=bad), self.assertRaises(
                    CleanupDecisionDenied):
                check(bad)

    def test_invalid_return_codes_denied(self):
        for bad in (True, False, -1, 256, "0", 0.0):
            with self.subTest(bad=bad), self.assertRaises(
                    CleanupDecisionDenied):
                check([], code=bad)

    def test_invalid_booleans_denied(self):
        for bad in (0, 1, "true", None):
            with self.subTest(bad=bad):
                with self.assertRaises(CleanupDecisionDenied):
                    decide(remove_attempted=bad, remove_exit_code=0,
                           observations=[], docker_timeout=False)
                with self.assertRaises(CleanupDecisionDenied):
                    decide(remove_attempted=True, remove_exit_code=0,
                           observations=[], docker_timeout=bad)

    def test_never_calls_docker_or_other_process(self):
        import inspect
        import updater.sandbox_cleanup_policy as sut
        src = inspect.getsource(sut)
        self.assertNotIn("subprocess", src)
        self.assertNotIn("import docker", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("eval(", src)
        self.assertNotIn("exec(", src)


if __name__ == "__main__":
    unittest.main()
