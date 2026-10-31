"""M14C static validation for disabled systemd operator unit.

No service installation or launch; validates clearly bounded privileges
and fail-closed production paths across architecture-independent package.
"""
from pathlib import Path
import configparser
import unittest


REPO=Path(__file__).resolve().parent.parent
UNIT=REPO/"deploy/systemd/linux-mcp-operator.service"


class SystemdPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=UNIT.read_text(encoding="utf-8")
        cls.config=configparser.ConfigParser(interpolation=None, strict=False)
        cls.config.optionxform=str
        cls.config.read_string(cls.text)
        cls.service=cls.config["Service"]

    def test_separate_non_root_user_and_no_general_capabilities(self):
        self.assertEqual(self.service["User"],"linux-mcp-operator")
        self.assertEqual(self.service["Group"],"linux-mcp-operator")
        self.assertEqual(self.service["NoNewPrivileges"],"yes")
        self.assertEqual(self.service["CapabilityBoundingSet"],"")
        self.assertEqual(self.service["AmbientCapabilities"],"")
        self.assertEqual(self.service["UMask"],"0077")

    def test_file_writes_only_private_state_directory(self):
        self.assertEqual(self.service["ProtectSystem"],"strict")
        self.assertEqual(self.service["ProtectHome"],"yes")
        self.assertEqual(self.service["ReadWritePaths"],"/var/lib/linux-mcp-operator")
        self.assertEqual(self.service["StateDirectory"],"linux-mcp-operator")
        self.assertEqual(self.service["StateDirectoryMode"],"0700")
        self.assertIn("ConditionPathExists=/var/lib/linux-mcp-operator/config.json",
                      self.text)

    def test_no_direct_network_ingress_or_docker_socket(self):
        self.assertEqual(self.service["RestrictAddressFamilies"],"AF_INET AF_UNIX")
        self.assertEqual(self.service["IPAddressDeny"],"any")
        self.assertEqual(self.service["IPAddressAllow"],"localhost")
        self.assertNotIn("/var/run/docker.sock",self.text)
        self.assertNotIn("0.0.0.0",self.text)
        self.assertNotIn("sudo",self.service["ExecStart"])
        self.assertNotIn("--install",self.service["ExecStart"])
        self.assertNotIn("--approve",self.service["ExecStart"])
        self.assertIn("--serve",self.service["ExecStart"])

    def test_is_only_reference_not_automatically_enabled(self):
        self.assertTrue(UNIT.exists())
        self.assertIn("NEVER enable",self.text)
        for setting in ["PrivateTmp=yes","PrivateDevices=yes",
                        "ProtectKernelModules=yes","ProtectControlGroups=yes",
                        "RestrictSUIDSGID=yes","LockPersonality=yes"]:
            self.assertIn(setting,self.text)


if __name__=="__main__":
    unittest.main()
