"""Offline, negative-first tests of the fixed-origin proposal; never deploys."""
import unittest
from updater import stable_dev_gateway as g


def receipt(project='fieldwork-parity-m5', port=18085, db='dev-db-v1', auth='dev-auth-v1'):
    return {
        'project': project,
        'bind_ip': '192.168.22.13',
        'port': port,
        'artifact_sha256': 'e' * 64,
        'test_gate': 'FULL_SUITE_PASS',
        'database_identity': db,
        'auth_identity': auth,
    }


class GatewayTests(unittest.TestCase):
    def test_stable_port_and_exact_host(self):
        plan = g.plan_switch(receipt())
        self.assertEqual(plan['stable_origin'], 'http://192.168.22.13:18090')
        self.assertEqual(plan['gateway_bind'], '192.168.22.13:18090:8080')
        self.assertIn('proxy_pass http://192.168.22.13:18085;', plan['nginx_config'])
        self.assertFalse(plan['activated'])
        self.assertFalse(plan['production_modified'])

    def test_new_release_keeps_origin(self):
        plan = g.plan_switch(receipt('fieldwork-parity-m6', 18086), receipt())
        self.assertEqual(plan['stable_origin'], g.GATEWAY_URL)
        self.assertTrue(plan['same_auth_identity'])
        self.assertTrue(plan['same_database_identity'])
        self.assertFalse(plan['authentication_continuity_proven'])
        self.assertIn('actual_candidate_health_pass', plan['requires'])

    def test_different_db_and_auth_block_session_claim(self):
        plan = g.plan_switch(receipt('fieldwork-parity-m6', 18086, 'another-db', 'new-key'), receipt())
        self.assertFalse(plan['same_database_identity'])
        self.assertFalse(plan['same_auth_identity'])
        self.assertIn('jwt_auth_identity_mismatch_must_be_resolved', plan['requires'])
        self.assertIn('dev_database_identity_mismatch_must_be_resolved', plan['requires'])

    def test_external_or_loopback_proxy_denied(self):
        for host in ('localhost', '127.0.0.1', '10.0.0.1', 'evil.test'):
            with self.subTest(host=host), self.assertRaisesRegex(g.GatewayDenied, 'TARGET_HOST_DENIED'):
                g.plan_switch({**receipt(), 'bind_ip': host})

    def test_production_and_gateway_and_stage_ports_denied(self):
        for port in (8080, 18090, 18081, 80, 443, 19000, -1, '18085', True):
            with self.subTest(port=port), self.assertRaisesRegex(g.GatewayDenied, 'TARGET_PORT_DENIED'):
                g.plan_switch({**receipt(), 'port': port})

    def test_unapproved_or_unknown_release_denied(self):
        for project in ('fieldwork', 'fieldwork-stage', 'fieldwork-parity-m0', 'not-ours', 'fieldwork-parity-m2\nserver{}'):
            with self.subTest(project=project), self.assertRaisesRegex(g.GatewayDenied, 'PROJECT_NOT_CANARY'):
                g.plan_switch(receipt(project=project))
        with self.assertRaisesRegex(g.GatewayDenied, 'FULL_SUITE_REQUIRED'):
            g.plan_switch({**receipt(), 'test_gate': 'PENDING'})

    def test_schema_injection_denied(self):
        with self.assertRaisesRegex(g.GatewayDenied, 'RECEIPT_SCHEMA_DENIED'):
            g.plan_switch({**receipt(), 'proxy_pass': 'http://evil'})
        with self.assertRaisesRegex(g.GatewayDenied, 'RELEASE_HASH_INVALID'):
            g.plan_switch({**receipt(), 'artifact_sha256': 'x'})

    def test_same_release_denied(self):
        with self.assertRaisesRegex(g.GatewayDenied, 'ALREADY_ACTIVE_RELEASE'):
            g.plan_switch(receipt(), receipt())

    def test_requires_real_health_and_local_activation(self):
        plan = g.plan_switch(receipt())
        self.assertEqual(plan['status'], 'REVIEW_ONLY_NOT_DEPLOYED')
        self.assertIn('actual_candidate_health_pass', plan['requires'])
        self.assertIn('local_activation_approved', plan['requires'])
        self.assertIn('durable_backup_and_rollback', plan['requires'])


if __name__ == '__main__':
    unittest.main()
