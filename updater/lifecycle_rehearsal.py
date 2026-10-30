"""Isolated end-to-end local-approval + four-file transaction rehearsal.

THIS IS NOT AN INSTALLER. Only test-owned /tmp/fieldwork-mcp-lifecycle-lab-*/mcp
is eligible. No host services, Docker, network, tunnel, commands, or real health
checks. The caller supplies a TEST signing key and SIMULATED health outcome.
The real Pi updater must be a separately audited locally approved component.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from . import local_approval_lab as approval
from . import lifecycle_transaction_lab as transaction

HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEALTH_CHOICES = frozenset({'pass', 'fail', 'error'})
DOMAIN = b'fieldwork-pi-mcp:lifecycle-module-bundle:v1\x00'


class RehearsalDenied(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RehearsalDenied(message)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _module_digest(payloads: dict[str, bytes]) -> str:
    """Bind ALL three runtime module byte hashes into the v1 proof extension pin."""
    require(type(payloads) is dict and set(payloads) == set(transaction.FILES),
            'PAYLOAD_SET_DENIED')
    out = bytearray(DOMAIN)
    for filename in transaction.MODULES:
        value = payloads[filename]
        require(type(value) is bytes and 0 < len(value) <= transaction.MAX_BYTES,
                'INVALID_MODULE_PAYLOAD')
        out.extend(filename.encode('ascii') + b'\x00')
        out.extend(bytes.fromhex(_sha(value)))
    return _sha(bytes(out))


def pins(*, commit: str, manifest_sha256: str,
         installed_sha256: str, payloads: dict[str, bytes]) -> dict[str, str]:
    """Derive a lab proof from fixed digest algorithms, never arbitrary paths."""
    require(type(commit) is str and HEX40.fullmatch(commit) is not None,
            'COMMIT_PIN_DENIED')
    require(type(manifest_sha256) is str and HEX64.fullmatch(manifest_sha256) is not None,
            'MANIFEST_PIN_DENIED')
    require(type(installed_sha256) is str and
            HEX64.fullmatch(installed_sha256) is not None, 'INSTALLED_PIN_DENIED')
    digest = _module_digest(payloads)
    main = payloads[transaction.MAIN]
    require(type(main) is bytes and 0 < len(main) <= transaction.MAX_BYTES,
            'INVALID_MAIN_PAYLOAD')
    return {'commit': commit, 'manifest_sha256': manifest_sha256,
            'installed_sha256': installed_sha256,
            'candidate_sha256': _sha(main), 'extension_sha256': digest}


def _consume_lab_nonce(root: Path, nonce: str) -> None:
    """One-use filesystem claim strictly inside the eligible disposable lab."""
    transaction._lab_root(root)
    require(type(nonce) is str and approval.HEX32.fullmatch(nonce) is not None,
            'NONCE_FORMAT_DENIED')
    filename = '.lab-approval-used-' + nonce
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                         os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
        except FileExistsError as exc:
            raise RehearsalDenied('LAB_APPROVAL_REPLAY_DENIED') from exc
        with os.fdopen(fd, 'wb') as stream:
            stream.write((nonce + '\n').encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def rehearse(*, root: Path, payloads: dict[str, bytes],
             installed_sha256: str, commit: str, manifest_sha256: str,
             token: dict, lab_key: bytes, simulated_health: str,
             fail_at: str | None = None) -> dict:
    """Test-only orchestration. Returns only simulated state and denial flags.

    Invariant: invalid proof cannot write the main source or any module.
    A validated replay claim is consumed before transaction changes.
    Failing or exceptional simulated health rolls the transaction back.
    No callback, shell, network request or user-controlled destination.
    """
    transaction._lab_root(root)
    require(type(simulated_health) is str and simulated_health in HEALTH_CHOICES,
            'SIMULATION_MODE_DENIED')
    require(fail_at is None or fail_at in {
        'after_journal', *(f'after_{name}' for name in transaction.MODULES),
        'after_main', 'after_applied'
    }, 'FAULT_INJECTION_MODE_DENIED')
    expected = pins(commit=commit, manifest_sha256=manifest_sha256,
                    installed_sha256=installed_sha256, payloads=payloads)
    # This validates an offline LAB token, not installation authority.
    proof = approval.verify(token, lab_key, expected=expected)
    require(proof.get('status') == 'VALID_LOCAL_PROOF_NOT_CONSUMED'
            and proof.get('activation_authorized') is False, 'PROOF_DENIED')
    _consume_lab_nonce(root, proof['nonce'])
    tx = transaction.LifecycleLabTransaction(root)
    tx.prepare(payloads, installed_sha256)
    try:
        tx.apply(payloads, fail_at=fail_at)
        if simulated_health == 'pass':
            result = tx.mark_lab_verified()
            return {'status': 'LAB_SIMULATED_HEALTH_PASS_BYTES_VERIFIED',
                    'transaction': result['status'],
                    'real_health_verified': False, 'local_activation_authorized': False,
                    'production_modified': False, 'mcp_modified': False,
                    'tunnel_restarted': False}
        # Both simulated health fail and error cases go through recovery.
        tx.recover()
        return {'status': 'LAB_SIMULATED_HEALTH_' +
                simulated_health.upper() + '_ROLLED_BACK',
                'real_health_verified': False, 'local_activation_authorized': False,
                'production_modified': False, 'mcp_modified': False,
                'tunnel_restarted': False}
    except BaseException:
        # A truly unexpected concurrent change must NOT be overwritten.
        # If recover() itself fails, propagate that instead of false success.
        tx.recover()
        raise
