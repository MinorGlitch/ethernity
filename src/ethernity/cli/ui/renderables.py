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

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .runtime import console, console_err


def build_kv_table(rows: Sequence[tuple[str, str]], *, title: str | None = None) -> Table:
    table = Table(title=title, show_header=False, box=box.SIMPLE, show_lines=False)
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def build_review_table(rows: Sequence[tuple[str, str | None]]) -> Table:
    table = Table(show_header=False, box=box.MINIMAL, show_lines=False, pad_edge=False)
    table.add_column("Field", style="muted", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        if value is None:
            table.add_row(Text(str(key), style="accent"), Text(""), end_section=True)
            continue
        table.add_row(str(key), str(value))
    return table


def build_action_list(items: Sequence[str]) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column()
    for item in items:
        table.add_row("-", Text(item))
    return table


def build_list_table(title: str, items: Sequence[str]) -> Table:
    table = Table(title=title, show_header=False, box=box.ASCII)
    table.add_column("Value")
    for item in items:
        table.add_row(str(item))
    return table


def panel(title: str, renderable, *, style: str = "panel") -> Panel:
    return Panel(
        renderable,
        title=title,
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def print_completion_panel(
    title: str,
    items: Sequence[str],
    *,
    quiet: bool,
    use_err: bool = False,
) -> None:
    if quiet:
        return
    output = console_err if use_err else console
    output.print(panel(title, build_action_list(items), style="success"))


def build_outputs_tree(
    qr_path: str,
    recovery_path: str,
    shard_paths: Sequence[str],
    signing_key_shard_paths: Sequence[str],
    kit_index_path: str | None = None,
) -> Tree:
    tree = Tree("Documents", guide_style="muted")
    tree.add(f"[accent]QR document[/accent] {qr_path}")
    tree.add(f"[accent]Recovery document[/accent] {recovery_path}")
    if kit_index_path:
        tree.add(f"[accent]Recovery kit index[/accent] {kit_index_path}")
    if shard_paths:
        shards = tree.add(f"[accent]Shard documents[/accent] ({len(shard_paths)})")
        for path in shard_paths:
            shards.add(path)
    if signing_key_shard_paths:
        shards = tree.add(
            f"[accent]Signing-key shard documents[/accent] ({len(signing_key_shard_paths)})"
        )
        for path in signing_key_shard_paths:
            shards.add(path)
    return tree


def build_recovered_tree(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    single_entry_output_is_directory: bool = False,
) -> Tree | None:
    if not output_path:
        return None
    if len(entries) == 1 and not single_entry_output_is_directory:
        tree = Tree("Output file", guide_style="muted")
        tree.add(output_path)
        return tree
    tree = Tree(output_path, guide_style="muted")
    for entry, _data in entries:
        rel = getattr(entry, "path", "payload.bin")
        tree.add(rel)
    return tree
