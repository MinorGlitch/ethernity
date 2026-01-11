#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence

from ...core.models import DocumentPlan
from ..core.types import BackupResult
from . import (
    build_kv_table,
    build_outputs_tree,
    build_recovered_tree,
    console,
    console_err,
    panel,
)


def print_backup_summary(
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
        panel(
            "Outputs",
            build_outputs_tree(
                result.qr_path,
                result.recovery_path,
                result.shard_paths,
                result.signing_key_shard_paths,
            ),
        )
    )


def print_recover_summary(
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
    console_err.print(panel("Recovery summary", build_kv_table(rows)))
    tree = build_recovered_tree(entries, output_path)
    if tree is not None:
        console_err.print(panel("Recovered files", tree))


def format_auth_status(status: str, *, allow_unsigned: bool) -> str:
    if status == "verified":
        return "verified"
    if status == "missing":
        return "skipped (--skip-auth-check)" if allow_unsigned else "missing"
    if status == "ignored":
        return "failed (check skipped)"
    return status
