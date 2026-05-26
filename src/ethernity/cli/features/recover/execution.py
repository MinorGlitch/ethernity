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

from collections.abc import Callable
from dataclasses import dataclass

from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared.io.outputs import (
    _single_entry_uses_directory_output,
    _write_recovered_outputs,
)
from ethernity.cli.shared.ui.debug import print_recover_debug
from ethernity.cli.shared.ui.summary import format_auth_status, print_recover_summary
from ethernity.cli.shared.ui_api import print_completion_panel, status
from ethernity.crypto import decrypt_bytes
from ethernity.extensions.recovery import (
    recover_chain_entries,
    validate_expected_recovery_head,
    validate_root_manifest_authority,
)
from ethernity.formats.envelope_codec import decode_envelope, extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


@dataclass(frozen=True)
class RecoverDecryptResult:
    manifest: EnvelopeManifest
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

    if plan.import_documents:
        chain = recover_chain_entries(plan, quiet=quiet, debug=debug)
        return RecoverDecryptResult(
            manifest=chain.manifest,
            extracted=list(chain.extracted),
            selected_extension_index=chain.selected_extension_index,
            selected_extension_doc_hash=chain.selected_extension_doc_hash,
        )

    with status("Decrypting and unpacking payload...", quiet=quiet):
        plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
        manifest, payload = decode_envelope(plaintext)
        extracted = extract_payloads(manifest, payload)
    validate_root_manifest_authority(manifest, plan.auth_payload, doc_hash=plan.doc_hash)
    validate_expected_recovery_head(
        plan,
        selected_extension_index=None,
        selected_extension_doc_hash=None,
    )
    return RecoverDecryptResult(manifest=manifest, extracted=extracted)


def decrypt_manifest_and_extract(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
) -> tuple[EnvelopeManifest, list[tuple[ManifestFile, bytes]]]:
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


def write_recovered_outputs(
    extracted: list[tuple[ManifestFile, bytes]],
    *,
    output_path: str | None,
    auth_status: str,
    allow_unsigned: bool,
    quiet: bool,
    single_entry_output_is_directory: bool = False,
    requested_extension_index: int | None = None,
    requested_extension_doc_hash: str | None = None,
    expected_head_doc_hash: str | None = None,
    selected_extension_index: int | None = None,
    selected_extension_doc_hash: str | None = None,
    on_file_written: Callable[[object, bytes, str, int, int], None] | None = None,
) -> list[str]:
    """Write recovered outputs and print the post-recovery summary."""

    written_paths = _write_recovered_outputs(
        output_path,
        extracted,
        single_entry_output_is_directory=single_entry_output_is_directory,
        on_entry_written=on_file_written,
    )
    auth_label = format_auth_status(auth_status, allow_unsigned=allow_unsigned)
    print_recover_summary(
        extracted,
        output_path,
        auth_status=auth_label,
        quiet=quiet,
        single_entry_output_is_directory=single_entry_output_is_directory,
        requested_extension_index=requested_extension_index,
        requested_extension_doc_hash=requested_extension_doc_hash,
        expected_head_doc_hash=expected_head_doc_hash,
        selected_extension_index=selected_extension_index,
        selected_extension_doc_hash=selected_extension_doc_hash,
    )
    if not quiet:
        actions = [f"Saved to {output_path}" if output_path else "Wrote recovered data to stdout."]
        actions.append("Verify recovered files match your originals.")
        if output_path:
            actions.append("Store the recovered files somewhere secure.")
        else:
            actions.append("Save stdout output if you need to keep the recovered data.")
        print_completion_panel("Recovery complete", actions, quiet=quiet, use_err=True)
    return written_paths


def run_recover_plan(
    plan: RecoveryPlan,
    *,
    quiet: bool,
    debug: bool = False,
    debug_max_bytes: int = 0,
    debug_reveal_secrets: bool = False,
) -> int:
    """Execute a prepared recovery plan end to end."""
    decrypted = decrypt_manifest_extract_selection(plan, quiet=quiet, debug=debug)
    manifest = decrypted.manifest
    extracted = decrypted.extracted
    if debug:
        print_recover_debug(
            manifest=manifest,
            extracted=extracted,
            ciphertext=plan.ciphertext,
            passphrase=plan.passphrase,
            auth_status=plan.auth_status,
            allow_unsigned=plan.allow_unsigned,
            output_path=plan.output_path,
            debug_max_bytes=debug_max_bytes,
            reveal_secrets=debug_reveal_secrets,
        )
    single_entry_output_is_directory = (
        plan.output_path is not None
        and len(extracted) == 1
        and manifest.input_origin in {"directory", "mixed"}
    )
    single_entry_output_is_directory = _single_entry_uses_directory_output(
        plan.output_path,
        single_entry_output_is_directory=single_entry_output_is_directory,
    )
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
        single_entry_output_is_directory=single_entry_output_is_directory,
        requested_extension_index=getattr(plan, "extension_index", None),
        requested_extension_doc_hash=getattr(plan, "extension_doc_hash", None),
        expected_head_doc_hash=getattr(plan, "expected_head_doc_hash", None),
        selected_extension_index=decrypted.selected_extension_index,
        selected_extension_doc_hash=decrypted.selected_extension_doc_hash,
    )
    return 0
