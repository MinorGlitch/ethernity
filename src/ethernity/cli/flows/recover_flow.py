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
    debug: bool = False,
) -> list[tuple[ManifestFile, bytes]]:
    with status("Decrypting and unpacking payload...", quiet=quiet):
        plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
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
        actions = [f"Saved to {output_path}" if output_path else "Wrote recovered data to stdout."]
        actions.append("Verify recovered files match your originals.")
        if output_path:
            actions.append("Store the recovered files somewhere secure.")
        else:
            actions.append("Save stdout output if you need to keep the recovered data.")
        print_completion_panel("Recovery complete", actions, quiet=quiet, use_err=True)


def run_recover_plan(plan: RecoveryPlan, *, quiet: bool, debug: bool = False) -> int:
    extracted = decrypt_and_extract(plan, quiet=quiet, debug=debug)
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
    )
    return 0
