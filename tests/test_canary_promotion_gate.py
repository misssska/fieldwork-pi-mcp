"""Proof-of-policy tests, not service-level verification or a deployment."""
import unittest
from updater import canary_promotion_gate as g


def receipt(project, port, db='devdb', auth='devauth'):
    return {
        'project': project,
        'bind_ip': '192.168.22.13',
        'port': port,
        'artifact_sha256': 'a' * 64,
        'test_gate': 'FULL_SUITE_PASS',
        'database_identity': db,
        'auth_identity': auth,
    }


CURRENT = receipt('fieldwork-parity-m5', 18085)
CANDIDATE = receipt('fieldwork-parity-m6', 18086)


def observed():
    return {
        'project': 'fieldwork-parity-m6',
        'host': '192.168.22.13',
        'port': 18086,
        'health_http_status': 200,
        'health_json_status': 'ok',
        'api_smoke': True,
        'authorization_smoke': True,
        'migration_gate': True,
        'tests_verified': True,
        'gateway_port_exclusive': True,
        'previous_route_backed_up': True,
        'network_scope': 'LAN_ONLY',
    }


class PromotionTests(unittest.TestCase):
    def test_full_preflight_review_not_deploy(self):
        result = g.review(CANDIDATE, CURRENT, observed())
        self.assertEqual(result['status'], 'PRE_PROMOTION_REVIEW_PASS_NOT_APPLIED')
        for name in ('authentication_continuity_proven', 'promotion_authorized',
                     'route_modified', 'production_modified'):
            self.assertFalse(result[name])

    def test_database_identity_change_denied(self):
        with self.assertRaisesRegex(g.PromotionDenied, 'DATABASE_IDENTITY_DRIFT'):
            g.review(receipt('fieldwork-parity-m6', 18086, db='newdb'), CURRENT, observed())

    def test_auth_identity_change_denied(self):
        with self.assertRaisesRegex(g.PromotionDenied, 'JWT_IDENTITY_DRIFT'):
            g.review(receipt('fieldwork-parity-m6', 18086, auth='newjwt'), CURRENT, observed())

    def test_unmeasured_release_identity_denied(self):
        for key, change in [('project', 'fieldwork-parity-m8'), ('host', '8.8.8.8'),
                            ('port', 8080), ('port', True)]:
            with self.subTest(key=key), self.assertRaises(g.PromotionDenied):
                g.review(CANDIDATE, CURRENT, {**observed(), key: change})

    def test_health_and_auth_checks_required(self):
        for key in ('api_smoke', 'authorization_smoke', 'migration_gate',
                    'tests_verified', 'gateway_port_exclusive',
                    'previous_route_backed_up'):
            with self.subTest(key=key), self.assertRaisesRegex(g.PromotionDenied, 'GATE_NOT_PASSED'):
                g.review(CANDIDATE, CURRENT, {**observed(), key: False})
        for value in (201, True, 500):
            with self.assertRaisesRegex(g.PromotionDenied, 'HEALTH_NOT_VERIFIED'):
                g.review(CANDIDATE, CURRENT, {**observed(), 'health_http_status': value})

    def test_public_gateway_denied(self):
        with self.assertRaisesRegex(g.PromotionDenied, 'PUBLIC_GATEWAY_DENIED'):
            g.review(CANDIDATE, CURRENT, {**observed(), 'network_scope': 'PUBLIC'})

    def test_schema_fail_closed(self):
        for change in ({'shell': 'sh'}, {'api_smoke': 'true'}, {'api_smoke': 1}):
            with self.subTest(change=change), self.assertRaises(g.PromotionDenied):
                g.review(CANDIDATE, CURRENT, {**observed(), **change})

    def test_unapproved_receipt_denied(self):
        with self.assertRaisesRegex(g.PromotionDenied, 'RELEASE_RECEIPT_DENIED'):
            g.review({**CANDIDATE, 'test_gate': 'PENDING'}, CURRENT, observed())


if __name__ == '__main__':
    unittest.main()
