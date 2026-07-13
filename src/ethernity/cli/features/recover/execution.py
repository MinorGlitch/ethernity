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

import sys
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console

from ethernity.cli.features.recover.planning import RecoveryPlan
from ethernity.cli.shared.events import CommandError
from ethernity.cli.shared.io import outputs
from ethernity.cli.shared.ui.runtime import plain_status
from ethernity.cli.shared.ui.state import isatty
from ethernity.crypto import decrypt_bytes
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    recover_chain_entries,
    validate_expected_recovery_head,
    validate_root_manifest_authority,
)
from ethernity.formats.envelope_codec import decode_envelope, extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile

_CONSOLE = Console(force_terminal=isatty(sys.__stdout__, sys.stdout))
_CONSOLE_ERR = Console(stderr=True, force_terminal=isatty(sys.__stderr__, sys.stderr))


def format_auth_status(status_value: str, *, allow_unsigned: bool) -> str:
    if status_value == "verified":
        return "verified"
    if status_value == "skipped":
        return "skipped (unsigned recovery)"
    if status_value == "ignored":
        return "failed (ignored during unsigned recovery)"
    if status_value == "invalid":
        return "invalid (ignored during unsigned recovery)" if allow_unsigned else "invalid"
    if status_value == "missing":
        return "skipped (unsigned recovery)" if allow_unsigned else "missing"
    return status_value


def print_recover_summary(
    entries: list[tuple[ManifestFile, bytes]],
    output_path: str | None,
    *,
    auth_status: str | None,
    quiet: bool,
    **_: object,
) -> None:
    if quiet:
        return
    count = len(entries)
    suffix = "file" if count == 1 else "files"
    target = output_path or "stdout"
    if auth_status:
        _CONSOLE_ERR.print(f"Recovered {count} {suffix} to {target}. Auth: {auth_status}.")
        return
    _CONSOLE_ERR.print(f"Recovered {count} {suffix} to {target}.")


def print_completion_panel(
    title: str,
    actions: list[str],
    *,
    quiet: bool,
    use_err: bool = False,
) -> None:
    if quiet:
        return
    console = _CONSOLE_ERR if use_err else _CONSOLE
    console.print(title)
    for action in actions:
        console.print(f"- {action}")


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

    try:
        if plan.import_documents:
            chain = recover_chain_entries(plan, quiet=quiet, debug=debug)
            return RecoverDecryptResult(
                manifest=chain.manifest,
                extracted=list(chain.extracted),
                selected_extension_index=chain.selected_extension_index,
                selected_extension_doc_hash=chain.selected_extension_doc_hash,
            )

        with plain_status(
            "Decrypting and unpacking payload...",
            quiet=quiet,
            console=_CONSOLE,
        ):
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
    except ExtensionRecoveryError as exc:
        raise CommandError(code=exc.code, message=str(exc), details=dict(exc.details)) from exc


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

    written_paths = outputs.write_recovered_outputs(
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
