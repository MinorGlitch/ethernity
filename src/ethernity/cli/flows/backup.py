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

import os
from dataclasses import replace
from pathlib import Path

from ...config import (
    DEFAULT_PAPER_SIZE,
    DEFAULT_TEMPLATE_STYLE,
    AppConfig,
    apply_template_design,
    list_template_designs,
    load_app_config,
)
from ...config.installer import PACKAGE_ROOT
from ...core.models import DocumentPlan, ShardingConfig, SigningSeedMode
from ..api import (
    DEBUG_MAX_BYTES_DEFAULT,
    build_review_table,
    console,
    console_err,
    panel,
    print_completion_panel,
    progress,
    prompt_choice,
    prompt_optional,
    prompt_optional_secret,
    prompt_path_with_picker,
    prompt_paths_with_picker,
    prompt_yes_no,
    wizard_flow,
    wizard_stage,
)
from ..core.log import _warn
from ..core.plan import _validate_backup_args, _validate_passphrase_words
from ..core.types import BackupArgs, BackupResult, InputFile
from ..io.inputs import _load_input_files
from ..ui.summary import print_backup_summary
from .backup_flow import run_backup as _run_backup
from .backup_plan import build_document_plan, plan_from_args
from .backup_wizard import (
    prompt_passphrase_words,
    resolve_passphrase_sharding,
    resolve_signing_seed_mode,
    resolve_signing_seed_sharding,
)

_KIT_INDEX_TEMPLATE_MARKER = "kit_index_inventory_artifacts_v3"


def _format_backup_input_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "input file not found" in lowered or "input dir not found" in lowered:
        return f"{message} Check the path and try again."
    if "input paths are on different roots" in lowered:
        return (
            "Inputs are on different drives or roots. Provide --base-dir to set a common "
            "base folder."
        )
    if "no input files found" in lowered:
        return "No input files found. Select files or folders to back up."
    return message


def _prompt_encryption(
    args: BackupArgs | None,
) -> tuple[str | None, int | None]:
    """Prompt for encryption settings. Returns (passphrase, passphrase_words)."""
    passphrase = args.passphrase if args is not None else None
    passphrase_generate = args.passphrase_generate if args is not None else False
    passphrase_words = args.passphrase_words if args is not None else None

    if passphrase is not None:
        entered = prompt_optional_secret(
            "Enter passphrase",
            help_text="Leave blank to keep the passphrase provided via flags.",
        )
        if entered is not None:
            passphrase = entered
    else:
        help_text = "Leave blank to auto-generate a strong passphrase."
        if passphrase_generate:
            help_text = "Leave blank to auto-generate a strong passphrase (as requested)."
        passphrase = prompt_optional_secret("Enter passphrase", help_text=help_text)
        if passphrase is None:
            if passphrase_words is None:
                passphrase_words = prompt_passphrase_words()
            else:
                _validate_passphrase_words(passphrase_words)

    return passphrase, passphrase_words


def _prompt_recovery_options(
    args: BackupArgs | None,
    debug_override: bool | None,
    quiet: bool,
) -> tuple[
    bool,
    bool,
    SigningSeedMode,
    ShardingConfig | None,
    ShardingConfig | None,
]:
    """Prompt for recovery options.

    Returns (sealed, debug, signing_seed_mode, sharding, signing_seed_sharding).
    """
    sharding = resolve_passphrase_sharding(args=args)

    if sharding is None:
        sealed = bool(args.sealed) if args is not None else False
    elif args is not None and args.sealed:
        sealed = True
    else:
        sealed = prompt_yes_no(
            "Seal backup (disallow new shards)",
            default=False,
            help_text="Sealed backups prevent creating new shard docs later.",
        )

    if debug_override is None:
        debug = prompt_yes_no(
            "Show pre-encryption debug output",
            default=False,
            help_text="Includes plaintext details; use only for troubleshooting.",
        )
    else:
        debug = debug_override

    if sharding is not None:
        signing_seed_mode = resolve_signing_seed_mode(
            args=args,
            sealed=sealed,
            quiet=quiet,
        )
        signing_seed_sharding = resolve_signing_seed_sharding(
            args=args,
            signing_seed_mode=signing_seed_mode,
            passphrase_sharding=sharding,
        )
    else:
        signing_seed_mode = SigningSeedMode.EMBEDDED
        signing_seed_sharding = None

    return sealed, debug, signing_seed_mode, sharding, signing_seed_sharding


def _prompt_layout(
    config_path: str | None,
    paper_size: str | None,
) -> tuple[str | None, str | None]:
    """Prompt for layout settings. Returns (config_path, paper_size override)."""
    paper = paper_size
    if config_path is None and not paper:
        layout_choices = {
            "a4": "A4",
            "letter": "Letter",
            "custom": "Custom config file (TOML)",
        }
        layout_choice = prompt_choice(
            "Paper size",
            layout_choices,
            default=DEFAULT_PAPER_SIZE.lower(),
            help_text="Choose a paper size or select a custom TOML config.",
        )
        if layout_choice == "custom":
            config_path = prompt_path_with_picker(
                "Config file path",
                kind="file",
                help_text="Provide a TOML config file.",
                picker_prompt="Select a config file",
            )
        else:
            paper = layout_choice.upper()
    elif paper:
        paper = paper.upper()
    return config_path, paper


def _resolve_design_name(design: str | None, designs: dict[str, Path]) -> str | None:
    if not design:
        return None
    if design in designs:
        return design
    lowered = design.lower()
    for name in designs:
        if name.lower() == lowered:
            return name
    return None


def _prompt_design(args: BackupArgs | None) -> str | None:
    designs = list_template_designs()
    if not designs:
        return None
    requested = args.design if args is not None else None
    resolved = _resolve_design_name(requested, designs)
    if requested and resolved is None:
        console_err.print(f"[error]Unknown template design: {requested}[/error]")
    if resolved:
        return resolved
    design_names = sorted(designs.keys(), key=lambda name: name.lower())
    if len(design_names) == 1:
        return design_names[0]
    default = DEFAULT_TEMPLATE_STYLE if DEFAULT_TEMPLATE_STYLE in designs else design_names[0]
    choices = {name: name for name in design_names}
    return prompt_choice(
        "Template design",
        choices,
        default=default,
        help_text="Design folders are discovered from packaged templates (copied to user config).",
    )


def _prompt_inputs(
    args: BackupArgs | None,
    quiet: bool,
    debug: bool,
) -> tuple[list, Path | None, str | None]:
    """Prompt for input files. Returns (input_files, resolved_base, output_dir)."""
    while True:
        input_values = prompt_paths_with_picker(
            "Input paths (files or directories, blank to finish)",
            picker_prompt="Select files or folders",
            kind="path",
            manual_help_text="Enter file or directory paths; blank line to finish.",
            picker_help_text="Use space to toggle, Enter to confirm.",
            empty_message="At least one input path is required.",
            stdin_message="Stdin input is not supported in the wizard.",
        )
        base_dir = args.base_dir if args is not None else None
        output_dir = args.output_dir if args is not None else None
        if output_dir is None:
            output_dir = prompt_optional(
                "Output folder (press Enter for default)",
                help_text="Creates a backup-<id> folder in current directory.",
            )

        status_quiet = quiet or debug
        try:
            with progress(quiet=status_quiet) as progress_bar:
                input_files, resolved_base = _load_input_files(
                    input_values,
                    [],
                    base_dir,
                    allow_stdin=False,
                    progress=progress_bar,
                )
        except ValueError as exc:
            console_err.print(f"[error]{_format_backup_input_error(exc)}[/error]")
            continue
        break

    return input_files, resolved_base, output_dir


def _apply_qr_chunk_size_override(config: AppConfig, qr_chunk_size: int | None) -> AppConfig:
    if qr_chunk_size is None:
        return config
    return replace(config, qr_chunk_size=qr_chunk_size)


def _build_review_rows(
    passphrase: str | None,
    passphrase_words: int | None,
    plan: DocumentPlan,
    input_files: list[InputFile],
    resolved_base: Path | None,
    output_dir: str | None,
    config_path: str | None,
    paper: str | None,
    design: str | None,
    config: AppConfig,
    debug: bool,
) -> list[tuple[str, str | None]]:
    """Build the review table rows."""
    review_rows: list[tuple[str, str | None]] = []
    review_rows.append(("Keys", None))
    if passphrase:
        review_rows.append(("Passphrase", "provided"))
    else:
        review_rows.append(("Passphrase", "auto-generated"))
        if passphrase_words:
            review_rows.append(("Passphrase length", f"{passphrase_words} words"))

    plan_sharding = plan.sharding
    if plan_sharding is not None:
        review_rows.append(("Sharding", f"{plan_sharding.threshold} of {plan_sharding.shares}"))
        review_rows.append(("Shard documents", str(plan_sharding.shares)))
        if plan.sealed:
            signing_label = "not stored (sealed backup)"
        elif plan.signing_seed_mode == SigningSeedMode.EMBEDDED:
            signing_label = "embedded in main document"
        else:
            signing_label = "separate signing-key shard documents"
        review_rows.append(("Signing key handling", signing_label))
        if plan.signing_seed_mode == SigningSeedMode.SHARDED:
            if plan.signing_seed_sharding:
                signing_seed_sharding = plan.signing_seed_sharding
                review_rows.append(
                    (
                        "Signing-key shards",
                        f"{signing_seed_sharding.threshold} of {signing_seed_sharding.shares}",
                    )
                )
            else:
                review_rows.append(("Signing-key shards", "same as passphrase"))
    else:
        review_rows.append(("Sharding", "disabled"))
        review_rows.append(("Signing key handling", "not applicable"))

    review_rows.append(("Sealed", "yes" if plan.sealed else "no"))
    review_rows.append(("Inputs", None))
    review_rows.append(("Input files", f"{len(input_files)} file(s)"))
    if resolved_base:
        review_rows.append(("Base dir", str(resolved_base)))
    if config_path:
        review_rows.append(("Config", config_path))
    else:
        review_rows.append(("Config", "default"))
    review_rows.append(("Paper size", str(config.paper_size)))
    review_rows.append(("QR chunk size (preferred)", f"{config.qr_chunk_size} bytes"))
    if design:
        review_rows.append(("Template design", design))
    review_rows.append(("Output", None))
    if output_dir:
        review_rows.append(("Output dir", output_dir))
    else:
        review_rows.append(("Output dir", "default (backup-<doc_id>)"))
    review_rows.append(("Debug output", "enabled" if debug else "disabled"))
    review_rows.append(("QR template", str(config.template_path)))
    review_rows.append(("Recovery template", str(config.recovery_template_path)))
    kit_index_template = _resolve_kit_index_template_path(config)
    if kit_index_template.is_file():
        review_rows.append(("Recovery kit index template", str(kit_index_template)))
    if plan.sharding is not None:
        review_rows.append(("Shard template", str(config.shard_template_path)))
    if (
        plan.sharding is not None
        and not plan.sealed
        and plan.signing_seed_mode == SigningSeedMode.SHARDED
    ):
        review_rows.append(
            ("Signing-key shard template", str(config.signing_key_shard_template_path))
        )
    return review_rows


def _resolve_kit_index_template_path(config: AppConfig) -> Path:
    kit_template_path = config.kit_template_path
    candidate = kit_template_path.with_name("kit_index_document.html.j2")
    if candidate.is_file() and _is_compatible_kit_index_template(candidate):
        return candidate
    package_candidate = (
        PACKAGE_ROOT / "templates" / kit_template_path.parent.name / "kit_index_document.html.j2"
    )
    return package_candidate


def _is_compatible_kit_index_template(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return _KIT_INDEX_TEMPLATE_MARKER in content


def _print_completion_actions(result: BackupResult, quiet: bool) -> None:
    """Print the completion panel with next actions."""
    if quiet:
        return
    output_dir = str(Path(result.qr_path).parent)
    actions = [
        f"Saved to {output_dir}",
        "Print the QR document and store it securely.",
        "Store the recovery document separately.",
    ]
    if result.kit_index_path:
        actions.append("Store the recovery kit index separately.")
    if result.shard_paths:
        actions.append(f"Store {len(result.shard_paths)} shard documents in different locations.")
    if result.signing_key_shard_paths:
        actions.append(
            f"Store {len(result.signing_key_shard_paths)} signing-key shard documents separately."
        )
    actions.append("Run `ethernity recover` to verify the backup.")
    print_completion_panel("Backup complete", actions, quiet=quiet)


def run_wizard(
    *,
    debug_override: bool | None = None,
    debug_max_bytes: int = DEBUG_MAX_BYTES_DEFAULT,
    config_path: str | None = None,
    paper_size: str | None = None,
    quiet: bool = False,
    args: BackupArgs | None = None,
) -> int:
    with wizard_flow(name="Backup", total_steps=5, quiet=quiet):
        if not quiet:
            console.print("[title]Ethernity backup wizard[/title]")
            console.print("[subtitle]Guided setup for backup documents.[/subtitle]")
            console.print("[subtitle]Defaults favor recovery (2-of-3 shards, unsealed).[/subtitle]")

        with wizard_stage("Encryption"):
            passphrase, passphrase_words = _prompt_encryption(args)

        with wizard_stage("Recovery"):
            sealed, debug, signing_seed_mode, sharding, signing_seed_sharding = (
                _prompt_recovery_options(args, debug_override, quiet)
            )

        with wizard_stage("Layout"):
            config_path, paper = _prompt_layout(config_path, paper_size)
            design = _prompt_design(args)

        plan = build_document_plan(
            sealed=sealed,
            signing_seed_mode=signing_seed_mode,
            sharding=sharding,
            signing_seed_sharding=signing_seed_sharding,
        )

        config = load_app_config(config_path, paper_size=paper)
        config = apply_template_design(config, design)
        config = _apply_qr_chunk_size_override(config, args.qr_chunk_size if args else None)

        with wizard_stage("Inputs"):
            input_files, resolved_base, output_dir = _prompt_inputs(args, quiet, debug)

        review_rows = _build_review_rows(
            passphrase,
            passphrase_words,
            plan,
            input_files,
            resolved_base,
            output_dir,
            config_path,
            paper,
            design,
            config,
            debug,
        )

        with wizard_stage("Review"):
            console.print(panel("Review", build_review_table(review_rows)))
            if not prompt_yes_no(
                "Proceed with backup",
                default=True,
                help_text="Select no to cancel.",
            ):
                console.print("Backup cancelled.")
                return 1

        if args is not None:
            _validate_backup_args(args)

        result = run_backup(
            input_files=input_files,
            base_dir=resolved_base,
            output_dir=output_dir,
            plan=plan,
            passphrase=passphrase,
            passphrase_words=passphrase_words,
            config=config,
            debug=debug,
            debug_max_bytes=debug_max_bytes,
            quiet=quiet,
        )
        print_backup_summary(result, plan, passphrase, quiet=quiet)
        _print_completion_actions(result, quiet)
    return 0


def _should_use_wizard_for_backup(args: BackupArgs) -> bool:
    if args.input or args.input_dir:
        return False
    if not os.isatty(0):
        return False
    return True


def run_backup_command(args: BackupArgs) -> int:
    config = load_app_config(args.config, paper_size=args.paper)
    config = apply_template_design(config, args.design)
    config = _apply_qr_chunk_size_override(config, args.qr_chunk_size)
    inputs = list(args.input or [])
    input_dirs = list(args.input_dir or [])

    _validate_backup_args(args)

    plan = plan_from_args(args)
    if plan.sealed and plan.signing_seed_mode == SigningSeedMode.SHARDED:
        _warn(
            "Signing-key sharding is disabled for sealed backups.",
            quiet=args.quiet,
        )

    passphrase = args.passphrase
    passphrase_words = args.passphrase_words
    quiet = args.quiet
    debug = args.debug
    debug_max_bytes = args.debug_max_bytes
    output_dir = args.output_dir
    status_quiet = quiet or debug
    with progress(quiet=status_quiet) as progress_bar:
        input_files, resolved_base = _load_input_files(
            inputs,
            input_dirs,
            args.base_dir,
            allow_stdin=True,
            progress=progress_bar,
        )
    result = run_backup(
        input_files=input_files,
        base_dir=resolved_base,
        output_dir=output_dir,
        plan=plan,
        passphrase=passphrase,
        passphrase_words=passphrase_words,
        config=config,
        debug=debug,
        debug_max_bytes=debug_max_bytes,
        quiet=quiet,
    )
    print_backup_summary(result, plan, passphrase, quiet=quiet)
    _print_completion_actions(result, quiet)
    return 0


def run_backup(
    *,
    input_files: list[InputFile],
    base_dir: Path | None,
    output_dir: str | None,
    plan: DocumentPlan,
    passphrase: str | None,
    passphrase_words: int | None = None,
    config: AppConfig,
    debug: bool = False,
    debug_max_bytes: int | None = None,
    quiet: bool = False,
) -> BackupResult:
    return _run_backup(
        input_files=input_files,
        base_dir=base_dir,
        output_dir=output_dir,
        plan=plan,
        passphrase=passphrase,
        passphrase_words=passphrase_words,
        config=config,
        debug=debug,
        debug_max_bytes=debug_max_bytes,
        quiet=quiet,
    )
