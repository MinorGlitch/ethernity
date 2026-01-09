#!/usr/bin/env python3
from __future__ import annotations

from ...crypto import decrypt_bytes
from ...formats.envelope_codec import decode_envelope, extract_payloads
from ...formats.envelope_types import ManifestFile
from ..api import print_completion_panel, status
from ..io.outputs import _write_recovered_outputs
from ..ui.summary import format_auth_status, print_recover_summary
from .recover_plan import RecoveryPlan


def decrypt_and_extract(
    plan: RecoveryPlan,
    *,
    quiet: bool,
) -> list[tuple[ManifestFile, bytes]]:
    with status("Decrypting and unpacking payload...", quiet=quiet):
        plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase)
        manifest, payload = decode_envelope(plaintext)
        extracted = extract_payloads(manifest, payload)
    return extracted


def write_recovered_outputs(
    extracted: list[tuple[ManifestFile, bytes]],
    *,
    output_path: str | None,
    auth_status: str,
    allow_unsigned: bool,
    quiet: bool,
) -> None:
    _write_recovered_outputs(output_path, extracted, quiet=quiet)
    auth_label = format_auth_status(auth_status, allow_unsigned=allow_unsigned)
    print_recover_summary(extracted, output_path, auth_status=auth_label, quiet=quiet)
    if not quiet:
        actions = ["Verify recovered files match your originals."]
        if output_path:
            actions.append("Store the recovered files somewhere secure.")
        else:
            actions.append("Save stdout output if you need to keep the recovered data.")
        print_completion_panel("Recovery complete", actions, quiet=quiet, use_err=True)


def run_recover_plan(plan: RecoveryPlan, *, quiet: bool) -> int:
    extracted = decrypt_and_extract(plan, quiet=quiet)
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
    )
    return 0
