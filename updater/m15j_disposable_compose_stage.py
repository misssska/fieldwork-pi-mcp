"""M15-J4 disposable three-service *Compose fixture* CI, NOT Pi stage deploy.

Real two-image Docker build, PostgreSQL startup/query, nginx -> API HTTP proxy,
bounded down. Entire source tree and Compose model are generated from fixed
Python literals, with image references constrained to full OCI digests. No
external caller YAML, filesystem paths, commands, host bind mounts, host ports,
or access to production. No remote MCP entrypoint or service unit.

This validates the *mechanics* of Compose build/up/smoke/down, NOT the legacy
FieldWork stage_manager exact release and not 36-tool shadow parity.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

DOCKER = "/usr/bin/docker"
OCI = re.compile(r"[a-z0-9][a-z0-9._/-]{1,160}@sha256:[a-f0-9]{64}\Z")
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
PREFIX = "fieldwork-m15jstage-"
SERVICES = ("api", "db", "nginx")

API_CONF = """server {
    listen 8080;
    server_name _;
    location = /health {
        default_type text/plain;
        return 200 'ok';
    }
    location / { return 404; }
}
"""
PROXY_CONF = """server {
    listen 8080;
    server_name _;
    location = /health {
        proxy_pass http://api:8080/health;
        proxy_set_header Host api;
    }
    location / { return 404; }
}
"""


class StageFixtureDenied(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise StageFixtureDenied(code)


def qualify(run_id: str, nginx_image: str, pg_image: str) -> str:
    require(type(run_id) is str and HEX32.fullmatch(run_id) is not None and
            type(nginx_image) is str and OCI.fullmatch(nginx_image) is not None
            and ("/nginx@" in nginx_image or nginx_image.startswith("nginx@"))
            and type(pg_image) is str and OCI.fullmatch(pg_image) is not None
            and ("/postgres@" in pg_image or pg_image.startswith("postgres@")),
            "M15J4_FIXED_PINNED_IMAGES_OR_ID_REQUIRED")
    return PREFIX + run_id


def compose_model(*, project: str, nginx_image: str, pg_image: str) -> dict:
    require(type(project) is str and project.startswith(PREFIX) and
            HEX32.fullmatch(project[len(PREFIX):]) is not None,
            "M15J4_PROJECT_DENIED")
    common_nginx = {
        "read_only": True, "user": "101:101", "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 64, "mem_limit": "128m",
        "tmpfs": ["/tmp:rw,mode=1777",
                  "/var/cache/nginx:rw,uid=101,gid=101,mode=0700",
                  "/var/run:rw,uid=101,gid=101,mode=0700"],
        "networks": ["default"],
        "healthcheck": {"test": ["CMD", "wget", "-q", "-O", "-",
                                 "http://127.0.0.1:8080/health"],
                        "interval": "3s", "timeout": "3s",
                        "retries": 20, "start_period": "3s"},
    }
    return {
        "name": project,
        "services": {
            "db": {
                "image": pg_image, "read_only": True, "user": "70:70",
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "pids_limit": 64, "mem_limit": "256m",
                "tmpfs": [
                    "/var/lib/postgresql/data:rw,uid=70,gid=70,mode=0700",
                    "/var/run/postgresql:rw,uid=70,gid=70,mode=0775",
                    "/tmp:rw,mode=1777",
                ],
                "environment": {
                    "POSTGRES_HOST_AUTH_METHOD": "trust",
                    "PGDATA": "/var/lib/postgresql/data/pgdata",
                },
                "healthcheck": {"test": ["CMD", "pg_isready", "-U", "postgres"],
                                "interval": "3s", "timeout": "3s",
                                "retries": 20, "start_period": "3s"},
                "networks": ["default"],
            },
            "api": {
                **common_nginx,
                "build": {"context": "./api", "dockerfile": "Dockerfile"},
                "depends_on": {"db": {"condition": "service_healthy"}},
            },
            "nginx": {
                **common_nginx,
                "build": {"context": "./nginx", "dockerfile": "Dockerfile"},
                "depends_on": {"api": {"condition": "service_healthy"}},
            },
        },
        "networks": {"default": {"internal": True}},
    }


def _write_fixture(root: Path, *, project: str,
                   nginx_image: str, pg_image: str) -> Path:
    require(root.is_dir() and not root.is_symlink(),
            "M15J4_ROOT_NOT_PRIVATE")
    conf = compose_model(project=project, nginx_image=nginx_image,
                         pg_image=pg_image)
    for service, nginx_conf in (("api", API_CONF), ("nginx", PROXY_CONF)):
        target = root / service
        target.mkdir(mode=0o700)
        dockerfile = ("FROM " + nginx_image + "\n"
                      + "COPY default.conf /etc/nginx/conf.d/default.conf\n")
        (target / "Dockerfile").write_text(dockerfile, encoding="ascii")
        (target / "default.conf").write_text(nginx_conf, encoding="ascii")
    file = root / "compose.json"
    file.write_text(json.dumps(conf, sort_keys=True, separators=(",", ":")),
                    encoding="ascii")
    return file


def _docker(argv: tuple[str, ...], *, timeout: int = 120) -> str:
    require(type(argv) is tuple and argv and argv[0] == DOCKER and
            type(timeout) is int and 1 <= timeout <= 240,
            "M15J4_DOCKER_INVOCATION_DENIED")
    require(argv[1:2] in (("compose",), ("container",), ("network",)),
            "M15J4_DOCKER_VERB_DENIED")
    try:
        r = subprocess.run(list(argv), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           cwd="/", env={"PATH": "/usr/bin:/bin",
                                         "HOME": "/nonexistent"},
                           timeout=timeout, check=False, shell=False)
    except (OSError, subprocess.SubprocessError):
        raise StageFixtureDenied("M15J4_DOCKER_TRANSPORT_UNVERIFIED") from None
    require(r.returncode == 0 and len(r.stdout) <= 8192,
            "M15J4_DOCKER_COMMAND_FAILED_OR_OUTPUT_OVERSIZE")
    try:
        return r.stdout.decode("ascii").strip()
    except UnicodeError:
        raise StageFixtureDenied("M15J4_OUTPUT_ENCODING_DENIED") from None


def _compose_args(project: str, file: Path, *action: str) -> tuple[str, ...]:
    require(type(project) is str and project.startswith(PREFIX)
            and HEX32.fullmatch(project[len(PREFIX):]) is not None and
            file.name == "compose.json" and file.is_file(),
            "M15J4_COMPOSE_PATH_OR_NAME_DENIED")
    require(action in (("build",), ("up", "--detach", "--wait",
                                  "--wait-timeout", "90"),
                       ("down",)),
            "M15J4_COMPOSE_ACTION_DENIED")
    return (DOCKER, "compose", "-p", project, "-f", str(file), *action)


def _project_containers(project: str) -> list[tuple[str, str]]:
    """Before compose down: refuse unexpected service/name or duplicates."""
    fmt = '{{.Names}}|{{.Label "com.docker.compose.service"}}'
    cmd = (DOCKER, "container", "ls", "--all",
           "--filter", "label=com.docker.compose.project=" + project,
           "--format", fmt)
    raw = _docker(cmd)
    rows = [] if not raw else [tuple(line.split("|")) for line in raw.splitlines()]
    require(len(rows) <= 3 and all(len(row) == 2 for row in rows) and
            set(rows) <= {(project + "-" + s + "-1", s) for s in SERVICES},
            "M15J4_COMPOSE_FOREIGN_CONTAINER_REFUSED")
    require(len(rows) == len(set(rows)),
            "M15J4_COMPOSE_DUPLICATE_CONTAINER_REFUSED")
    return rows


def run_fixed_stage(*, run_id: str, nginx_image: str, pg_image: str,
                    source_locally_trusted: bool,
                    ci_disposable_host: bool) -> dict:
    require(source_locally_trusted is True and
            ci_disposable_host is True and os.geteuid() != 0,
            "M15J4_CI_ONLY_NONROOT")
    project = qualify(run_id, nginx_image, pg_image)
    ready = False
    cleanup = False
    with tempfile.TemporaryDirectory(prefix="m15j4-fixture-") as tmp:
        root = Path(tmp)
        file = _write_fixture(root, project=project,
                              nginx_image=nginx_image, pg_image=pg_image)
        try:
            _docker(_compose_args(project, file, "build"), timeout=240)
            _docker(_compose_args(project, file, "up", "--detach", "--wait",
                                  "--wait-timeout", "90"), timeout=150)
            _project_containers(project)
            def exec_argv(service: str, *args: str) -> tuple[str, ...]:
                require(service in SERVICES, "M15J4_SERVICE_DENIED")
                return (DOCKER, "compose", "-p", project, "-f",
                        str(file), "exec", "-T", service, *args)
            api_result = _docker(exec_argv(
                "nginx", "wget", "-q", "-O", "-",
                "http://127.0.0.1:8080/health"))
            sql_result = _docker(exec_argv(
                "db", "psql", "-U", "postgres", "-X", "-tAc", "SELECT 1"))
            require(api_result == "ok" and sql_result == "1",
                    "M15J4_STAGE_HTTP_OR_SQL_SMOKE_FAILED")
            ready = True
        finally:
            # The independent CI-only project is constructed from immutable
            # local literals, not an existing M12 release or input YAML.
            # If a foreign container has gained this project label, STOP.
            _project_containers(project)
            _docker(_compose_args(project, file, "down"), timeout=120)
            cleanup = _project_containers(project) == []
    require(ready and cleanup, "M15J4_STAGE_NOT_CLEANLY_VERIFIED")
    return {"status": "M15J4_NATIVE_COMPOSE_BUILD_UP_HTTP_SQL_DOWN_PASS",
            "project": project, "services": list(SERVICES),
            "image_build_verified": True, "http_proxy_verified": True,
            "postgres_sql_verified": True,
            "compose_resources_cleaned": True,
            "host_ports_published": False,
            "host_bind_mounts_used_at_runtime": False,
            "production_modified": False,
            "pi_host_executed": False,
            "real_fieldwork_stage_release_parity": False,
            "mcp_36_tool_parity": False,
            "cutover_authorized": False}
