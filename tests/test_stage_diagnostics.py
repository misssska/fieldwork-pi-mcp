import json
import unittest
from updater.stage_diagnostics import classify_compose_ps as check

class StageDiagnosticsTests(unittest.TestCase):
    def test_empty_success_is_not_running(self):
        self.assertEqual(check(0, '')['status'], 'STAGE_NO_CONTAINERS')
    def test_command_failure(self):
        self.assertEqual(check(1, '')['status'], 'STAGE_DOCKER_PS_FAILED')
    def test_all_running_not_health_pass(self):
        data=[{'Service': x, 'State': 'running'} for x in ('api','db','nginx')]
        self.assertEqual(check(0, json.dumps(data))['status'], 'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED')
    def test_missing_service(self):
        self.assertEqual(check(0, json.dumps([{'Service':'db','State':'running'}]))['status'], 'STAGE_SERVICES_MISSING')
    def test_exited(self):
        self.assertEqual(check(0, json.dumps([{'Service':'db','State':'exited'}]))['status'], 'STAGE_CONTAINERS_NOT_RUNNING')
    def test_ndjson(self):
        data='\n'.join(json.dumps({'Service':x,'State':'running'}) for x in ('api','db','nginx'))
        self.assertEqual(check(0,data)['status'], 'STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED')
    def test_bad_json(self):
        self.assertEqual(check(0,'{bad')['status'],'STAGE_DOCKER_PS_UNPARSEABLE')
    def test_unexpected_service(self):
        self.assertEqual(check(0,json.dumps([{'Service':'production-api','State':'running'}]))['status'],'STAGE_DOCKER_PS_UNEXPECTED')
    def test_duplicate_service(self):
        self.assertEqual(check(0,json.dumps([{'Service':'db','State':'running'}]*2))['status'],'STAGE_DOCKER_PS_UNEXPECTED')
    def test_no_secrets_or_names_exposed(self):
        r=check(0,json.dumps([{'Service':'db','State':'running','Name':'secret'}]))
        self.assertNotIn('secret',str(r))

if __name__=='__main__': unittest.main()
