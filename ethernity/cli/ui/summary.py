#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from . import (
    console,
    console_err,
    _build_kv_table,
    _build_outputs_tree,
    _build_recovered_tree,
    _panel,
)

if TYPE_CHECKING:
    from ..core.types import BackupResult
    from ...core.models import DocumentPlan


def _print_backup_summary(
    result: BackupResult,
    plan: DocumentPlan,
    passphrase: str | None,
    *,
    quiet: bool,
) -> None:
    if quiet:
        return
    console.print()
    console.print(
        _panel(
            "Outputs",
            _build_outputs_tree(
                result.qr_path,
                result.recovery_path,
                result.shard_paths,
                result.signing_key_shard_paths,
            ),
        )
    )


def _print_recover_summary(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    auth_status: str | None,
    quiet: bool,
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
    console_err.print(_panel("Recovery summary", _build_kv_table(rows)))
    tree = _build_recovered_tree(entries, output_path)
    if tree is not None:
        console_err.print(_panel("Recovered files", tree))


def _format_auth_status(status: str, *, allow_unsigned: bool) -> str:
    if status == "verified":
        return "verified"
    if status == "missing":
        return "missing (allowed)" if allow_unsigned else "missing"
    if status == "ignored":
        return "invalid (ignored)"
    return status
