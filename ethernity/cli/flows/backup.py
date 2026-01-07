#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .backup_flow import run_backup as _run_backup
from ..core.plan import _validate_backup_args, _validate_passphrase_words
from ..core.types import BackupResult, InputFile
from ..io.inputs import _load_input_files
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
    _prompt_optional,
    _prompt_optional_path,
    _prompt_optional_secret,
    _prompt_required_path,
    _prompt_required_paths,
    _prompt_yes_no,
    _warn,
    _wizard_flow,
    _wizard_stage,
)
from ..ui.summary import _print_backup_summary
from ...crypto import DEFAULT_PASSPHRASE_WORDS, MNEMONIC_WORD_COUNTS
from ...config import DEFAULT_PAPER_SIZE, PAPER_CONFIGS, load_app_config
from ...core.models import DocumentPlan, ShardingConfig, SigningSeedMode


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

        passphrase = getattr(args, "passphrase", None) if args is not None else None
        passphrase_generate = bool(getattr(args, "passphrase_generate", False))
        passphrase_words = getattr(args, "passphrase_words", None) if args is not None else None

        with _wizard_stage(
            "Encryption",
            help_text="Choose how the backup is secured.",
        ):
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

        with _wizard_stage(
            "Recovery options",
            help_text="Split passphrases into shards and decide whether to seal backups.",
        ):
            sharding = None
            signing_seed_mode = SigningSeedMode.EMBEDDED
            signing_seed_sharding = None
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

            if sharding is not None:
                mode_arg = getattr(args, "signing_key_mode", None) if args is not None else None
                if mode_arg:
                    signing_seed_mode = SigningSeedMode(mode_arg)
                if sealed:
                    if signing_seed_mode == SigningSeedMode.SHARDED:
                        _warn(
                            "Signing-key sharding is disabled for sealed backups.",
                            quiet=quiet,
                        )
                        signing_seed_mode = SigningSeedMode.EMBEDDED
                else:
                    if mode_arg is None:
                        signing_choice = _prompt_choice(
                            "Signing key handling",
                            {
                                "embedded": "Embedded in main document (default, easiest to mint new shards)",
                                "sharded": "Separate signing-key shards (requires quorum to mint new shards)",
                            },
                            default="embedded",
                            help_text=(
                                "Embedded stores the signing key inside the encrypted main document. "
                                "Sharded keeps it only in separate signing-key shard PDFs."
                            ),
                        )
                        signing_seed_mode = SigningSeedMode(signing_choice)
                    if signing_seed_mode == SigningSeedMode.SHARDED:
                        sk_threshold = getattr(args, "signing_key_shard_threshold", None) if args is not None else None
                        sk_count = getattr(args, "signing_key_shard_count", None) if args is not None else None
                        if sk_threshold is not None or sk_count is not None:
                            if sk_threshold is None or sk_count is None:
                                raise ValueError(
                                    "both --signing-key-shard-threshold and --signing-key-shard-count are required"
                                )
                            use_existing = _prompt_yes_no(
                                f"Use provided signing-key sharding ({sk_threshold} of {sk_count})",
                                default=True,
                                help_text="Choose no to configure a different quorum.",
                            )
                            if use_existing:
                                signing_seed_sharding = ShardingConfig(
                                    threshold=sk_threshold,
                                    shares=sk_count,
                                )
                            else:
                                sk_threshold = _prompt_int(
                                    "Signing-key shard threshold (n)",
                                    minimum=1,
                                    help_text="Minimum signing-key shard documents needed to mint new shards.",
                                )
                                sk_count = _prompt_int(
                                    "Signing-key shard count (k)",
                                    minimum=sk_threshold,
                                    help_text="Total signing-key shard documents to create.",
                                )
                                signing_seed_sharding = ShardingConfig(
                                    threshold=sk_threshold,
                                    shares=sk_count,
                                )
                        else:
                            use_same = _prompt_yes_no(
                                "Use same quorum for signing-key shards",
                                default=True,
                                help_text="Choose no to set a different quorum for signing-key shards.",
                            )
                            if not use_same:
                                sk_threshold = _prompt_int(
                                    "Signing-key shard threshold (n)",
                                    minimum=1,
                                    help_text="Minimum signing-key shard documents needed to mint new shards.",
                                )
                                sk_count = _prompt_int(
                                    "Signing-key shard count (k)",
                                    minimum=sk_threshold,
                                    help_text="Total signing-key shard documents to create.",
                                )
                                signing_seed_sharding = ShardingConfig(
                                    threshold=sk_threshold,
                                    shares=sk_count,
                                )

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

        plan = DocumentPlan(
            version=1,
            sealed=sealed,
            signing_seed_mode=signing_seed_mode,
            sharding=sharding,
            signing_seed_sharding=signing_seed_sharding,
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
                input_values = _prompt_required_paths(
                    "Input paths (files or directories, blank to finish)",
                    help_text="Enter file or directory paths; blank line to finish.",
                    kind="path",
                    empty_message="At least one input path is required.",
                    stdin_message="Stdin input is not supported in the wizard.",
                )
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
                    continue
                break

        review_rows: list[tuple[str, str]] = []
        if passphrase:
            review_rows.append(("Passphrase", "provided"))
        else:
            review_rows.append(("Passphrase", "auto-generated"))
            if passphrase_words:
                review_rows.append(("Passphrase length", f"{passphrase_words} words"))
        plan_sharding = plan.sharding
        if plan_sharding is not None:
            review_rows.append(
                ("Sharding", f"{plan_sharding.threshold} of {plan_sharding.shares}")
            )
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
                    review_rows.append(
                        (
                            "Signing-key shards",
                            f"{plan.signing_seed_sharding.threshold} of {plan.signing_seed_sharding.shares}",
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
        _print_backup_summary(result, plan, passphrase, quiet=quiet)
        if not quiet:
            actions = [
                f"Open QR document: {result.qr_path}",
                f"Store recovery document separately: {result.recovery_path}",
            ]
            if result.shard_paths:
                actions.append(
                    f"Store {len(result.shard_paths)} shard documents in different locations."
                )
            if result.signing_key_shard_paths:
                actions.append(
                    f"Store {len(result.signing_key_shard_paths)} signing-key shard documents separately."
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

    _validate_backup_args(args)

    sharding = None
    if args.shard_threshold or args.shard_count:
        if not args.shard_threshold or not args.shard_count:
            raise ValueError("both --shard-threshold and --shard-count are required")
        sharding = ShardingConfig(threshold=args.shard_threshold, shares=args.shard_count)

    signing_key_mode = getattr(args, "signing_key_mode", None)
    signing_seed_mode = (
        SigningSeedMode(signing_key_mode)
        if signing_key_mode
        else SigningSeedMode.EMBEDDED
    )
    if signing_seed_mode == SigningSeedMode.SHARDED:
        if sharding is None:
            raise ValueError("signing key sharding requires passphrase sharding")
        if args.sealed:
            _warn(
                "Signing-key sharding is disabled for sealed backups.",
                quiet=bool(getattr(args, "quiet", False)),
            )
    signing_key_shard_threshold = getattr(args, "signing_key_shard_threshold", None)
    signing_key_shard_count = getattr(args, "signing_key_shard_count", None)
    signing_seed_sharding = None
    if (
        signing_seed_mode == SigningSeedMode.SHARDED
        and signing_key_shard_threshold is not None
        and signing_key_shard_count is not None
    ):
        signing_seed_sharding = ShardingConfig(
            threshold=signing_key_shard_threshold,
            shares=signing_key_shard_count,
        )

    plan = DocumentPlan(
        version=1,
        sealed=bool(args.sealed),
        signing_seed_mode=signing_seed_mode,
        sharding=sharding,
        signing_seed_sharding=signing_seed_sharding,
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
        passphrase=passphrase,
        passphrase_words=passphrase_words,
        config=config,
        debug=debug,
        debug_max_bytes=debug_max_bytes,
        quiet=quiet,
    )
    _print_backup_summary(result, plan, passphrase, quiet=quiet)
    if not quiet:
        actions = [
            f"Open QR document: {result.qr_path}",
            f"Store recovery document separately: {result.recovery_path}",
        ]
        if result.shard_paths:
            actions.append(
                f"Store {len(result.shard_paths)} shard documents in different locations."
            )
        if result.signing_key_shard_paths:
            actions.append(
                f"Store {len(result.signing_key_shard_paths)} signing-key shard documents separately."
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
    passphrase: str | None,
    passphrase_words: int | None = None,
    config,
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
