#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Recover decrypted manifests and write extracted files."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.crypto import decrypt_bytes
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    recover_chain_entries,
    validate_expected_recovery_head,
    validate_root_signing_key_binding,
)
from ethernity.formats.document_codec import decode_backup_document, extract_payloads
from ethernity.formats.manifest import BackupManifest, ManifestFile
from ethernity.workflows.recovery.planning import RecoveryPlan
from ethernity.workflows.shared.events import CommandError


@dataclass(frozen=True)
class RecoverDecryptResult:
    manifest: BackupManifest
    extracted: list[tuple[ManifestFile, bytes]]
    selected_extension_index: int | None = None
    selected_extension_doc_hash: str | None = None


def decrypt_manifest_extract_selection(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
) -> RecoverDecryptResult:
    """Decrypt a recovery plan and preserve any explicit replay-target metadata."""

    try:
        if plan.import_documents:
            chain = recover_chain_entries(plan, debug=debug)
            return RecoverDecryptResult(
                manifest=chain.manifest,
                extracted=list(chain.extracted),
                selected_extension_index=chain.selected_extension_index,
                selected_extension_doc_hash=chain.selected_extension_doc_hash,
            )

        plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
        manifest, payload = decode_backup_document(plaintext)
        extracted = extract_payloads(manifest, payload)
        validate_root_signing_key_binding(manifest, plan.auth_payload, doc_hash=plan.doc_hash)
        validate_expected_recovery_head(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return RecoverDecryptResult(manifest=manifest, extracted=extracted)
    except ExtensionRecoveryError as exc:
        raise CommandError(code=exc.code, message=str(exc), details=dict(exc.details)) from exc


def decrypt_manifest_and_extract(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
) -> tuple[BackupManifest, list[tuple[ManifestFile, bytes]]]:
    """Decrypt a recovery plan ciphertext and extract manifest payload entries."""

    result = decrypt_manifest_extract_selection(plan, quiet=quiet, debug=debug)
    return result.manifest, result.extracted


def decrypt_and_extract(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
) -> list[tuple[ManifestFile, bytes]]:
    """Decrypt and extract payload entries, discarding the parsed manifest."""

    _manifest, extracted = decrypt_manifest_and_extract(plan, quiet=quiet, debug=debug)
    return extracted
