"""Pure sandbox test DB environment adapter regression tests."""
import unittest

from updater.sandbox_db_env import build_isolated_test_env, TestEnvironmentDenied


class TestDbEnvTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "FIELDWORK_TESTING": "1",
            "DATABASE_URL": "postgresql://user:opaque@test-db:5432/fieldwork_test",
            "TEST_DATABASE_URL": "postgresql://user:opaque@test-db:5432/fieldwork_test",
            "UNRELATED": "preserve",
        }

    def build(self):
        return build_isolated_test_env(self.original)

    def test_safe_env_drops_generic_database_url(self):
        env = self.build()
        self.assertNotIn("DATABASE_URL", env)
        self.assertEqual(env["FIELDWORK_TEST_DATABASE_URL"],
                         self.original["TEST_DATABASE_URL"])
        self.assertEqual(env["UNRELATED"], "preserve")

    def test_never_mutates_original(self):
        self.build()
        self.assertIn("DATABASE_URL", self.original)
        self.assertNotIn("FIELDWORK_TEST_DATABASE_URL", self.original)

    def test_test_mode_required(self):
        self.original["FIELDWORK_TESTING"] = "0"
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_MODE_REQUIRED"):
            self.build()

    def test_missing_test_url(self):
        del self.original["TEST_DATABASE_URL"]
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_URL_REQUIRED"):
            self.build()

    def test_production_host_denied(self):
        self.original["TEST_DATABASE_URL"] = "postgresql://u:p@prod-db/fieldwork_test"
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_DATABASE_TARGET_DENIED"):
            self.build()

    def test_production_database_denied(self):
        self.original["TEST_DATABASE_URL"] = "postgresql://u:p@test-db/fieldwork"
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_DATABASE_TARGET_DENIED"):
            self.build()

    def test_wrong_port_denied(self):
        self.original["TEST_DATABASE_URL"] = "postgresql://u:p@test-db:15432/fieldwork_test"
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_DATABASE_TARGET_DENIED"):
            self.build()

    def test_query_override_denied(self):
        self.original["TEST_DATABASE_URL"] = (
            "postgresql://u:p@test-db/fieldwork_test?application_name=unexpected")
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_DATABASE_TARGET_DENIED"):
            self.build()

    def test_non_postgres_driver_denied(self):
        self.original["TEST_DATABASE_URL"] = "sqlite:///fieldwork_test"
        with self.assertRaisesRegex(TestEnvironmentDenied, "TEST_DRIVER_DENIED"):
            self.build()

    def test_encoded_database_name_allowed(self):
        self.original["TEST_DATABASE_URL"] = "postgresql://u:p@test-db/fieldwork%5Ftest"
        self.assertEqual(self.build()["FIELDWORK_TEST_DATABASE_URL"],
                         self.original["TEST_DATABASE_URL"])

    def test_no_url_leak_in_error(self):
        self.original["TEST_DATABASE_URL"] = "postgresql://u:topsecret@prod-db/fieldwork"
        with self.assertRaises(TestEnvironmentDenied) as err:
            self.build()
        self.assertNotIn("topsecret", str(err.exception))

    def test_psycopg_driver_allowed(self):
        self.original["TEST_DATABASE_URL"] = (
            "postgresql+psycopg://u:p@test-db:5432/fieldwork_test")
        self.assertEqual(self.build()["FIELDWORK_TEST_DATABASE_URL"],
                         self.original["TEST_DATABASE_URL"])


if __name__ == "__main__":
    unittest.main()
