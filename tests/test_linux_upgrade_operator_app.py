"""M14C operator service local setup/readiness, not a Pi deployment."""
from pathlib import Path
from unittest.mock import patch
import json
import os
import tempfile
import unittest
from updater import linux_upgrade_gate as gate
from updater import linux_upgrade_operator_app as app

NOW=1793469000
HMAC=b"local-secret-from-operator-only-key-material-32bytes"
TOKEN=b"separate-operator-browser-token-32bytes-more"
SOURCE="a"*64
TARGET="b"*64


class OperatorServiceConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.root.chmod(0o700)
        (self.root/"approved").mkdir(mode=0o700)
        self.current_euid=os.geteuid()
        self.config={
            "host_id":"fieldwork-pi",
            "remote_mcp_euid":self.current_euid + 1,
            "allowed_modules":["fieldwork_mcp.py"],
            "locked_modules":[],
            "active_hashes":{"fieldwork_mcp.py":SOURCE},
            "listen_port":8767,
        }
        self.request={
            "protocol":1,
            "host_id":"fieldwork-pi",
            "commit_sha":"c"*40,
            "issued_at":NOW-1,
            "expires_at":NOW+100,
            "files":[{"name":"fieldwork_mcp.py",
                      "action":"replace",
                      "old_sha256":SOURCE,"new_sha256":TARGET}],
        }
        self.write("config.json",gate.canon(self.config))
        self.write("request.json",gate.canon(self.request))
        self.write("approval_hmac.key",HMAC)
        self.write("operator_token.key",TOKEN)

    def write(self,name,value):
        p=self.root/name
        p.write_bytes(value)
        p.chmod(0o600)
        return p

    def session(self):
        return app.load_review_session(root=self.root,now=NOW)

    def test_local_setup_produces_real_plan_with_private_credentials(self):
        s=self.session()
        self.assertEqual(s.plan.host_id,"fieldwork-pi")
        self.assertEqual(len(s.plan.files),1)
        self.assertEqual(s.operator_token,TOKEN)
        self.assertEqual(s.local_secret,HMAC)
        self.assertNotEqual(TOKEN,HMAC)
        self.assertEqual(s.state,"PENDING")
        self.assertEqual(len(list((self.root/"approved").iterdir())),0)

    def test_remote_mcp_same_user_must_not_host_operator(self):
        self.config["remote_mcp_euid"]=self.current_euid
        self.write("config.json",gate.canon(self.config))
        with self.assertRaisesRegex(app.OperatorServiceDenied,
                                    "OPERATOR_NOT_SEPARATE_UID"):
            self.session()

    def test_fake_docker_root_operator_forbidden(self):
        with patch.object(app.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(app.OperatorServiceDenied,
                                        "OPERATOR_ROOT_DENIED"):
                self.session()

    def test_port_cannot_be_exposed_or_changed(self):
        for port in (0,8181,8768,True,"8767"):
            self.config["listen_port"]=port
            self.write("config.json",gate.canon(self.config))
            with self.subTest(port=port),self.assertRaisesRegex(
                    app.OperatorServiceDenied,"OPERATOR_PORT_NOT_FIXED"):
                self.session()

    def test_configuration_extra_arbitrary_command_denied(self):
        for key in ("shell","url","docker_host"):
            config=dict(self.config)
            config[key]="rm -rf /"
            self.write("config.json",gate.canon(config))
            with self.subTest(key=key),self.assertRaisesRegex(
                    app.OperatorServiceDenied,"OPERATOR_CONFIG_SCHEMA_DENIED"):
                self.session()

    def test_wrong_host_not_cross_authorized(self):
        self.request["host_id"]="orange-pi"
        self.write("request.json",gate.canon(self.request))
        with self.assertRaisesRegex(gate.UpgradeDenied,"PLAN_HOST_MISMATCH"):
            self.session()

    def test_source_mismatch_denied_without_signing(self):
        self.config["active_hashes"]["fieldwork_mcp.py"]="f"*64
        self.write("config.json",gate.canon(self.config))
        with self.assertRaisesRegex(gate.UpgradeDenied,"PLAN_ACTIVE_SOURCE_MISMATCH"):
            self.session()
        self.assertFalse(list((self.root/"approved").iterdir()))

    def test_owner_only_permissions_required_for_config_and_secrets(self):
        for name in ("config.json","request.json","approval_hmac.key",
                     "operator_token.key"):
            file=self.root/name
            file.chmod(0o644)
            with self.subTest(name=name),self.assertRaisesRegex(
                    app.OperatorServiceDenied,"OPERATOR_FILE_MODE_OR_SIZE_DENIED"):
                self.session()
            file.chmod(0o600)

    def test_canonical_json_required(self):
        self.write("config.json",json.dumps(self.config).encode("ascii"))
        with self.assertRaisesRegex(app.OperatorServiceDenied,
                                    "OPERATOR_JSON_NONCANONICAL"):
            self.session()

    def test_symlink_secret_denied(self):
        key=self.root/"operator_token.key"
        outside=self.root/"secret-original"
        outside.write_bytes(TOKEN)
        key.unlink()
        key.symlink_to(outside)
        with self.assertRaisesRegex(app.OperatorServiceDenied,
                                    "OPERATOR_FILE_MISSING_OR_SYMLINK"):
            self.session()

    def test_missing_private_approval_dir_denied(self):
        (self.root/"approved").rmdir()
        with self.assertRaises(Exception):
            self.session()

    def test_invalid_local_browser_secret_denied(self):
        self.write("operator_token.key",HMAC)
        with self.assertRaisesRegex(Exception,"REVIEW_OPERATOR_AUTH_INVALID"):
            self.session()

    def test_local_operator_only_no_source_or_docker_changes(self):
        import inspect
        s=inspect.getsource(app)
        for forbidden in ("subprocess.run(","os.system(","docker stop","docker rm",
                          "shell=True",".unlink(","sudo -n","eval("):
            self.assertNotIn(forbidden,s)


if __name__=="__main__":
    unittest.main()
