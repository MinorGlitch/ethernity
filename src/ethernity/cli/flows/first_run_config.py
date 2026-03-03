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

from dataclasses import dataclass
from typing import Literal

from ...config import (
    DEFAULT_TEMPLATE_STYLE,
    apply_first_run_defaults,
    first_run_onboarding_needed,
    list_template_designs,
    mark_first_run_onboarding_complete,
    resolve_config_path,
)
from ..api import (
    build_review_table,
    console,
    panel,
    prompt_choice,
    prompt_yes_no,
    wizard_flow,
    wizard_stage,
)

PayloadCodec = Literal["auto", "raw", "gzip"]
QrPayloadCodec = Literal["raw", "base64"]

_DESIGN_DESCRIPTIONS = {
    "archive": "clean archival look",
    "forge": "high-contrast technical",
    "ledger": "structured record style",
    "maritime": "compact navigation style",
    "sentinel": "balanced default look",
}


@dataclass(frozen=True)
class FirstRunSelections:
    design: str
    qr_payload_codec: QrPayloadCodec
    payload_codec: PayloadCodec


def run_first_run_config_wizard(
    *,
    config_path: str | None,
    quiet: bool,
    force: bool = False,
) -> bool:
    """Prompt for first-run defaults and persist selections.

    Returns ``True`` when preferences are applied, otherwise ``False``.
    """

    if not force and not first_run_onboarding_needed():
        return False

    with wizard_flow(name="First run setup", total_steps=2, quiet=quiet):
        with wizard_stage("Welcome"):
            if not quiet:
                console.print("[title]Welcome to Ethernity[/title]")
                console.print(
                    "[subtitle]This one-time setup chooses default backup preferences.[/subtitle]"
                )
                console.print(
                    "[subtitle]Command flags still override these defaults "
                    "whenever needed.[/subtitle]"
                )
            should_configure = prompt_yes_no(
                "Configure defaults now",
                default=True,
                help_text=(
                    "Recommended. This takes about 30 seconds and you can rerun it later with "
                    "`ethernity config --onboard`."
                ),
            )
            if not should_configure:
                mark_first_run_onboarding_complete()
                if not quiet:
                    console.print(
                        "[dim]Keeping current defaults (template: sentinel, QR codec: raw, "
                        "payload codec: auto).[/dim]"
                    )
                return False

            selections = FirstRunSelections(
                design=_prompt_design(),
                qr_payload_codec=_prompt_qr_payload_codec(),
                payload_codec=_prompt_payload_codec(),
            )

        with wizard_stage("Review"):
            review_rows = [
                ("Config file", str(resolve_config_path(config_path))),
                ("Template design", selections.design),
                ("QR payload codec", selections.qr_payload_codec),
                ("Payload codec", selections.payload_codec),
                ("Applies to", "default backup/recovery runs"),
            ]
            console.print(panel("First-run defaults", build_review_table(review_rows)))
            apply_defaults = prompt_yes_no(
                "Apply these defaults",
                default=True,
                help_text=(
                    "Select no to keep current config unchanged. You can rerun with "
                    "`ethernity config --onboard`."
                ),
            )

    if apply_defaults:
        path = apply_first_run_defaults(
            config_path,
            design=selections.design,
            payload_codec=selections.payload_codec,
            qr_payload_codec=selections.qr_payload_codec,
        )
        if not quiet:
            console.print(f"[success]Defaults saved to {path}[/success]")
    else:
        if not quiet:
            console.print("[dim]No changes written.[/dim]")
    mark_first_run_onboarding_complete()
    return apply_defaults


def _prompt_design() -> str:
    designs = list_template_designs()
    if not designs:
        raise ValueError("no template designs available")
    names = sorted(designs.keys(), key=lambda name: name.lower())
    default = DEFAULT_TEMPLATE_STYLE if DEFAULT_TEMPLATE_STYLE in designs else names[0]
    choices = {
        name: f"{name} ({_DESIGN_DESCRIPTIONS.get(name, 'template design')})" for name in names
    }
    return prompt_choice(
        "Default template design",
        choices,
        default=default,
        help_text=(
            "Used for backup, recovery, shard, signing-key shard, and kit templates. "
            "You can still override per command using --design."
        ),
    )


def _prompt_qr_payload_codec() -> QrPayloadCodec:
    choices = {
        "raw": "raw (recommended, smaller QR payloads)",
        "base64": "base64 (ASCII-safe text payloads, larger)",
    }
    selected = prompt_choice(
        "QR payload codec",
        choices,
        default="raw",
        help_text=(
            "Choose how QR bytes are represented. raw is usually denser; base64 is useful for "
            "strict text-only toolchains."
        ),
    )
    return "base64" if selected == "base64" else "raw"


def _prompt_payload_codec() -> PayloadCodec:
    choices = {
        "auto": "auto (recommended, compress when helpful)",
        "gzip": "gzip (always compress, more CPU)",
        "raw": "raw (never compress, fastest)",
    }
    selected = prompt_choice(
        "Backup payload codec",
        choices,
        default="auto",
        help_text=(
            "Controls pre-encryption payload encoding. auto usually gives the best size/speed "
            "balance."
        ),
    )
    if selected == "gzip":
        return "gzip"
    if selected == "raw":
        return "raw"
    return "auto"
