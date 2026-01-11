#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from ...config import DEFAULT_PAPER_SIZE, PAPER_CONFIGS, AppConfig, load_app_config
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
    prompt_optional_path,
    prompt_optional_secret,
    prompt_required_path,
    prompt_required_paths,
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

    if args is not None and args.sealed:
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
    """Prompt for layout settings. Returns (config_path, paper)."""
    paper = paper_size
    if config_path is None and not paper:
        layout_choices = {key.lower(): key for key in PAPER_CONFIGS.keys()}
        layout_choices["custom"] = "Custom config file (TOML)"
        layout_choice = prompt_choice(
            "Layout preset",
            layout_choices,
            default=DEFAULT_PAPER_SIZE.lower(),
            help_text="Choose a paper preset or select a custom TOML config.",
        )
        if layout_choice == "custom":
            config_path = prompt_required_path(
                "Config file path",
                kind="file",
                help_text="Provide a TOML config file.",
            )
        else:
            paper = layout_choice.upper()
    elif paper:
        paper = paper.upper()
    return config_path, paper


def _prompt_inputs(
    args: BackupArgs | None,
    wizard_mode: bool,
    quiet: bool,
    debug: bool,
) -> tuple[list, Path | None, str | None]:
    """Prompt for input files. Returns (input_files, resolved_base, output_dir)."""
    while True:
        input_values = prompt_required_paths(
            "Input paths (files or directories, blank to finish)",
            help_text="Enter file or directory paths; blank line to finish.",
            kind="path",
            empty_message="At least one input path is required.",
            stdin_message="Stdin input is not supported in the wizard.",
        )
        base_dir = args.base_dir if args is not None else None
        if base_dir is None:
            if wizard_mode:
                base_dir = prompt_optional_path(
                    "Common parent folder (press Enter to auto-detect)",
                    kind="dir",
                    help_text="File paths will be stored relative to this folder.",
                )
            else:
                base_dir = prompt_optional(
                    "Common parent folder (press Enter to auto-detect)",
                    help_text="File paths will be stored relative to this folder.",
                )
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
            console_err.print(f"[error]{exc}[/error]")
            continue
        break

    return input_files, resolved_base, output_dir


def _build_review_rows(
    passphrase: str | None,
    passphrase_words: int | None,
    plan: DocumentPlan,
    input_files: list[InputFile],
    resolved_base: Path | None,
    output_dir: str | None,
    config_path: str | None,
    paper: str | None,
    config: AppConfig,
    debug: bool,
) -> list[tuple[str, str]]:
    """Build the review table rows."""
    review_rows: list[tuple[str, str]] = []
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
    review_rows.append(("Debug output", "enabled" if debug else "disabled"))
    review_rows.append(("Inputs", f"{len(input_files)} file(s)"))
    if resolved_base:
        review_rows.append(("Base dir", str(resolved_base)))
    if output_dir:
        review_rows.append(("Output dir", output_dir))
    else:
        review_rows.append(("Output dir", "default (backup-<doc_id>)"))
    if config_path:
        review_rows.append(("Config", config_path))
    else:
        default_paper = DEFAULT_PAPER_SIZE
        review_rows.append(("Paper preset", paper.upper() if paper else default_paper))
    review_rows.append(("QR template", str(config.template_path)))
    review_rows.append(("Recovery template", str(config.recovery_template_path)))
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


def _print_completion_actions(result: BackupResult, quiet: bool) -> None:
    """Print the completion panel with next actions."""
    if quiet:
        return
    actions = [
        f"Open QR document: {result.qr_path}",
        f"Store recovery document separately: {result.recovery_path}",
    ]
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
    wizard_mode = args is None
    with wizard_flow(name="Backup", total_steps=5, quiet=quiet):
        if not quiet:
            console.print("[title]Ethernity backup wizard[/title]")
            console.print("[subtitle]Interactive setup for creating backup documents.[/subtitle]")
            console.print(
                "[subtitle]Defaults favor recovery: shard quorum defaults to 2 of 3, "
                "and backups are unsealed so you can add shards later.[/subtitle]"
            )

        with wizard_stage("Encryption", help_text="Choose how the backup is secured."):
            passphrase, passphrase_words = _prompt_encryption(args)

        with wizard_stage(
            "Recovery options",
            help_text="Split passphrases into shards and decide whether to seal backups.",
        ):
            sealed, debug, signing_seed_mode, sharding, signing_seed_sharding = (
                _prompt_recovery_options(args, debug_override, quiet)
            )

        with wizard_stage("Layout", help_text="Pick the layout preset or a custom config file."):
            config_path, paper = _prompt_layout(config_path, paper_size)

        plan = build_document_plan(
            sealed=sealed,
            signing_seed_mode=signing_seed_mode,
            sharding=sharding,
            signing_seed_sharding=signing_seed_sharding,
        )

        config = load_app_config(config_path) if config_path else load_app_config(paper_size=paper)

        with wizard_stage(
            "Inputs & output",
            help_text="Select files to include and where to write the PDFs.",
        ):
            input_files, resolved_base, output_dir = _prompt_inputs(args, wizard_mode, quiet, debug)

        review_rows = _build_review_rows(
            passphrase,
            passphrase_words,
            plan,
            input_files,
            resolved_base,
            output_dir,
            config_path,
            paper,
            config,
            debug,
        )

        with wizard_stage("Review & confirm", help_text="Confirm settings before writing files."):
            console.print(panel("Review", build_review_table(review_rows)))
            if not prompt_yes_no(
                "Proceed with backup",
                default=True,
                help_text="Select no to exit without writing any files.",
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
    if args.config and args.paper:
        raise ValueError("use either --config or --paper, not both")

    config = load_app_config(args.config, paper_size=args.paper)
    inputs = list(args.input or [])
    input_dirs = list(args.input_dir or [])
    if not inputs and not input_dirs and not os.isatty(0):
        inputs.append("-")

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
