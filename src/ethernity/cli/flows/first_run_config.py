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
    ONBOARDING_FIELD_BACKUP_OUTPUT_DIR,
    ONBOARDING_FIELD_PAGE_SIZE,
    ONBOARDING_FIELD_PAYLOAD_CODEC,
    ONBOARDING_FIELD_QR_CHUNK_SIZE,
    ONBOARDING_FIELD_QR_PAYLOAD_CODEC,
    ONBOARDING_FIELD_SHARDING,
    ONBOARDING_FIELD_TEMPLATE_DESIGN,
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
    prompt_int,
    prompt_optional,
    prompt_yes_no,
    render_home_banner,
    wizard_flow,
    wizard_stage,
)
from ..ui.runtime import clear_screen

PayloadCodec = Literal["auto", "raw", "gzip"]
QrPayloadCodec = Literal["raw", "base64"]
PageSize = Literal["A4", "LETTER"]
SigningKeyMode = Literal["embedded", "sharded"]

_DESIGN_DESCRIPTIONS = {
    "archive": "clean archival look",
    "forge": "high-contrast technical",
    "ledger": "structured record style",
    "maritime": "compact navigation style",
    "sentinel": "balanced default look",
}

_FIRST_RUN_CONFIGURED_FIELDS = {
    ONBOARDING_FIELD_TEMPLATE_DESIGN,
    ONBOARDING_FIELD_PAGE_SIZE,
    ONBOARDING_FIELD_BACKUP_OUTPUT_DIR,
    ONBOARDING_FIELD_QR_CHUNK_SIZE,
    ONBOARDING_FIELD_SHARDING,
    ONBOARDING_FIELD_PAYLOAD_CODEC,
    ONBOARDING_FIELD_QR_PAYLOAD_CODEC,
}


def _preferred_design_order(names: list[str]) -> list[str]:
    """Return design names with sentinel first, then alphabetical."""

    sentinel_first = sorted(
        names,
        key=lambda name: (0 if name.lower() == "sentinel" else 1, name.lower()),
    )
    return sentinel_first


@dataclass(frozen=True)
class FirstRunSelections:
    design: str
    qr_payload_codec: QrPayloadCodec
    payload_codec: PayloadCodec
    page_size: PageSize
    backup_output_dir: str | None
    qr_chunk_size: int
    shard_threshold: int | None
    shard_count: int | None
    signing_key_mode: SigningKeyMode | None


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

    if not quiet:
        clear_screen()

    with wizard_flow(name="First run setup", total_steps=2, quiet=quiet):
        with wizard_stage("Welcome"):
            if not quiet:
                render_home_banner()
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
                    console.print("[dim]Keeping current config defaults unchanged.[/dim]")
                return False

            selections = FirstRunSelections(
                design=_prompt_design(),
                qr_payload_codec=_prompt_qr_payload_codec(),
                payload_codec=_prompt_payload_codec(),
                page_size=_prompt_page_size(),
                backup_output_dir=_prompt_backup_output_dir(),
                qr_chunk_size=_prompt_qr_chunk_size(),
                shard_threshold=None,
                shard_count=None,
                signing_key_mode=None,
            )
            (
                shard_threshold,
                shard_count,
                signing_key_mode,
            ) = _prompt_sharding_defaults()
            selections = FirstRunSelections(
                design=selections.design,
                qr_payload_codec=selections.qr_payload_codec,
                payload_codec=selections.payload_codec,
                page_size=selections.page_size,
                backup_output_dir=selections.backup_output_dir,
                qr_chunk_size=selections.qr_chunk_size,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_mode=signing_key_mode,
            )

        with wizard_stage("Review"):
            review_rows = [
                ("Config file", str(resolve_config_path(config_path))),
                ("Template design", selections.design),
                ("Paper size", selections.page_size),
                (
                    "Backup output dir",
                    selections.backup_output_dir or "unset (default backup-<doc_id>)",
                ),
                ("QR payload codec", selections.qr_payload_codec),
                ("Payload codec", selections.payload_codec),
                ("QR chunk size", f"{selections.qr_chunk_size} bytes"),
                (
                    "Passphrase sharding",
                    (
                        f"{selections.shard_threshold} of {selections.shard_count}"
                        if selections.shard_threshold is not None
                        and selections.shard_count is not None
                        else "disabled"
                    ),
                ),
                (
                    "Signing key handling",
                    (
                        "same sharding as passphrase"
                        if selections.signing_key_mode == "sharded"
                        else (
                            "embedded in main document"
                            if selections.signing_key_mode == "embedded"
                            else "not applicable"
                        )
                    ),
                ),
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
            page_size=selections.page_size,
            backup_output_dir=selections.backup_output_dir,
            qr_chunk_size=selections.qr_chunk_size,
            shard_threshold=selections.shard_threshold,
            shard_count=selections.shard_count,
            signing_key_mode=selections.signing_key_mode,
        )
        if not quiet:
            console.print(f"[success]Defaults saved to {path}[/success]")
        mark_first_run_onboarding_complete(configured_fields=_FIRST_RUN_CONFIGURED_FIELDS)
    else:
        if not quiet:
            console.print("[dim]No changes written.[/dim]")
        mark_first_run_onboarding_complete()
    return apply_defaults


def _prompt_design() -> str:
    designs = list_template_designs()
    if not designs:
        raise ValueError("no template designs available")
    names = _preferred_design_order(list(designs.keys()))
    default = DEFAULT_TEMPLATE_STYLE if DEFAULT_TEMPLATE_STYLE in designs else names[0]
    choices = {
        name: (
            f"{name} ({_DESIGN_DESCRIPTIONS.get(name, 'template design')}, recommended)"
            if name.lower() == "sentinel"
            else f"{name} ({_DESIGN_DESCRIPTIONS.get(name, 'template design')})"
        )
        for name in names
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


def _prompt_page_size() -> PageSize:
    choices = {
        "A4": "A4 (recommended for most regions)",
        "LETTER": "Letter (US/Canada)",
    }
    selected = prompt_choice(
        "Default paper size",
        choices,
        default="A4",
        help_text="Used for PDF rendering defaults. You can still override with --paper.",
    )
    return "LETTER" if selected == "LETTER" else "A4"


def _prompt_backup_output_dir() -> str | None:
    return prompt_optional(
        "Default backup output directory (optional)",
        help_text=(
            "Leave empty to use the current behavior (creates backup-<doc_id> in your current "
            "directory)."
        ),
    )


def _prompt_qr_chunk_size() -> int:
    preset = prompt_choice(
        "Preferred QR chunk size",
        {
            "768": "768 bytes (recommended default)",
            "256": "256 bytes (highest scan margin)",
            "384": "384 bytes (more scan margin)",
            "512": "512 bytes (balanced scan margin)",
            "1024": "1024 bytes (fewer QR codes)",
            "1536": "1536 bytes (fewer QR codes, less scan margin)",
            "2048": "2048 bytes (fewest QR codes, least scan margin)",
            "custom": "Custom value",
        },
        default="768",
        help_text=(
            "Smaller chunk sizes create more QR codes but are easier to scan on lower quality "
            "devices."
        ),
    )
    if preset != "custom":
        return int(preset)
    return prompt_int(
        "Custom QR chunk size (bytes)",
        minimum=64,
        maximum=2048,
        help_text="Enter a value between 64 and 2048 bytes.",
    )


def _prompt_sharding_defaults() -> tuple[int | None, int | None, SigningKeyMode | None]:
    mode = prompt_choice(
        "Default passphrase sharding",
        {
            "none": "Disabled (single recovery passphrase)",
            "2of3": "2 of 3 shards (recommended)",
            "custom": "Custom threshold/count",
        },
        default="none",
        help_text=(
            "Sharding splits the recovery passphrase across multiple shard documents. "
            "Any threshold number of shards can recover the passphrase."
        ),
    )
    if mode == "none":
        return None, None, None

    if mode == "2of3":
        threshold = 2
        count = 3
    else:
        threshold = prompt_int(
            "Shard threshold",
            minimum=1,
            maximum=255,
            help_text="Minimum shards required to recover the passphrase (1-255).",
        )
        count = prompt_int(
            "Shard count",
            minimum=threshold,
            maximum=255,
            help_text="Total shard documents to create (must be >= threshold).",
        )

    signing_choice = prompt_choice(
        "When sharding is enabled, how should the signing key be stored?",
        {
            "embedded": "Embedded in main document (recommended)",
            "sharded": "Sharded using the same threshold/count",
        },
        default="embedded",
        help_text=(
            "Embedded keeps fewer documents. Sharded signing keys require shard documents for "
            "signature verification and recovery metadata."
        ),
    )
    signing_mode: SigningKeyMode = "sharded" if signing_choice == "sharded" else "embedded"
    return threshold, count, signing_mode
