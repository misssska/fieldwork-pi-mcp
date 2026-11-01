#!/usr/bin/env bash
# FieldWork M5 R7 — read-only, no changes to production/staging/M4/M5.
set -uo pipefail
STATE="$HOME/.local/state/fieldwork-pi-mcp-v03/stage-v06"
BASE="$STATE/parity-m4.d2DIn9Zr"
project='fieldwork-parity-m5-r7'
test_project='fieldwork-parity-m5-r7-test'
port=18085
failed=0
check() {
  if "$@" >/dev/null 2>&1; then
    printf 'PASS %s\n' "$LABEL"
  else
    printf 'BLOCKED %s\n' "$LABEL"
    failed=$((failed+1))
  fi
}
source_file() { [ -f "$BASE/$1" ] && [ ! -L "$BASE/$1" ]; }
source_hash() { 
  source_file "$1" || return 1
  local actual
  actual="$(sha256sum -- "$BASE/$1")" || return 1
  [ "${actual%% *}" = "$2" ]
}
no_compose_project() {
  local output
  output="$(docker ps -aq --filter "label=com.docker.compose.project=$1" 2>/dev/null)" || return 1
  [ -z "$output" ]
}
port_free() {
  # If 'ss' unavailable, don't claim the port is free.
  command -v ss >/dev/null 2>&1 || return 1
  local listeners
  listeners="$(ss -H -ltn "sport = :$port" 2>/dev/null)" || return 1
  [ -z "$listeners" ]
}
mkdir_guard() { [ -d "$1" ] && [ ! -L "$1" ] && [ "$(realpath -e -- "$1")" = "$1" ]; }
LABEL='docker_read_access'; check docker info --format '{{.ServerVersion}}'
LABEL='M4_stage_root'; check mkdir_guard "$STATE"
LABEL='M4_exact_source_directory'; check mkdir_guard "$BASE"
LABEL='M4_team_api_sha256'; check source_hash 'server/app/team_api.py' 'cf1db461dd8c4fec2b055bf4c72837d50bcefd79f8b83559431d85c06e6eabe8'
LABEL='M4_PhotoGallery_sha256'; check source_hash 'frontend/src/components/PhotoGallery.tsx' '384315df61d71f116d56ed9571cc95cf6813edb81fc1ab236fc9dff2bccf2286'
LABEL='M4_DocumentViewer_test_sha256'; check source_hash 'frontend/src/components/DocumentViewer.test.tsx' '5e802a79179f9a171ed06160258bab0f31400045f7b615a85fcea37c04d6abef'
# check above uses exact M5 R7 requirement from launch_canary; reject source drift.
for rel in docker-compose.stage.yml docker-compose.m4-test-v4.yml .env.stage \
  frontend/src/components/PhotoGallery.test.tsx server/app/main.py \
  server/app/models.py server/scripts/migrate.py \
  server/alembic/versions/20260720_01_repair_legacy_project_memberships.py; do
    LABEL="M4_file_present:$rel"; check source_file "$rel"
done
LABEL='M5_R7_canary_project_unused'; check no_compose_project "$project"
LABEL='M5_R7_test_project_unused'; check no_compose_project "$test_project"
LABEL='port_18085_unbound'; check port_free
if command -v df >/dev/null 2>&1 && [ -d "$STATE" ]; then
  space="$(df -Pk -- "$STATE" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [[ "$space" =~ ^[0-9]+$ ]] && [ "$space" -ge 5242880 ]; then
    echo 'PASS stage_disk_free_at_least_5GiB'
  else
    echo 'BLOCKED stage_disk_free_at_least_5GiB'; failed=$((failed+1))
  fi
else
  echo 'BLOCKED stage_disk_free_at_least_5GiB'; failed=$((failed+1))
fi
if [ "$failed" -eq 0 ]; then
  echo 'M5_R7_ISOLATED_PREFLIGHT=PASS'
  echo 'M5_R7_TESTS_AND_CANARY_NOT_EXECUTED'
else
  echo "M5_R7_ISOLATED_PREFLIGHT=BLOCKED:$failed"
  echo 'NO_SOURCE_OR_CONTAINER_CHANGES_PERFORMED'
fi
