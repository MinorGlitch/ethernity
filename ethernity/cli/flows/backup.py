#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .backup_flow import run_backup as _run_backup
from ..core.plan import _infer_mode, _validate_backup_args, _validate_passphrase_words
from ..core.types import BackupResult, InputFile
from ..io.inputs import _load_input_files
from ..keys.keys import _load_recipients
from ..ui import (
    DEBUG_MAX_BYTES_DEFAULT,
    console,
    console_err,
    _build_review_table,
    _panel,
    _print_completion_panel,
    _progress,
    _prompt_choice,
    _prompt_int,
    _prompt_multiline,
    _prompt_optional,
    _prompt_optional_path,
    _prompt_optional_secret,
    _prompt_required_path,
    _prompt_required_secret,
    _prompt_yes_no,
    _warn,
    _wizard_flow,
    _wizard_stage,
)
from ..ui.summary import _print_backup_summary
from ...crypto import DEFAULT_PASSPHRASE_WORDS, MNEMONIC_WORD_COUNTS
from ...config import DEFAULT_PAPER_SIZE, PAPER_CONFIGS, load_app_config
from ...core.models import DocumentMode, DocumentPlan, KeyMaterial, ShardingConfig


def _prompt_passphrase_words() -> int:
    choices = {str(count): f"{count} words" for count in MNEMONIC_WORD_COUNTS}
    default = str(DEFAULT_PASSPHRASE_WORDS)
    value = _prompt_choice(
        "Passphrase length",
        choices,
        default=default,
        help_text="Longer passphrases are stronger and easier to record.",
    )
    return int(value)


def run_wizard(
    *,
    debug_override: bool | None = None,
    debug_max_bytes: int = DEBUG_MAX_BYTES_DEFAULT,
    config_path: str | None = None,
    paper_size: str | None = None,
    quiet: bool = False,
    args: argparse.Namespace | None = None,
) -> int:
    wizard_mode = args is None
    with _wizard_flow(name="Backup", total_steps=5, quiet=quiet):
        if not quiet:
            console.print("[title]Ethernity backup wizard[/title]")
            console.print("[subtitle]Interactive setup for creating backup documents.[/subtitle]")
            console.print(
                "[subtitle]Defaults favor recovery: shard quorum defaults to 2 of 3, and backups are "
                "unsealed so you can add shards later.[/subtitle]"
            )

        recipients = _load_recipients(
            list(getattr(args, "recipient", []) or []),
            list(getattr(args, "recipients_file", []) or []),
        )
        passphrase = getattr(args, "passphrase", None) if args is not None else None
        passphrase_generate = bool(getattr(args, "passphrase_generate", False))
        passphrase_words = getattr(args, "passphrase_words", None) if args is not None else None
        generate_identity = bool(getattr(args, "generate_identity", False))

        mode_arg = getattr(args, "mode", None) if args is not None else None
        key_material = KeyMaterial.NONE
        with _wizard_stage(
            "Encryption",
            help_text="Choose how the backup is secured.",
        ):
            if mode_arg:
                mode = DocumentMode(mode_arg)
            elif recipients or generate_identity:
                mode = DocumentMode.RECIPIENT
            elif passphrase or passphrase_generate:
                mode = DocumentMode.PASSPHRASE
            else:
                mode_choice = _prompt_choice(
                    "Encryption type",
                    {
                        "passphrase": "Passphrase (single secret)",
                        "recipient": "Recipients (age public keys)",
                    },
                    default="passphrase",
                    help_text=(
                        "Passphrase is a single secret. Recipients are public keys for shared access."
                    ),
                )
                mode = (
                    DocumentMode.PASSPHRASE
                    if mode_choice == "passphrase"
                    else DocumentMode.RECIPIENT
                )

            if mode == DocumentMode.PASSPHRASE:
                if passphrase is not None:
                    entered = _prompt_optional_secret(
                        "Enter passphrase",
                        help_text="Leave blank to keep the passphrase provided via flags.",
                    )
                    if entered is not None:
                        passphrase = entered
                else:
                    help_text = "Leave blank to auto-generate a strong passphrase."
                    if passphrase_generate:
                        help_text = (
                            "Leave blank to auto-generate a strong passphrase (as requested)."
                        )
                    passphrase = _prompt_optional_secret("Enter passphrase", help_text=help_text)
                    if passphrase is None:
                        if passphrase_words is None:
                            passphrase_words = _prompt_passphrase_words()
                        else:
                            _validate_passphrase_words(passphrase_words)
                key_material = KeyMaterial.PASSPHRASE
            else:
                if recipients:
                    key_material = KeyMaterial.NONE
                elif generate_identity:
                    key_material = KeyMaterial.IDENTITY
                else:
                    use_existing = _prompt_yes_no(
                        "Provide recipient public keys",
                        default=True,
                        help_text="Recipients are age public keys used for shared access.",
                    )
                    if use_existing:
                        while True:
                            recipients = _prompt_multiline(
                                "Enter recipients (one per line, blank to finish)",
                                help_text="Each line should be an age public key like age1...",
                            )
                            if recipients:
                                key_material = KeyMaterial.NONE
                                break
                            use_identity = _prompt_yes_no(
                                "No recipients entered. Generate a new identity instead",
                                default=True,
                                help_text="Generates a new age identity and uses its public key.",
                            )
                            if use_identity:
                                key_material = KeyMaterial.IDENTITY
                                break
                    else:
                        key_material = KeyMaterial.IDENTITY

        with _wizard_stage(
            "Recovery options",
            help_text="Split passphrases into shards and decide whether to seal backups.",
        ):
            sharding = None
            if mode == DocumentMode.PASSPHRASE:
                threshold = getattr(args, "shard_threshold", None) if args is not None else None
                shares = getattr(args, "shard_count", None) if args is not None else None
                if threshold is not None or shares is not None:
                    if threshold is None or shares is None:
                        raise ValueError("both --shard-threshold and --shard-count are required")
                    use_existing = _prompt_yes_no(
                        f"Use provided sharding ({threshold} of {shares})",
                        default=True,
                        help_text="Choose no to configure a different quorum.",
                    )
                    if use_existing:
                        sharding = ShardingConfig(threshold=threshold, shares=shares)
                    else:
                        default_threshold = 2
                        default_shares = 3
                        use_default = _prompt_yes_no(
                            f"Use the default quorum ({default_threshold} of {default_shares})",
                            default=True,
                            help_text="Pick a different split if you need more redundancy.",
                        )
                        if use_default:
                            sharding = ShardingConfig(
                                threshold=default_threshold,
                                shares=default_shares,
                            )
                        else:
                            threshold = _prompt_int(
                                "Shard threshold (n)",
                                minimum=1,
                                help_text="Minimum number of shard documents required to recover.",
                            )
                            shares = _prompt_int(
                                "Shard count (k)",
                                minimum=threshold,
                                help_text="Total number of shard documents to create.",
                            )
                            sharding = ShardingConfig(threshold=threshold, shares=shares)
                else:
                    enable_sharding = _prompt_yes_no(
                        "Split passphrase into shard documents",
                        default=True,
                        help_text="Recommended. You'll need a quorum of shard documents to recover.",
                    )
                    if enable_sharding:
                        default_threshold = 2
                        default_shares = 3
                        use_default = _prompt_yes_no(
                            f"Use the default quorum ({default_threshold} of {default_shares})",
                            default=True,
                            help_text="Pick a different split if you need more redundancy.",
                        )
                        if use_default:
                            sharding = ShardingConfig(
                                threshold=default_threshold,
                                shares=default_shares,
                            )
                        else:
                            threshold = _prompt_int(
                                "Shard threshold (n)",
                                minimum=1,
                                help_text="Minimum number of shard documents required to recover.",
                            )
                            shares = _prompt_int(
                                "Shard count (k)",
                                minimum=threshold,
                                help_text="Total number of shard documents to create.",
                            )
                            sharding = ShardingConfig(threshold=threshold, shares=shares)

            if args is not None and getattr(args, "sealed", False):
                sealed = True
            else:
                sealed = _prompt_yes_no(
                    "Seal backup (disallow new shards)",
                    default=False,
                    help_text="Sealed backups prevent creating new shard docs later.",
                )
            if debug_override is None:
                debug = _prompt_yes_no(
                    "Show pre-encryption debug output",
                    default=False,
                    help_text="Includes plaintext details; use only for troubleshooting.",
                )
            else:
                debug = debug_override

        with _wizard_stage(
            "Layout",
            help_text="Pick the layout preset or a custom config file.",
        ):
            paper = paper_size
            if config_path is None and not paper:
                layout_choices = {key.lower(): key for key in PAPER_CONFIGS.keys()}
                layout_choices["custom"] = "Custom config file (TOML)"
                layout_choice = _prompt_choice(
                    "Layout preset",
                    layout_choices,
                    default=DEFAULT_PAPER_SIZE.lower(),
                    help_text="Choose a paper preset or select a custom TOML config.",
                )
                if layout_choice == "custom":
                    config_path = _prompt_required_path(
                        "Config file path",
                        kind="file",
                        help_text="Provide a TOML config file.",
                    )
                else:
                    paper = layout_choice.upper()
            elif paper:
                paper = paper.upper()

        if key_material == KeyMaterial.NONE and sharding is not None:
            _warn("Sharding requires key material; disabling sharding.", quiet=quiet)
            sharding = None

        plan = DocumentPlan(
            version=1,
            mode=mode,
            key_material=key_material,
            sealed=sealed,
            sharding=sharding,
            recipients=tuple(recipients),
        )

        if config_path:
            config = load_app_config(config_path)
        else:
            config = load_app_config(paper_size=paper)

        with _wizard_stage(
            "Inputs & output",
            help_text="Select files to include and where to write the PDFs.",
        ):
            while True:
                input_values = _prompt_multiline(
                    "Input paths (files or directories, blank to finish)",
                    help_text="Enter file or directory paths; blank line to finish.",
                )
                if not input_values:
                    console_err.print("[error]At least one input path is required.[/error]")
                    if not wizard_mode:
                        raise ValueError("at least one input path is required")
                    continue
                if "-" in input_values:
                    console_err.print(
                        "[error]Stdin input is not supported in the wizard.[/error]"
                    )
                    if not wizard_mode:
                        raise ValueError("stdin input is not supported in the wizard")
                    continue
                base_dir = getattr(args, "base_dir", None) if args is not None else None
                if base_dir is None:
                    if wizard_mode:
                        base_dir = _prompt_optional_path(
                            "Base directory for relative paths (leave blank to auto)",
                            kind="dir",
                            help_text="If set, paths are stored relative to this directory.",
                        )
                    else:
                        base_dir = _prompt_optional(
                            "Base directory for relative paths (leave blank to auto)",
                            help_text="If set, paths are stored relative to this directory.",
                        )
                output_dir = getattr(args, "output_dir", None) if args is not None else None
                if output_dir is None:
                    output_dir = _prompt_optional(
                        "Output directory (leave blank for default)",
                        help_text="Default creates a backup-<doc_id> folder.",
                    )

                status_quiet = quiet or debug
                try:
                    with _progress(quiet=status_quiet) as progress:
                        input_files, resolved_base = _load_input_files(
                            input_values,
                            [],
                            base_dir,
                            allow_stdin=False,
                            progress=progress,
                        )
                except ValueError as exc:
                    console_err.print(f"[error]{exc}[/error]")
                    if not wizard_mode:
                        raise
                    continue
                break

        review_rows: list[tuple[str, str]] = [("Mode", plan.mode.value)]
        if plan.mode == DocumentMode.PASSPHRASE:
            if passphrase:
                review_rows.append(("Passphrase", "provided"))
            else:
                review_rows.append(("Passphrase", "auto-generated"))
            plan_sharding = plan.sharding
            if plan_sharding is not None:
                review_rows.append(
                    ("Sharding", f"{plan_sharding.threshold} of {plan_sharding.shares}")
                )
            else:
                review_rows.append(("Sharding", "disabled"))
        else:
            if recipients:
                review_rows.append(("Recipients", f"{len(recipients)} provided"))
            elif plan.key_material == KeyMaterial.IDENTITY:
                review_rows.append(("Recipients", "generated identity"))
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
        review_rows.append(("Template", str(config.template_path)))
        review_rows.append(("Recovery template", str(config.recovery_template_path)))

        with _wizard_stage(
            "Review & confirm",
            help_text="Confirm settings before writing files.",
        ):
            console.print(_panel("Review", _build_review_table(review_rows)))
            if not _prompt_yes_no(
                "Proceed with backup",
                default=True,
                help_text="Select no to exit without writing any files.",
            ):
                console.print("Backup cancelled.")
                return 1
        if args is not None and "passphrase_generate" in vars(args):
            _validate_backup_args(plan.mode, args, recipients)
        result = run_backup(
            input_files=input_files,
            base_dir=resolved_base,
            output_dir=output_dir,
            plan=plan,
            recipients=recipients,
            passphrase=passphrase,
            passphrase_words=passphrase_words,
            config=config,
            title_override=getattr(args, "title", None) if args is not None else None,
            subtitle_override=getattr(args, "subtitle", None) if args is not None else None,
            debug=debug,
            debug_max_bytes=debug_max_bytes,
            quiet=quiet,
        )
        _print_backup_summary(result, plan, recipients, passphrase, quiet=quiet)
        if not quiet:
            actions = [
                f"Open QR document: {result.qr_path}",
                f"Store recovery document separately: {result.recovery_path}",
            ]
            if result.shard_paths:
                actions.append(
                    f"Store {len(result.shard_paths)} shard documents in different locations."
                )
            actions.append("Run `ethernity recover` to verify the backup.")
            _print_completion_panel("Backup complete", actions, quiet=quiet)
    return 0


def _should_use_wizard_for_backup(args: argparse.Namespace) -> bool:
    if args.input or args.input_dir:
        return False
    if not os.isatty(0):
        return False
    return True


def run_backup_command(args: argparse.Namespace) -> int:
    if args.config and args.paper:
        raise ValueError("use either --config or --paper, not both")

    config = load_app_config(args.config, paper_size=args.paper)
    inputs = list(args.input or [])
    input_dirs = list(args.input_dir or [])
    if not inputs and not input_dirs and not os.isatty(0):
        inputs.append("-")

    mode = DocumentMode(args.mode) if args.mode else _infer_mode(args)
    recipients = _load_recipients(args.recipient, args.recipients_file)
    _validate_backup_args(mode, args, recipients)
    if mode == DocumentMode.RECIPIENT and not recipients and not args.generate_identity:
        raise ValueError("recipient mode requires --recipient/--recipients-file or --generate-identity")

    sharding = None
    if args.shard_threshold or args.shard_count:
        if not args.shard_threshold or not args.shard_count:
            raise ValueError("both --shard-threshold and --shard-count are required")
        sharding = ShardingConfig(threshold=args.shard_threshold, shares=args.shard_count)

    if mode == DocumentMode.PASSPHRASE:
        key_material = KeyMaterial.PASSPHRASE
    else:
        key_material = KeyMaterial.IDENTITY if args.generate_identity else KeyMaterial.NONE

    if mode == DocumentMode.RECIPIENT and sharding is not None:
        print("Sharding is only supported for passphrase mode; disabling sharding.", file=sys.stderr)
        sharding = None

    plan = DocumentPlan(
        version=1,
        mode=mode,
        key_material=key_material,
        sealed=bool(args.sealed),
        sharding=sharding,
        recipients=tuple(recipients),
    )

    passphrase = args.passphrase
    passphrase_words = getattr(args, "passphrase_words", None)
    quiet = bool(getattr(args, "quiet", False))
    debug = getattr(args, "debug", False)
    debug_max_bytes = getattr(args, "debug_max_bytes", 0)
    output_dir = args.output_dir
    status_quiet = quiet or debug
    with _progress(quiet=status_quiet) as progress:
        input_files, resolved_base = _load_input_files(
            inputs,
            input_dirs,
            args.base_dir,
            allow_stdin=True,
            progress=progress,
        )
    result = run_backup(
        input_files=input_files,
        base_dir=resolved_base,
        output_dir=output_dir,
        plan=plan,
        recipients=recipients,
        passphrase=passphrase,
        passphrase_words=passphrase_words,
        config=config,
        title_override=args.title,
        subtitle_override=args.subtitle,
        debug=debug,
        debug_max_bytes=debug_max_bytes,
        quiet=quiet,
    )
    _print_backup_summary(result, plan, recipients, passphrase, quiet=quiet)
    if not quiet:
        actions = [
            f"Open QR document: {result.qr_path}",
            f"Store recovery document separately: {result.recovery_path}",
        ]
        if result.shard_paths:
            actions.append(
                f"Store {len(result.shard_paths)} shard documents in different locations."
            )
        actions.append("Run `ethernity recover` to verify the backup.")
        _print_completion_panel("Backup complete", actions, quiet=quiet)
    return 0



def run_backup(
    *,
    input_files: list[InputFile],
    base_dir: Path | None,
    output_dir: str | None,
    plan: DocumentPlan,
    recipients: list[str],
    passphrase: str | None,
    passphrase_words: int | None = None,
    config,
    title_override: str | None,
    subtitle_override: str | None,
    debug: bool = False,
    debug_max_bytes: int | None = None,
    quiet: bool = False,
) -> BackupResult:
    return _run_backup(
        input_files=input_files,
        base_dir=base_dir,
        output_dir=output_dir,
        plan=plan,
        recipients=recipients,
        passphrase=passphrase,
        passphrase_words=passphrase_words,
        config=config,
        title_override=title_override,
        subtitle_override=subtitle_override,
        debug=debug,
        debug_max_bytes=debug_max_bytes,
        quiet=quiet,
    )
