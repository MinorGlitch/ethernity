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

import functools
from pathlib import Path
from typing import Annotated, Literal

import typer

from ethernity.cli.bootstrap.startup import ensure_playwright_browsers
from ethernity.cli.features.extend.models import (
    EXTENSION_TOO_LARGE,
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PassphraseStoragePolicy,
    PlaintextPassphrase,
    ReuseRootPassphraseShards,
    SigningKeyStoragePolicy,
)
from ethernity.cli.features.extend.service import (
    PreparedExtendRun,
    PublishedExtensionResult,
    encrypt_prepared_extension_document,
    prepare_extend_run,
    resolve_extend_runtime,
    run_extend,
    validate_prepared_extend_render,
)
from ethernity.cli.features.extend.workspace import prompt_add_files_workspace_args
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.common import (
    _ctx_state,
    _paper_callback,
    _resolve_config_and_paper,
    _run_cli,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs
from ethernity.cli.shared.ui_api import (
    build_kv_table,
    build_outputs_tree,
    console,
    console_err,
    panel,
    print_completion_panel,
)
from ethernity.config import ExtendDefaults
from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.extensions.build import default_extension_chunker
from ethernity.extensions.staging import preflight_extension_publish_target

_EXTEND_HELP = (
    "Create a new extension update from an authenticated backup chain "
    "and publish it into a writable output root.\n\n"
    "Examples:\n"
    "  ethernity extend --root-dir root --input in.txt\n"
    "  ethernity extend --root-dir out --scan root.pdf --scan extension-01.pdf --input in.txt\n"
    "  ethernity extend --root-dir root --input in.txt --dry-run\n"
    "  ethernity extend --root-dir root --input in.txt --unlock-policy reuse-root\n"
    "  ethernity extend --root-dir root --input in.txt --signing-key-mode sharded\n"
    "  ethernity extend --root-dir root --input-dir docs --base-dir docs\n\n"
    "Notes:\n"
    "  reuse-root requires a recoverable root passphrase shard quorum and emits no "
    "extension-local passphrase shards.\n"
    "  pass --shard-count 0 to explicitly choose plaintext passphrase output.\n"
    "  pass --signing-key-mode sharded to write root/chain signing authority shard documents.\n"
    "  scan-mode append requires --expected-head-doc-hash or explicit --allow-stale-head.\n"
)


def register(app: typer.Typer) -> None:
    app.command(name="add", help="Add files to an existing backup with a guided workspace.")(add)
    app.command(help=_EXTEND_HELP)(extend)


def _print_extend_summary(result: PublishedExtensionResult, *, quiet: bool) -> None:
    if quiet:
        return
    console.print()
    console.print(
        panel(
            "Outputs",
            build_outputs_tree(
                str(result.qr_document_path),
                str(result.recovery_document_path),
                tuple(str(path) for path in result.shard_paths),
                tuple(str(path) for path in result.signing_key_shard_paths),
                str(result.recovery_kit_index_path) if result.recovery_kit_index_path else None,
            ),
        )
    )
    console.print(
        panel(
            "Extension summary",
            build_kv_table(
                [
                    ("Root", str(result.publish_root or result.final_dir.parent.parent)),
                    ("Extension dir", str(result.final_dir)),
                    ("Index", f"{result.index:02d}"),
                    ("Doc ID", result.doc_id.hex()),
                    (
                        "Extending from",
                        (
                            f"supplied head {result.parent_head_index}"
                            if result.parent_head_index is not None
                            else "supplied head"
                        ),
                    ),
                    ("Freshness scope", "supplied carriers only"),
                    *(
                        [("Head doc hash", result.parent_head_doc_hash)]
                        if result.parent_head_doc_hash is not None
                        else []
                    ),
                    *(
                        [("Expected head", result.expected_head_doc_hash)]
                        if result.expected_head_doc_hash is not None
                        else []
                    ),
                ]
            ),
        )
    )


def _print_completion_actions(result: PublishedExtensionResult, *, quiet: bool) -> None:
    if quiet:
        return
    actions = [
        f"Saved extension {result.index:02d} to {result.final_dir}",
        "Keep the root backup media and every extension document together.",
    ]
    if result.root_passphrase_shard_threshold is not None and result.root_passphrase_shard_count:
        actions.append(
            "Recovering this extension depends on the root passphrase shard quorum "
            f"({result.root_passphrase_shard_threshold} of "
            f"{result.root_passphrase_shard_count}); keep those root shard documents available."
        )
    if result.shard_paths:
        actions.append(f"Store {len(result.shard_paths)} extension shard documents separately.")
    if result.signing_key_shard_paths:
        actions.append(
            "Store "
            f"{len(result.signing_key_shard_paths)} root/chain signing authority shard documents "
            "separately."
        )
    actions.append("Verify the extended chain before retiring any older media set.")
    print_completion_panel("Extend complete", actions, quiet=quiet)


def run_extend_command(args: ExtendArgs, *, debug: bool = False) -> int:
    _ = debug
    ensure_playwright_browsers(quiet=args.quiet)
    result = run_extend(args)
    _print_extend_summary(result, quiet=args.quiet)
    _print_completion_actions(result, quiet=args.quiet)
    return 0


def run_extend_dry_run_command(args: ExtendArgs, *, debug: bool = False) -> int:
    _ = debug
    prepared = prepare_extend_run(args)
    try:
        preflight_extension_publish_target(
            prepared.inspection.root_dir,
            index=prepared.next_index,
            publish_layout="loose" if prepared.args.scan else "canonical",
            allow_missing_root=bool(prepared.args.scan),
            require_empty_root=bool(prepared.args.scan),
        )
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.EXTENSION_PUBLISH_TARGET_INVALID,
            message=str(exc),
            details={"stage": "publish_target"},
        ) from exc
    runtime = resolve_extend_runtime(prepared, create_layout_debug_dir=False)
    encrypted = encrypt_prepared_extension_document(
        prepared,
        chunker=default_extension_chunker,
    )
    estimated_extension_bytes = len(encrypted.ciphertext)
    if estimated_extension_bytes > MAX_CIPHERTEXT_BYTES:
        raise ApiCommandError(
            code=EXTENSION_TOO_LARGE,
            message=(
                "extension ciphertext exceeds MAX_CIPHERTEXT_BYTES "
                f"({MAX_CIPHERTEXT_BYTES}): {estimated_extension_bytes} bytes"
            ),
        )
    validate_prepared_extend_render(prepared, runtime=runtime, encrypted=encrypted)
    _print_extend_dry_run_summary(
        args,
        prepared=prepared,
        qr_chunk_size=runtime.qr_chunk_size,
        passphrase_policy=runtime.passphrase,
        signing_key_policy=runtime.signing_key,
        recovery_kit_index=runtime.kit_index_template_path is not None,
        chunk_reuse={
            "reused_chunks": encrypted.built.stats.reused_chunks,
            "new_chunks": encrypted.built.stats.new_chunks,
        },
        estimated_extension_bytes=estimated_extension_bytes,
    )
    return 0


def _print_extend_dry_run_summary(
    args: ExtendArgs,
    *,
    prepared: PreparedExtendRun,
    qr_chunk_size: int,
    passphrase_policy: PassphraseStoragePolicy,
    signing_key_policy: SigningKeyStoragePolicy,
    recovery_kit_index: bool,
    chunk_reuse: dict[str, int],
    estimated_extension_bytes: int,
) -> None:
    if args.quiet:
        return
    console.print()
    console.print(
        panel(
            "Extend dry run",
            build_kv_table(
                [
                    ("Root", str(args.root_dir)),
                    ("Next index", f"{prepared.next_index:02d}"),
                    ("Parent doc hash", prepared.parent_doc_hash.hex()),
                    ("Changed paths", str(len(prepared.changed_paths))),
                    ("New paths", str(len(prepared.new_paths))),
                    ("Unchanged paths", str(len(prepared.unchanged_paths))),
                    ("Reused chunks", str(chunk_reuse["reused_chunks"])),
                    ("New chunks", str(chunk_reuse["new_chunks"])),
                    ("Estimated ciphertext bytes", str(estimated_extension_bytes)),
                    ("Passphrase recovery", _passphrase_policy_label(passphrase_policy)),
                    ("Signing authority recovery", _signing_key_policy_label(signing_key_policy)),
                    ("Recovery kit index", "yes" if recovery_kit_index else "no"),
                    ("QR chunk size", str(qr_chunk_size)),
                ]
            ),
        )
    )


def _passphrase_policy_label(policy: PassphraseStoragePolicy) -> str:
    if isinstance(policy, ReuseRootPassphraseShards):
        return f"reuse root shards ({policy.threshold} of {policy.share_count})"
    if isinstance(policy, ExtensionPassphraseShards):
        return f"extension shards ({policy.threshold} of {policy.share_count})"
    if isinstance(policy, PlaintextPassphrase):
        return "plaintext in recovery document"
    return "unknown"


def _signing_key_policy_label(policy: SigningKeyStoragePolicy) -> str:
    if isinstance(policy, ExtensionSigningKeyShards):
        return f"root/chain signing authority shards ({policy.threshold} of {policy.share_count})"
    return "not stored in extension artifacts"


def add(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Use this config file.",
            rich_help_panel="Config",
        ),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper",
            help="Paper size override (A4/Letter).",
            callback=_paper_callback,
            rich_help_panel="Config",
        ),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option(
            "--design",
            help="Template design folder (auto-discovered under templates/).",
            rich_help_panel="Config",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Show traceback details on failure.",
            rich_help_panel="Debug",
        ),
    ] = False,
) -> None:
    state = _ctx_state(ctx)
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    design_value = design or (state.design if state is not None else None)
    defaults = state.extend_defaults if state is not None else None
    if not isinstance(defaults, ExtendDefaults):
        defaults = ExtendDefaults()
    quiet_value = quiet or (state.quiet if state is not None else False)
    debug_value = debug or (state.debug if state is not None else False)

    def _run_guided_add() -> int | None:
        args = prompt_add_files_workspace_args(
            config=config_value,
            paper=paper_value,
            design=design_value,
            quiet=quiet_value,
            extend_defaults=defaults,
        )
        if args is None:
            return 1
        return run_extend_command(args, debug=debug_value)

    _run_cli(_run_guided_add, debug=debug_value)


def extend(
    ctx: typer.Context,
    root_dir: Annotated[
        Path,
        typer.Option(
            "--root-dir",
            help="Writable folder where the next extension artifacts will be published.",
            rich_help_panel="Inputs",
        ),
    ],
    scan: Annotated[
        list[str] | None,
        typer.Option(
            "--scan",
            help=(
                "Printed/scanned root or extension backup image/PDF to use as the current chain "
                "source (repeatable)."
            ),
            rich_help_panel="Inputs",
        ),
    ] = None,
    input: Annotated[
        list[Path] | None,
        typer.Option(
            "--input",
            "-i",
            help="File to include in this extension (repeatable, use - for stdin).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    input_dir: Annotated[
        list[Path] | None,
        typer.Option(
            "--input-dir",
            help="Folder to include in this extension (recursive, repeatable).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase to decrypt and extend with.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-fallback-file",
            help="Passphrase shard recovery text file for unlocking the existing backup.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Passphrase shard QR payload file for unlocking the existing backup.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-scan",
            help="Passphrase shard image/PDF to scan for unlocking the existing backup.",
            rich_help_panel="Unlock",
        ),
    ] = None,
    unlock_policy: Annotated[
        Literal["self-contained", "reuse-root"] | None,
        typer.Option(
            "--unlock-policy",
            help=(
                "Extension unlock artifact policy. reuse-root requires a recoverable root "
                "passphrase shard quorum and emits no extension-local passphrase shards; "
                "explicit signing-key shard options remain independent."
            ),
            rich_help_panel="Outputs",
        ),
    ] = None,
    shard_threshold: Annotated[
        int | None,
        typer.Option(
            "--shard-threshold",
            help="Extension shards needed to recover.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    shard_count: Annotated[
        int | None,
        typer.Option(
            "--shard-count",
            help="Extension shard documents to create.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    signing_key_mode: Annotated[
        Literal["not-stored", "sharded"] | None,
        typer.Option(
            "--signing-key-mode",
            help=(
                "Root/chain signing authority recovery for future extension minting: "
                "not-stored or sharded."
            ),
            rich_help_panel="Outputs",
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        int | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Root/chain signing authority shards needed to recover.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        int | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Root/chain signing authority shard documents to create.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    expected_head_doc_hash: Annotated[
        str | None,
        typer.Option(
            "--expected-head-doc-hash",
            help="Require the validated current head to match this 32-byte doc hash.",
            rich_help_panel="Behavior",
        ),
    ] = None,
    allow_stale_head: Annotated[
        bool,
        typer.Option(
            "--allow-stale-head",
            help=(
                "Allow scan-mode append without a trusted expected head hash. "
                "Only use when the supplied scans are known to be the latest chain state."
            ),
            rich_help_panel="Behavior",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Render-validate and preview the next extension without publishing artifacts.",
            rich_help_panel="Behavior",
        ),
    ] = False,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Use this config file.",
            rich_help_panel="Config",
        ),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper",
            help="Paper size override (A4/Letter).",
            callback=_paper_callback,
            rich_help_panel="Config",
        ),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option(
            "--design",
            help="Template design folder (auto-discovered under templates/).",
            rich_help_panel="Config",
        ),
    ] = None,
    qr_chunk_size: Annotated[
        int | None,
        typer.Option(
            "--qr-chunk-size",
            help="Preferred ciphertext bytes per QR frame.",
            rich_help_panel="Config",
        ),
    ] = None,
    base_dir: Annotated[
        str | None,
        typer.Option(
            "--base-dir",
            help="Base path for stored relative names.",
            rich_help_panel="Advanced",
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir",
            help=(
                "Write per-document layout diagnostics JSON files to this directory "
                "(for pagination/capacity debugging)."
            ),
            rich_help_panel="Advanced",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Show traceback details on failure.",
            rich_help_panel="Debug",
        ),
    ] = False,
) -> None:
    state = _ctx_state(ctx)
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    design_value = design or (state.design if state is not None else None)
    defaults = state.extend_defaults if state is not None else None
    if not isinstance(defaults, ExtendDefaults):
        defaults = ExtendDefaults()

    quiet_value = quiet or (state.quiet if state is not None else False)
    debug_value = debug or (state.debug if state is not None else False)
    base_dir_value = base_dir if base_dir is not None else defaults.base_dir

    args = ExtendArgs(
        config=config_value,
        paper=paper_value,
        design=design_value,
        root_dir=str(root_dir),
        scan=list(scan or []),
        input=[str(path) for path in (input or [])],
        input_dir=[str(path) for path in (input_dir or [])],
        base_dir=base_dir_value,
        layout_debug_dir=layout_debug_dir,
        qr_chunk_size=qr_chunk_size,
        passphrase=passphrase,
        shard_fallback_file=list(shard_fallback_file or []),
        shard_payloads_file=list(shard_payloads_file or []),
        shard_scan=list(shard_scan or []),
        unlock_policy=unlock_policy,
        shard_threshold=shard_threshold,
        shard_count=shard_count,
        signing_key_mode=signing_key_mode,
        signing_key_shard_threshold=signing_key_shard_threshold,
        signing_key_shard_count=signing_key_shard_count,
        expected_head_doc_hash=expected_head_doc_hash,
        allow_stale_head=allow_stale_head,
        quiet=quiet_value,
    )
    if not args.input and not args.input_dir:
        console_err.print(
            "Input is required for extend. Use --input PATH, --input-dir DIR, or --input -."
        )
        raise typer.Exit(code=2)
    command = run_extend_dry_run_command if dry_run else run_extend_command
    _run_cli(functools.partial(command, args, debug=debug_value), debug=debug_value)
