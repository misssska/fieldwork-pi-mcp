"""M14D local Docker proxy helper/client and reference unit tests."""
from pathlib import Path
import configparser
import os
import socket
import stat
import tempfile
import unittest
import json
import threading
from unittest.mock import patch
from updater import linux_docker_read_proxy_client as client
from updater import linux_docker_read_proxy_service as service
from updater import linux_docker_read_proxy as protocol


class LocalServiceTests(unittest.TestCase):
    def test_only_fixed_local_file_for_allowed_client_uid(self):
        with tempfile.TemporaryDirectory() as td:
            parent=Path(td)
            cfg=parent/"client.json"
            cfg.write_bytes(b'{"version":1,"client_uid":2142}')
            cfg.chmod(0o600)
            with patch.object(service.os,"geteuid",return_value=os.geteuid()):
                got=service.read_fixed_config(config=cfg)
            self.assertEqual(got,2142)

    def test_reject_unknown_config_fields_and_same_uid(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"client.json"
            for body in (
                {"version":1,"client_uid":os.geteuid(),"sudo":True},
                {"version":1,"client_uid":os.geteuid()},
                {"version":1,"client_uid":True},
                {"version":1,"client_uid":0},
                {"version":2,"client_uid":2142},
            ):
                p.write_bytes(json.dumps(body).encode("ascii"))
                p.chmod(0o600)
                with self.subTest(body=body),self.assertRaises(service.DockerHelperDenied):
                    service.read_fixed_config(config=p)

    def test_symlink_and_public_config_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            parent=Path(td)
            p=parent/"client.json"
            p.write_bytes(b'{"version":1,"client_uid":2142}')
            p.chmod(0o644)
            with self.assertRaisesRegex(service.DockerHelperDenied,
                                        "DOCKER_HELPER_CONFIG_MODE_DENIED"):
                service.read_fixed_config(config=p)
            p.chmod(0o600)
            link=parent/"symlink"/"client.json"
            (parent/"symlink").symlink_to(parent,target_is_directory=True)
            # Parent symlink is forbidden in deployment; require fix below.
            with self.assertRaises(service.DockerHelperDenied):
                service.read_fixed_config(config=link)

    def test_no_host_shell_or_mutable_daemon_requests(self):
        import inspect
        s=inspect.getsource(service)
        for forbidden in ("subprocess.run(","os.system(","docker rm","docker stop",
                          "shell=True","sudo -n","exec(","eval("):
            self.assertNotIn(forbidden,s)


class ClientSocketTests(unittest.TestCase):
    def test_invalid_op_denied_without_connect(self):
        for bad in ("stop","exec","delete","system prune","localhost",None):
            with self.subTest(bad=bad),self.assertRaises(client.ClientDenied):
                client.query(bad)

    def test_unreachable_socket_is_safe_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(client.ClientDenied,
                                        "DOCKER_CLIENT_LOCAL_HELPER_UNAVAILABLE"):
                client.query("inventory",socket_path=Path(td)/"missing.sock")

    def test_local_integration_with_real_peer_uid(self):
        with tempfile.TemporaryDirectory() as td:
            endpoint=Path(td)/"proxy.sock"
            server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            server.bind(str(endpoint))
            server.listen(2)
            result=[]
            def worker():
                try:
                    with server:
                        conn,_=server.accept()
                        with conn:
                            result.append(protocol.serve_connection(
                                conn,allowed_mcp_uid=os.geteuid(),
                                helper_uid=os.geteuid()+1))
                except Exception as exc:
                    result.append(type(exc).__name__)
            t=threading.Thread(target=worker,daemon=True)
            t.start()
            data={
                "status":"READ_ONLY_HOST_DOCKER_INVENTORY",
                "total":0,"rows":[],"inventory_sha256":"f"*64,
                "host_modified":False,"production_modified":False,
                "container_removal_authorized":False,
                "sandbox_test_retry_authorized":False
            }
            with patch.object(protocol.inventory,"docker_inventory",return_value=data):
                got=client.query("inventory",socket_path=endpoint)
            t.join(timeout=3)
            self.assertEqual(result,[True])
            self.assertEqual(got["total"],0)

    def test_client_does_not_call_docker_socket_directly(self):
        import inspect
        s=inspect.getsource(client)
        for forbidden in ('"/var/run/docker.sock"',"docker stop","subprocess.run(",
                          "shell=True","os.system("):
            self.assertNotIn(forbidden,s)


class DockerProxyServiceUnitTests(unittest.TestCase):
    def test_socket_unit_preserves_no_docker_group_for_mcp(self):
        root=Path(__file__).resolve().parent.parent/"deploy/systemd"
        sock=(root/"linux-mcp-docker-proxy.socket").read_text()
        self.assertIn("SocketGroup=linux-mcp-client",sock)
        self.assertIn("SocketMode=0660",sock)
        self.assertIn("Accept=no",sock)
        self.assertNotIn("SocketGroup=docker",sock)
        self.assertIn("ListenStream=/run/linux-mcp-docker-proxy.sock",sock)

    def test_helper_is_separate_from_operator_and_docker_privilege_visible(self):
        root=Path(__file__).resolve().parent.parent/"deploy/systemd"
        serviceunit=(root/"linux-mcp-docker-proxy.service").read_text()
        self.assertIn("User=linux-mcp-docker-helper",serviceunit)
        self.assertIn("SupplementaryGroups=docker",serviceunit)
        self.assertIn("PrivateNetwork=yes",serviceunit)
        self.assertIn("ProtectSystem=strict",serviceunit)
        self.assertIn("NoNewPrivileges=yes",serviceunit)
        self.assertIn("IPAddressDeny=any",serviceunit)
        self.assertNotIn("User=linux-mcp-operator",serviceunit)
        self.assertNotIn("ExecStart=/bin/sh",serviceunit)
        self.assertNotIn("0.0.0.0",serviceunit)


if __name__=="__main__":
    unittest.main()
