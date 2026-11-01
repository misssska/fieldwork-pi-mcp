# syntax=docker/dockerfile:1.7
# Candidate only. Never build from /opt/fieldwork or an unverified upload.
# BuildKit named contexts:
#   fieldwork_base = separately pinned, audited, clean private Git base
#   policy         = reviewed appliance/ directory from immutable MCP commit
# Both base image args MUST be image digests, not mutable tags.
ARG NODE_BASE
ARG POSTGRES_BASE
FROM ${NODE_BASE} AS node_source
FROM ${POSTGRES_BASE} AS appliance

USER root
COPY --from=node_source /usr/local/bin/node /usr/local/bin/node
COPY --from=node_source /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip libnss-wrapper ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=fieldwork_base frontend/package.json frontend/package-lock.json /build/frontend/
COPY --from=fieldwork_base server/requirements.txt server/requirements-dev.txt /build/server/
COPY --from=policy fieldwork-test-suite /usr/local/bin/fieldwork-test-suite

ARG FRONTEND_LOCK_SHA256
ARG BACKEND_REQUIREMENTS_SHA256
ARG BACKEND_DEV_REQUIREMENTS_SHA256
ARG CONTRACT_SHA256
RUN set -eu; \
    test "$(sha256sum /build/frontend/package-lock.json | cut -d' ' -f1)" = "${FRONTEND_LOCK_SHA256}"; \
    test "$(sha256sum /build/server/requirements.txt | cut -d' ' -f1)" = "${BACKEND_REQUIREMENTS_SHA256}"; \
    test "$(sha256sum /build/server/requirements-dev.txt | cut -d' ' -f1)" = "${BACKEND_DEV_REQUIREMENTS_SHA256}"; \
    test "$(sha256sum /usr/local/bin/fieldwork-test-suite | cut -d' ' -f1)" = "${CONTRACT_SHA256}"; \
    cd /build/frontend; \
    npm ci --ignore-scripts --no-audit --no-fund; \
    mkdir -p /build/frontend/node_modules; \
    python3 -m venv /opt/fieldwork-test-venv; \
    /opt/fieldwork-test-venv/bin/pip install --disable-pip-version-check --no-cache-dir -r /build/server/requirements-dev.txt; \
    install -d -m 0755 /opt/fieldwork-test; \
    mv /build/frontend/node_modules /opt/fieldwork-test/node_modules; \
    chmod 0755 /usr/local/bin/fieldwork-test-suite; \
    /usr/local/bin/fieldwork-test-suite --contract-check

LABEL org.fieldwork.appliance.profile="fieldwork-offline-test-appliance-v1" \
      org.fieldwork.appliance.frontend-lock-sha256="${FRONTEND_LOCK_SHA256}" \
      org.fieldwork.appliance.backend-requirements-sha256="${BACKEND_REQUIREMENTS_SHA256}" \
      org.fieldwork.appliance.backend-dev-requirements-sha256="${BACKEND_DEV_REQUIREMENTS_SHA256}" \
      org.fieldwork.appliance.production-access="denied" \
      org.fieldwork.appliance.scope="isolated-test-only" \
      org.fieldwork.appliance.script-sha256="${CONTRACT_SHA256}"

ENV PATH="/opt/fieldwork-test-venv/bin:/usr/lib/postgresql/18/bin:/usr/local/bin:/usr/bin:/bin"
WORKDIR /work
# Override the inherited upstream postgres entrypoint: accidentally running
# this image without one exact suite must immediately fail, never start a DB.
ENTRYPOINT ["/usr/local/bin/fieldwork-test-suite"]
CMD ["NO_UNAPPROVED_DEFAULT_SUITE"]
# The approved host runner also sets this exact entrypoint plus --user,
# --network=none, read-only root, /work and /tmp tmpfs, stage read-only
# source mount, and NEVER a Docker socket or production volume.
