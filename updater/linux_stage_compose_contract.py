"""M14F: fail-closed, pure Compose configuration admission for fixed stage.

Offline contract for a NEW, image-pinned, rebuild-free Compose design.
This does not accept the current M12 FieldWork Compose release (which uses
build). It does not execute Docker, read live files, restart containers, or
approve a release. The real stage release needs a dedicated migration.

No YAML parser: the caller supplies docker compose config --format json
from a separately validated, locally owned source path. The source bytes
must be exact SHA-pinned against trusted local release metadata.
"""
from __future__ import annotations

import hashlib
import json
import re

PROJECT = "fieldwork-stage"
SERVICES = ("api", "db", "nginx")
TOP_KEYS = frozenset(("name", "services", "networks", "volumes"))
SERVICE_KEYS = frozenset((
    "image", "read_only", "cap_drop", "security_opt", "networks", "user",
    "init", "pids_limit", "mem_limit", "ports", "volumes",
))
OCI = re.compile(r"[a-z0-9][a-z0-9._/-]{1,160}@sha256:[a-f0-9]{64}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
MAX_JSON = 32_768


class ComposeDenied(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ComposeDenied(reason)


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        require(name not in result, "STAGE_COMPOSE_DUPLICATE_KEY")
        result[name] = value
    return result


def _parse(data: bytes) -> dict:
    require(type(data) is bytes and 1 <= len(data) <= MAX_JSON,
            "STAGE_COMPOSE_JSON_SIZE_DENIED")
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(
                             ComposeDenied("STAGE_COMPOSE_NONFINITE_DENIED")))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, ComposeDenied):
            raise
        raise ComposeDenied("STAGE_COMPOSE_JSON_DENIED") from exc
    require(type(obj) is dict and set(obj) == TOP_KEYS,
            "STAGE_COMPOSE_TOP_KEYS_DENIED")
    return obj


def validate_config(config_json: bytes, *, locally_pinned_images: dict,
                    source_sha256: str, actual_source_sha256: str) -> dict:
    """Admit a minimal exact stage project, never a runnable Docker command."""
    require(type(source_sha256) is str and
            SHA64.fullmatch(source_sha256) is not None and
            type(actual_source_sha256) is str and
            source_sha256 == actual_source_sha256,
            "STAGE_COMPOSE_SOURCE_DRIFT")
    require(type(locally_pinned_images) is dict and
            set(locally_pinned_images) == set(SERVICES) and
            all(type(value) is str and OCI.fullmatch(value)
                for value in locally_pinned_images.values()),
            "STAGE_COMPOSE_LOCAL_IMAGE_PINS_DENIED")
    obj = _parse(config_json)
    require(obj["name"] == PROJECT and
            type(obj["name"]) is str,
            "STAGE_COMPOSE_PROJECT_DENIED")
    require(type(obj["services"]) is dict and
            set(obj["services"]) == set(SERVICES),
            "STAGE_COMPOSE_SERVICE_SET_DENIED")
    require(obj["networks"] == {
        "default": {"name": "fieldwork-stage_default", "internal": True}},
        "STAGE_COMPOSE_NETWORK_DENIED")
    require(obj["volumes"] == {
        "data": {"name": "fieldwork-stage_data"}},
        "STAGE_COMPOSE_VOLUMES_DENIED")

    images = {}
    for service in SERVICES:
        item = obj["services"][service]
        require(type(item) is dict and
                SERVICE_KEYS.issuperset(item.keys()) and
                type(item.get("image")) is str and
                item["image"] == locally_pinned_images[service],
                "STAGE_COMPOSE_SERVICE_KEYS_OR_IMAGE_DENIED")
        require(item.get("read_only") is (service != "db") and
                item.get("cap_drop") == ["ALL"] and
                item.get("security_opt") == ["no-new-privileges:true"] and
                item.get("networks") == ["default"] and
                item.get("user") == "65534:65534" and
                item.get("init") is True and
                type(item.get("pids_limit")) is int and
                8 <= item["pids_limit"] <= 128 and
                type(item.get("mem_limit")) is str and
                re.fullmatch(r"(?:64|96|128|192|256|384|512)[mM]",
                             item["mem_limit"]) is not None,
                "STAGE_COMPOSE_SERVICE_SECURITY_DENIED")

        if service == "nginx":
            require(item.get("ports") == [{
                "target": 80, "published": "18081",
                "host_ip": "127.0.0.1", "protocol": "tcp",
            }], "STAGE_COMPOSE_PUBLIC_PORT_DENIED")
        else:
            require("ports" not in item, "STAGE_COMPOSE_UNEXPECTED_PORT")

        if service == "db":
            require(item.get("volumes") == [{
                "type": "volume", "source": "data",
                "target": "/var/lib/postgresql/data",
                "read_only": False,
            }], "STAGE_COMPOSE_DB_VOLUME_DENIED")
        else:
            require("volumes" not in item, "STAGE_COMPOSE_UNEXPECTED_MOUNT")
        images[service] = item["image"]

    return {
        "status": "STAGE_COMPOSE_OFFLINE_ADMITTED",
        "scope": "fixed_fieldwork_stage_only",
        "source_sha256": source_sha256,
        "rendered_config_sha256": hashlib.sha256(config_json).hexdigest(),
        "image_digests": images,
        "docker_command_executed": False,
        "release_publisher_verified": False,
        "activation_authorized": False,
        "production_modified": False,
    }
