"""Tests for M14D Docker read-only projection -- no host Docker access."""
import json
import os
import socket
import threading
import unittest
from unittest.mock import patch

from updater import linux_docker_read_proxy as p


def packet(operation="inventory"):
    return json.dumps({"version":1,"operation":operation},
                      separators=(",",":")).encode("ascii")+b"\n"


def inventory_result():
    return {
        "status":"READ_ONLY_HOST_DOCKER_INVENTORY",
        "total":1,"rows":[{"id":"a"*64,"name":"fieldwork-api-1",
                         "state":"running","created":"fixed"}],
        "inventory_sha256":"a"*64,
        "host_modified":False,"production_modified":False,
        "container_removal_authorized":False,
        "sandbox_test_retry_authorized":False
    }


def stats_result():
    return {
        "status":"READ_ONLY_DOCKER_RESOURCE_STATS",
        "scope":"docker_running_containers",
        "cpu_unit":"percent_of_one_cpu_core_can_exceed_100",
        "count":1,
        "rows":[{"container_id":"a"*12,
                 "name":"fieldwork-api-1","cpu_percent_of_one_core":13.1,
                 "memory_used_bytes":12288,"memory_limit_bytes":1048576}],
        "write_performed":False,"production_modified":False,
    }


class ReadProxyUnitTests(unittest.TestCase):
    def test_only_two_fixed_names_in_protocol(self):
        self.assertEqual(p.OPERATIONS,{"inventory","resources"})
        self.assertEqual(p.parse_request(packet("inventory")),"inventory")
        self.assertEqual(p.parse_request(packet("resources")),"resources")

    def test_forged_requests_fail_closed(self):
        bad=[
            b"",b"{}",b'{"version":1,"operation":"inventory"}',
            b'{"version":1,"operation":"inventory"}\n\n',
            b'{"version":true,"operation":"inventory"}\n',
            b'{"version":1,"operation":"stop"}\n',
            b'{"version":1,"operation":"exec"}\n',
            b'{"version":1,"operation":"inventory","command":"rm -f"}\n',
            b'{"version":1,"operation":"inventory","operation":"resources"}\n',
            b'{"version":1,"operation":null}\n',
            b'{"version":1,"operation":"inventory","path":"/var/run/docker.sock"}\n',
            b"x"*513+b"\n",
            b'{"version":NaN,"operation":"inventory"}\n',
            b'{"version":1,"operation":"inventory"}\nSECRET',
        ]
        for item in bad:
            with self.subTest(item=item[:60]),self.assertRaises(p.ProxyDenied):
                p.parse_request(item)

    def test_strict_dispatch_exact_old_inventory_and_m13_stats(self):
        with patch.object(p.inventory,"docker_inventory",return_value=inventory_result()) as inv,patch.object(
                p.telemetry,"docker_stats",return_value=stats_result()) as stats:
            got=p.dispatch("inventory")
            self.assertEqual(got["status"],"READ_ONLY_HOST_DOCKER_INVENTORY")
            inv.assert_called_once_with({})
            stats.assert_not_called()
            got=p.dispatch("resources")
            self.assertEqual(got["status"],"READ_ONLY_DOCKER_RESOURCE_STATS")
            stats.assert_called_once_with({})
        with self.assertRaisesRegex(p.ProxyDenied,"DOCKER_PROXY_OPERATION_DENIED"):
            p.dispatch("delete")

    def test_deny_untrusted_backend_status_or_mutation(self):
        mutated=inventory_result()
        mutated["host_modified"]=True
        with patch.object(p.inventory,"docker_inventory",return_value=mutated):
            with self.assertRaisesRegex(p.ProxyDenied,"DOCKER_PROXY_INVENTORY_RESULT_DENIED"):
                p.dispatch("inventory")
        mutated2=stats_result()
        mutated2["write_performed"]=True
        with patch.object(p.telemetry,"docker_stats",return_value=mutated2):
            with self.assertRaisesRegex(p.ProxyDenied,"DOCKER_PROXY_STATS_RESULT_DENIED"):
                p.dispatch("resources")

    def test_output_limits_do_not_spill_secrets(self):
        with self.assertRaises(p.ProxyDenied):
            p.encode_result({"status":"UNKNOWN"})
        bad=inventory_result()
        bad["secret"]="x"*p.MAX_REPLY
        with self.assertRaisesRegex(p.ProxyDenied,"DOCKER_PROXY_REPLY_TOO_LARGE"):
            p.encode_result(bad)

    def test_root_self_or_wrong_peer_denied(self):
        for peer,allowed,helper in ((0,1000,1001),(1000,1001,2000),
                                    (1000,1000,1000),(1000,0,2000),
                                    (True,1000,2000)):
            with self.subTest(peer=peer,allowed=allowed,helper=helper),self.assertRaisesRegex(
                p.ProxyDenied,"DOCKER_PROXY_PEER_CREDENTIALS_DENIED"):
                p.check_peer_uid(peer,allowed_mcp_uid=allowed,helper_uid=helper)

    def test_docker_backend_has_no_arbitrary_command_verb(self):
        import inspect
        source=inspect.getsource(p)
        self.assertNotIn("shell=True",source)
        self.assertNotIn("subprocess.run(",source)
        self.assertNotIn("docker stop",source)
        self.assertNotIn("docker rm",source)
        self.assertNotIn("docker exec",source)
        self.assertNotIn("sudo -n",source)
        self.assertNotIn("os.system(",source)

    def test_requires_exact_socket_activation_environment(self):
        with patch.dict(os.environ,{"LISTEN_PID":"0","LISTEN_FDS":"1"},clear=True):
            with self.assertRaisesRegex(p.ProxyDenied,"DOCKER_PROXY_ACTIVATION_ENV_DENIED"):
                p.activated_listener()
        with patch.dict(os.environ,{"LISTEN_PID":str(os.getpid()),"LISTEN_FDS":"9"},clear=True):
            with self.assertRaisesRegex(p.ProxyDenied,"DOCKER_PROXY_ACTIVATION_ENV_DENIED"):
                p.activated_listener()


@unittest.skipUnless(hasattr(socket,"SO_PEERCRED"),"Linux SO_PEERCRED required")
class RealUnixCredentialsTests(unittest.TestCase):
    def talk(self,message,*,allowed=None,handler=None):
        client,server=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        uid=os.geteuid()
        self.assertGreater(uid,0)
        calls=[]
        def worker():
            try:
                calls.append(p.serve_connection(server,
                    allowed_mcp_uid=uid if allowed is None else allowed,
                    helper_uid=uid+1))
            finally:
                server.close()
        thread=threading.Thread(target=worker,daemon=True)
        with client:
            # Send before starting the worker to avoid a denial-path
            # scheduling race: the helper may close immediately after
            # rejecting the peer credential (BrokenPipe is not a backend bug).
            client.sendall(message)
            client.shutdown(socket.SHUT_WR)
            thread.start()
            output=client.recv(p.MAX_REPLY+1024)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        return json.loads(output),calls

    def test_real_peer_credentials_and_inventory_response(self):
        with patch.object(p.inventory,"docker_inventory",return_value=inventory_result()) as inv:
            response,calls=self.talk(packet("inventory"))
        self.assertEqual(response["total"],1)
        self.assertEqual(calls,[True])
        inv.assert_called_once_with({})

    def test_real_socket_rejects_mismatched_uid(self):
        with patch.object(p.inventory,"docker_inventory",return_value=inventory_result()) as inv:
            response,calls=self.talk(packet("inventory"),allowed=os.geteuid()+5)
        self.assertEqual(response,{"status":"DOCKER_PROXY_DENIED"})
        self.assertEqual(calls,[False])
        inv.assert_not_called()

    def test_real_socket_rejects_mutating_request_before_backend(self):
        with patch.object(p.inventory,"docker_inventory",return_value=inventory_result()) as inv:
            response,calls=self.talk(packet("delete"))
        self.assertEqual(response,{"status":"DOCKER_PROXY_DENIED"})
        self.assertEqual(calls,[False])
        inv.assert_not_called()

    def test_real_socket_stats_return_bounded_sanitized_response(self):
        with patch.object(p.telemetry,"docker_stats",return_value=stats_result()) as fn:
            response,calls=self.talk(packet("resources"))
        self.assertEqual(response["count"],1)
        self.assertEqual(calls,[True])
        fn.assert_called_once_with({})


if __name__=="__main__":
    unittest.main()
