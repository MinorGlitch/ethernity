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

from collections.abc import Sequence

from ethernity.cli.shared.types import BackupResult, MintResult
from ethernity.cli.shared.ui import (
    build_kv_table,
    build_mint_outputs_tree,
    build_outputs_tree,
    build_recovered_tree,
    console,
    console_err,
    panel,
)
from ethernity.core.models import DocumentPlan


def _recover_target_rows(
    *,
    requested_extension_index: int | None,
    requested_extension_doc_hash: str | None,
    expected_head_doc_hash: str | None,
    selected_extension_index: int | None,
    selected_extension_doc_hash: str | None,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if requested_extension_index is None and requested_extension_doc_hash is None:
        if selected_extension_index is not None:
            rows.append(
                (
                    "Replay target",
                    f"latest supplied authenticated extension {selected_extension_index}",
                )
            )
            if selected_extension_doc_hash is not None:
                rows.append(("Target doc hash", selected_extension_doc_hash))
            rows.append(("Freshness scope", "supplied carriers only"))
        if expected_head_doc_hash is not None:
            rows.append(("Expected head", expected_head_doc_hash))
        return rows
    if requested_extension_index == 0:
        rows.append(("Replay target", "explicit selection: root backup (extension 0)"))
        if expected_head_doc_hash is not None:
            rows.append(("Expected head", expected_head_doc_hash))
        return rows

    if selected_extension_index is not None:
        rows.append(("Replay target", f"explicit selection: extension {selected_extension_index}"))
    else:
        rows.append(("Replay target", "explicit selection"))

    target_doc_hash = selected_extension_doc_hash or requested_extension_doc_hash
    if target_doc_hash is not None:
        rows.append(("Target doc hash", target_doc_hash))
    if expected_head_doc_hash is not None:
        rows.append(("Expected head", expected_head_doc_hash))
    rows.append(("Freshness scope", "supplied carriers only"))
    return rows


def _mint_target_rows(result: MintResult) -> list[tuple[str, str]]:
    if result.selected_extension_index is None:
        return [("Mint target", "root backup")]
    rows = [("Mint target", f"extension {result.selected_extension_index}")]
    if result.selected_extension_doc_hash is not None:
        rows.append(("Target doc hash", result.selected_extension_doc_hash))
    return rows


def print_backup_summary(
    result: BackupResult,
    plan: DocumentPlan,
    passphrase: str | None,
    *,
    quiet: bool,
) -> None:
    _ = (plan, passphrase)
    if quiet:
        return
    console.print()
    console.print(
        panel(
            "Outputs",
            build_outputs_tree(
                result.qr_path,
                result.recovery_path,
                result.shard_paths,
                result.signing_key_shard_paths,
                result.kit_index_path,
            ),
        )
    )


def print_recover_summary(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    auth_status: str | None,
    quiet: bool,
    single_entry_output_is_directory: bool = False,
    requested_extension_index: int | None = None,
    requested_extension_doc_hash: str | None = None,
    expected_head_doc_hash: str | None = None,
    selected_extension_index: int | None = None,
    selected_extension_doc_hash: str | None = None,
) -> None:
    if quiet:
        return
    count = len(entries)
    suffix = "file" if count == 1 else "files"
    rows = [("Recovered", f"{count} {suffix}")]
    if output_path:
        rows.append(("Output", output_path))
    else:
        rows.append(("Output", "stdout"))
    if auth_status:
        rows.append(("Auth verification", auth_status))
    rows.extend(
        _recover_target_rows(
            requested_extension_index=requested_extension_index,
            requested_extension_doc_hash=requested_extension_doc_hash,
            expected_head_doc_hash=expected_head_doc_hash,
            selected_extension_index=selected_extension_index,
            selected_extension_doc_hash=selected_extension_doc_hash,
        )
    )
    console_err.print(panel("Recovery summary", build_kv_table(rows)))
    tree = build_recovered_tree(
        entries,
        output_path,
        single_entry_output_is_directory=single_entry_output_is_directory,
    )
    if tree is not None:
        console_err.print(panel("Recovered files", tree))


def print_mint_summary(result: MintResult, *, quiet: bool) -> None:
    if quiet:
        return
    console.print()
    console.print(
        panel(
            "Outputs",
            build_mint_outputs_tree(result.shard_paths, result.signing_key_shard_paths),
        )
    )
    console.print(
        panel(
            "Mint summary",
            build_kv_table(
                [
                    ("Output", result.output_dir),
                    ("Signing authority", result.signing_key_source),
                    *_mint_target_rows(result),
                ]
            ),
        )
    )
    if result.notes:
        console.print(panel("Advisory", "\n".join(f"- {note}" for note in result.notes)))


def format_auth_status(status: str, *, allow_unsigned: bool) -> str:
    if status == "verified":
        return "verified"
    if status == "skipped":
        return "skipped (unsigned recovery)"
    if status == "ignored":
        return "failed (ignored during unsigned recovery)"
    if status == "invalid":
        return "invalid (ignored during unsigned recovery)" if allow_unsigned else "invalid"
    if status == "missing":
        return "skipped (unsigned recovery)" if allow_unsigned else "missing"
    return status
