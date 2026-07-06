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
from typing import Literal, cast

from ethernity.cli.shared.ui.runtime import clear_screen
from ethernity.cli.shared.ui_api import (
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
from ethernity.config import (
    DEFAULT_TEMPLATE_STYLE,
    ONBOARDING_FIELD_BACKUP_OUTPUT_DIR,
    ONBOARDING_FIELD_PAGE_SIZE,
    ONBOARDING_FIELD_PAYLOAD_CODEC,
    ONBOARDING_FIELD_QR_CHUNK_SIZE,
    ONBOARDING_FIELD_QR_ERROR_CORRECTION,
    ONBOARDING_FIELD_QR_PAYLOAD_CODEC,
    ONBOARDING_FIELD_SHARDING,
    ONBOARDING_FIELD_TEMPLATE_DESIGN,
    apply_first_run_defaults,
    first_run_onboarding_needed,
    list_template_designs,
    mark_first_run_onboarding_complete,
    resolve_config_path,
)

PayloadCodec = Literal["auto", "raw", "gzip"]
QrPayloadCodec = Literal["raw", "base64"]
QrErrorCorrection = Literal["L", "M", "Q", "H"]
PageSize = Literal["A4", "LETTER"]
SigningKeyMode = Literal["embedded", "sharded"]
FirstRunLaunchAction = Literal["backup", "recover"]
FirstRunEntryChoice = Literal["backup", "recover", "configure", "skip"]

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
    ONBOARDING_FIELD_SHARDING,
}
_FIRST_RUN_ADVANCED_CONFIGURED_FIELDS = {
    ONBOARDING_FIELD_QR_CHUNK_SIZE,
    ONBOARDING_FIELD_QR_ERROR_CORRECTION,
    ONBOARDING_FIELD_PAYLOAD_CODEC,
    ONBOARDING_FIELD_QR_PAYLOAD_CODEC,
}
_DEFAULT_QR_PAYLOAD_CODEC: QrPayloadCodec = "raw"
_DEFAULT_QR_ERROR_CORRECTION: QrErrorCorrection = "M"
_DEFAULT_PAYLOAD_CODEC: PayloadCodec = "auto"
_DEFAULT_QR_CHUNK_SIZE = 768


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
    qr_error_correction: QrErrorCorrection
    payload_codec: PayloadCodec
    page_size: PageSize
    backup_output_dir: str | None
    qr_chunk_size: int
    shard_threshold: int | None
    shard_count: int | None
    signing_key_mode: SigningKeyMode | None
    advanced_defaults_configured: bool = False


@dataclass(frozen=True)
class FirstRunOnboardingResult:
    applied_defaults: bool
    launch_action: FirstRunLaunchAction | None = None


def run_first_run_config_wizard(
    *,
    config_path: str | None,
    quiet: bool,
    force: bool = False,
) -> FirstRunOnboardingResult:
    """Run first-run onboarding and return any direct-launch action."""

    if not force and not first_run_onboarding_needed():
        return FirstRunOnboardingResult(applied_defaults=False)

    if not quiet:
        clear_screen()

    if force:
        return _run_defaults_setup_wizard(config_path=config_path, quiet=quiet)

    with wizard_flow(name="Get started", total_steps=1, quiet=quiet):
        with wizard_stage("Welcome"):
            entry_choice = _prompt_first_run_entry_choice(quiet=quiet)

    if entry_choice == "configure":
        return _run_defaults_setup_wizard(config_path=config_path, quiet=quiet)

    mark_first_run_onboarding_complete()
    if entry_choice in {"backup", "recover"}:
        if not quiet:
            console.print(
                "[dim]You can save backup defaults later with `ethernity config --onboard`.[/dim]"
            )
        return FirstRunOnboardingResult(
            applied_defaults=False,
            launch_action=cast(FirstRunLaunchAction, entry_choice),
        )

    if not quiet:
        console.print("[dim]Keeping current config defaults unchanged.[/dim]")
    return FirstRunOnboardingResult(applied_defaults=False)


def _prompt_first_run_entry_choice(*, quiet: bool) -> FirstRunEntryChoice:
    if not quiet:
        render_home_banner()
        console.print("[title]Welcome[/title]")
        console.print(
            "[subtitle]Start with the job you need now. "
            "You can save backup defaults in about a minute.[/subtitle]"
        )
    selected = prompt_choice(
        "What are you trying to do today?",
        {
            "backup": "Create a backup",
            "recover": "Recover from a backup",
            "configure": "Save backup defaults first",
            "skip": "Skip setup for now",
        },
        default="backup",
        help_text=(
            "Start a guided task now, or save default backup settings first. You can come back "
            "later with `ethernity config --onboard`."
        ),
    )
    return cast(FirstRunEntryChoice, selected)


def _run_defaults_setup_wizard(
    *,
    config_path: str | None,
    quiet: bool,
) -> FirstRunOnboardingResult:
    with wizard_flow(name="Default setup", total_steps=2, quiet=quiet):
        with wizard_stage("Essentials"):
            if not quiet:
                console.print("[title]Backup defaults[/title]")
                console.print(
                    "[subtitle]These choices cover most first backups. "
                    "Change QR settings only if you know you need something different.[/subtitle]"
                )
            selections = FirstRunSelections(
                design=_prompt_design(),
                qr_payload_codec=_DEFAULT_QR_PAYLOAD_CODEC,
                qr_error_correction=_DEFAULT_QR_ERROR_CORRECTION,
                payload_codec=_DEFAULT_PAYLOAD_CODEC,
                page_size=_prompt_page_size(),
                backup_output_dir=_prompt_backup_output_dir(),
                qr_chunk_size=_DEFAULT_QR_CHUNK_SIZE,
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
                qr_error_correction=selections.qr_error_correction,
                payload_codec=selections.payload_codec,
                page_size=selections.page_size,
                backup_output_dir=selections.backup_output_dir,
                qr_chunk_size=selections.qr_chunk_size,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_mode=signing_key_mode,
            )
            if prompt_yes_no(
                "Change QR and compression settings",
                default=False,
                help_text=(
                    "Leave this off to use the recommended settings: raw QR text, M error "
                    "correction, auto compression, and 768 bytes per QR code."
                ),
            ):
                selections = FirstRunSelections(
                    design=selections.design,
                    qr_payload_codec=_prompt_qr_payload_codec(),
                    qr_error_correction=_prompt_qr_error_correction(),
                    payload_codec=_prompt_payload_codec(),
                    page_size=selections.page_size,
                    backup_output_dir=selections.backup_output_dir,
                    qr_chunk_size=_prompt_qr_chunk_size(),
                    shard_threshold=selections.shard_threshold,
                    shard_count=selections.shard_count,
                    signing_key_mode=selections.signing_key_mode,
                    advanced_defaults_configured=True,
                )

        with wizard_stage("Review"):
            review_rows = [
                ("Config file", str(resolve_config_path(config_path))),
                ("Template design", selections.design),
                ("Paper size", selections.page_size),
                (
                    "Default backup folder",
                    selections.backup_output_dir or "unset (default backup-<doc_id>)",
                ),
                (
                    "QR and compression settings",
                    ("customized" if selections.advanced_defaults_configured else "recommended"),
                ),
                (
                    "Passphrase recovery method",
                    (
                        f"{selections.shard_threshold} of {selections.shard_count}"
                        if selections.shard_threshold is not None
                        and selections.shard_count is not None
                        else "disabled"
                    ),
                ),
                (
                    "Signing key storage",
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
                ("Used for", "default backup and recovery runs"),
            ]
            if selections.advanced_defaults_configured:
                review_rows[4:4] = [
                    ("QR text format", selections.qr_payload_codec),
                    ("QR error correction", selections.qr_error_correction),
                    ("Backup compression", selections.payload_codec),
                    ("QR data size", f"{selections.qr_chunk_size} bytes"),
                ]
            console.print(panel("Saved defaults", build_review_table(review_rows)))
            apply_defaults = prompt_yes_no(
                "Save these defaults",
                default=True,
                help_text=(
                    "Select no to keep your current settings. You can rerun with "
                    "`ethernity config --onboard`."
                ),
            )

    if apply_defaults:
        path = apply_first_run_defaults(
            config_path,
            design=selections.design,
            payload_codec=selections.payload_codec,
            qr_payload_codec=selections.qr_payload_codec,
            qr_error_correction=selections.qr_error_correction,
            page_size=selections.page_size,
            backup_output_dir=selections.backup_output_dir,
            qr_chunk_size=selections.qr_chunk_size,
            shard_threshold=selections.shard_threshold,
            shard_count=selections.shard_count,
            signing_key_mode=selections.signing_key_mode,
        )
        if not quiet:
            console.print(f"[success]Defaults saved to {path}[/success]")
        mark_first_run_onboarding_complete(configured_fields=_configured_fields_for(selections))
        return FirstRunOnboardingResult(applied_defaults=True)

    if not quiet:
        console.print("[dim]No defaults were saved.[/dim]")
    mark_first_run_onboarding_complete()
    return FirstRunOnboardingResult(applied_defaults=False)


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
        "Default print design",
        choices,
        default=default,
        help_text=(
            "Used for new backup, recovery, and shard documents. "
            "You can still override it with --design."
        ),
    )


def _prompt_qr_payload_codec() -> QrPayloadCodec:
    choices = {
        "raw": "raw (recommended, smaller QR payloads)",
        "base64": "base64 (ASCII-safe text payloads, larger)",
    }
    selected = prompt_choice(
        "QR text format",
        choices,
        default=_DEFAULT_QR_PAYLOAD_CODEC,
        help_text=("Leave this on raw unless another tool needs base64 text."),
    )
    return "base64" if selected == "base64" else "raw"


def _prompt_qr_error_correction() -> QrErrorCorrection:
    choices = {
        "M": "M (recommended, balanced capacity and resilience)",
        "L": "L (highest capacity, least resilience)",
        "Q": "Q (higher resilience, fewer QR bytes)",
        "H": "H (maximum resilience, fewest QR bytes)",
    }
    selected = prompt_choice(
        "QR error correction",
        choices,
        default=_DEFAULT_QR_ERROR_CORRECTION,
        help_text=(
            "Higher levels survive more print/scan damage but fit less data per QR code. "
            "M is a good default for most backups."
        ),
    )
    if selected in {"L", "M", "Q", "H"}:
        return cast(QrErrorCorrection, selected)
    return "M"


def _prompt_payload_codec() -> PayloadCodec:
    choices = {
        "auto": "auto (recommended, compress when helpful)",
        "gzip": "gzip (always compress, more CPU)",
        "raw": "raw (never compress, fastest)",
    }
    selected = prompt_choice(
        "Backup compression",
        choices,
        default=_DEFAULT_PAYLOAD_CODEC,
        help_text=(
            "Controls whether the backup is compressed before encryption. "
            "auto usually gives the best size and speed balance."
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
        "Paper size",
        choices,
        default="A4",
        help_text="Used for PDF rendering defaults. You can still override with --paper.",
    )
    return "LETTER" if selected == "LETTER" else "A4"


def _prompt_backup_output_dir() -> str | None:
    return prompt_optional(
        "Default backup folder (optional)",
        help_text=("Leave empty to create a new backup-<doc_id> folder in the current directory."),
    )


def _prompt_qr_chunk_size() -> int:
    preset = prompt_choice(
        "QR data size",
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
        default=str(_DEFAULT_QR_CHUNK_SIZE),
        help_text=(
            "Smaller sizes create more QR codes, but they are easier to scan on lower-quality "
            "printers and cameras."
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
        "Passphrase recovery method",
        {
            "none": "Keep one recovery passphrase",
            "2of3": "Split into 3 recovery shards, need any 2 (recommended)",
            "custom": "Custom threshold/count",
        },
        default="2of3",
        help_text=(
            "This splits the recovery passphrase across multiple documents. "
            "In the recommended setup, any 2 of 3 can recover the backup."
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
        "If you split the passphrase, where should the signing key go?",
        {
            "embedded": "Embedded in main document (recommended)",
            "sharded": "Sharded using the same threshold/count",
        },
        default="embedded",
        help_text=(
            "Embedded keeps the number of printed documents lower. "
            "Sharded signing keys require extra shard documents for future verification and "
            "recovery metadata."
        ),
    )
    signing_mode: SigningKeyMode = "sharded" if signing_choice == "sharded" else "embedded"
    return threshold, count, signing_mode


def _configured_fields_for(selections: FirstRunSelections) -> set[str]:
    configured = set(_FIRST_RUN_CONFIGURED_FIELDS)
    if selections.advanced_defaults_configured:
        configured.update(_FIRST_RUN_ADVANCED_CONFIGURED_FIELDS)
    return configured
