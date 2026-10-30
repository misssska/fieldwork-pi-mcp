# FieldWork Pi MCP updater — security architecture

## Current state

This repository currently contains a **download-and-stage component**, not an unattended installer. It cannot modify the running MCP, the existing tunnel, or production FieldWork. Do not advertise it as deployed to the Pi.

## Trust and release model

1. Developer prepares an MCP release in GitHub with a JSON manifest containing relative allowlisted file names and SHA-256 digests.
2. A release is identified by an **immutable 40-character commit SHA**, and its manifest digest is approved out-of-band.
3. The stager downloads only from `raw.githubusercontent.com/misssska/fieldwork-pi-mcp/<commit>/release/...`. It rejects redirects, extra manifest fields, traversal paths, symlink staging paths, hash mismatches and unexpected code.
4. It writes only to the user's private `~/.local/state/fieldwork-pi-mcp/update-staging` directory. **It never executes downloaded code.**
5. A future separate local executor must verify the stage receipt, exact installed-source SHA, isolated test evidence, backup/rollback plan, and an explicit one-time local approval **before** replacing any MCP files. That executor is **not yet implemented or installed**.

## Non-negotiable boundaries

- No remote shell exposed through MCP.
- No automatic production deployment, and no access to `/opt/fieldwork`, production Docker volumes or database.
- No unattended update or restart.
- No private keys, passwords, environment files, API tokens or customer data in this public repository.
- Never replace a live MCP source file solely by changing a hard-coded expected hash.
- The existing `fieldwork-pi-tunnel.service` remains the only tunnel; no second tunnel.
- Candidate changes must preserve existing behavior and be tested against the actual installed Pi source, not an assumed baseline.

## Next milestone

Obtain a trustworthy, redacted snapshot of the installed MCP source and compare its SHA-256 with `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`. Then implement a separately approved local executor with atomic activation, restart health checks, persistent logs and rollback. Only after that can GitHub-based remote update requests replace ZIP/manual installs.
