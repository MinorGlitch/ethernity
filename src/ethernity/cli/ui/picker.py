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

from pathlib import Path
from typing import Callable, TypeVar, cast

import questionary
from rich.padding import Padding

from ..core.paths import expanduser_cli_path
from .prompts_core import (
    QUESTIONARY_STYLE,
    _ask_question,
    _resolve_context,
    prompt_choice,
    prompt_choice_list,
    prompt_multiline,
    prompt_optional,
    prompt_required,
)
from .state import UIContext, format_hint


def _list_picker_entries(
    directory: str,
    *,
    allow_files: bool,
    allow_dirs: bool,
    include_hidden: bool,
) -> list[tuple[str, str]]:
    error = validate_path(directory, kind="dir")
    if error:
        raise ValueError(error)
    root = Path(expanduser_cli_path(directory, preserve_stdin=False) or "")
    entries: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        name = entry.name
        if not include_hidden and name.startswith("."):
            continue
        is_dir = entry.is_dir()
        if is_dir:
            if not allow_dirs:
                continue
        else:
            if not allow_files or not entry.is_file():
                continue
        label = f"{name}/" if is_dir else name
        entries.append((str(entry), label))
    if not entries:
        raise ValueError(
            f"No selectable entries in {root}. Choose another directory or switch to manual entry."
        )
    return entries


T = TypeVar("T")


def _remember_picker_directory(context: UIContext, value: object) -> None:
    path_value: str | None = None
    if isinstance(value, str):
        path_value = value
    elif isinstance(value, list) and value and isinstance(value[0], str):
        path_value = value[0]
    if path_value is None:
        return
    stripped = path_value.strip()
    if not stripped or stripped == "-":
        return
    path = Path(expanduser_cli_path(stripped, preserve_stdin=False) or "")
    if path.exists() and path.is_dir():
        context.last_picker_dir = str(path)
    else:
        context.last_picker_dir = str(path.parent)


def _run_picker_flow(
    *,
    selection_prompt: str,
    selection_help_text: str | None,
    select_label: str = "Pick from list",
    manual_label: str,
    default_mode: str = "select",
    directory_prompt: str,
    directory_help_text: str,
    picker_help_text: str,
    context: UIContext,
    select_func: Callable[[str], T],
    manual_func: Callable[[], T],
) -> T:
    while True:
        input_mode = prompt_choice(
            selection_prompt,
            {
                "select": select_label,
                "manual": manual_label,
            },
            default=default_mode,
            help_text=selection_help_text,
            context=context,
        )
        if input_mode == "select":
            if picker_help_text:
                context.console.print(Padding(format_hint(picker_help_text), (0, 0, 0, 1)))
            directory = prompt_optional_path(
                directory_prompt,
                kind="dir",
                help_text=directory_help_text,
                context=context,
            )
            directory = directory or context.last_picker_dir or "."
            try:
                selected = select_func(directory)
                _remember_picker_directory(context, selected)
                return selected
            except ValueError as exc:
                context.console_err.print(f"[error]{exc}[/error]")
                continue
        manual_value = manual_func()
        _remember_picker_directory(context, manual_value)
        return manual_value


def _prompt_select_entries(
    prompt: str,
    *,
    directory: str,
    allow_files: bool,
    allow_dirs: bool,
    include_hidden: bool,
    help_text: str | None,
    multi: bool,
    context: UIContext,
) -> str | list[str]:
    entries = _list_picker_entries(
        directory,
        allow_files=allow_files,
        allow_dirs=allow_dirs,
        include_hidden=include_hidden,
    )
    if not multi:
        return prompt_choice_list(
            entries,
            default=None,
            title=prompt,
            help_text=help_text,
            context=context,
        )
    choices = [questionary.Choice(title=label, value=value) for value, label in entries]
    while True:
        if help_text:
            context.console.print(Padding(format_hint(help_text), (0, 0, 0, 1)))
        values = _ask_question(
            questionary.checkbox(
                prompt,
                choices=choices,
                qmark="",
                style=QUESTIONARY_STYLE,
            )
        )
        if values is None:
            raise KeyboardInterrupt
        if values:
            return list(values)
        context.console_err.print("[error]Select at least one item.[/error]")


def prompt_select_paths(
    prompt: str,
    *,
    directory: str,
    allow_files: bool = True,
    allow_dirs: bool = True,
    include_hidden: bool = False,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> list[str]:
    context = _resolve_context(context)
    values = _prompt_select_entries(
        prompt,
        directory=directory,
        allow_files=allow_files,
        allow_dirs=allow_dirs,
        include_hidden=include_hidden,
        help_text=help_text,
        multi=True,
        context=context,
    )
    return cast(list[str], values)


def prompt_select_path(
    prompt: str,
    *,
    directory: str,
    allow_files: bool = True,
    allow_dirs: bool = True,
    include_hidden: bool = False,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    value = _prompt_select_entries(
        prompt,
        directory=directory,
        allow_files=allow_files,
        allow_dirs=allow_dirs,
        include_hidden=include_hidden,
        help_text=help_text,
        multi=False,
        context=context,
    )
    return cast(str, value)


def prompt_path_with_picker(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_stdin: bool = False,
    selection_prompt: str = "Pick from list / Enter path",
    selection_help_text: str | None = None,
    directory_prompt: str = "Directory to list (press Enter for current)",
    directory_help_text: str | None = None,
    picker_prompt: str | None = None,
    picker_help_text: str | None = None,
    include_hidden: bool = False,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    if directory_help_text is None:
        directory_help_text = "Pick the folder to list for selection."
    if picker_help_text is None:
        picker_help_text = "Use arrow keys to choose an entry."
    if picker_prompt is None:
        picker_prompt = "Select a path"

    def _select(directory: str) -> str:
        return prompt_select_path(
            picker_prompt,
            directory=directory,
            allow_files=kind in {"path", "file"},
            allow_dirs=kind in {"path", "dir"},
            include_hidden=include_hidden,
            help_text=picker_help_text,
            context=context,
        )

    def _manual() -> str:
        return prompt_required_path(
            prompt,
            kind=kind,
            help_text=help_text,
            allow_stdin=allow_stdin,
            context=context,
        )

    return _run_picker_flow(
        selection_prompt=selection_prompt,
        selection_help_text=selection_help_text,
        select_label="Pick from list",
        manual_label="Enter path",
        default_mode="select",
        directory_prompt=directory_prompt,
        directory_help_text=directory_help_text,
        picker_help_text=picker_help_text,
        context=context,
        select_func=_select,
        manual_func=_manual,
    )


def prompt_optional_path_with_picker(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_new: bool = False,
    selection_prompt: str = "Pick from list / Enter path",
    selection_help_text: str | None = None,
    directory_prompt: str = "Directory to list (press Enter for current)",
    directory_help_text: str | None = None,
    picker_prompt: str | None = None,
    picker_help_text: str | None = None,
    include_hidden: bool = False,
    context: UIContext | None = None,
) -> str | None:
    context = _resolve_context(context)
    if directory_help_text is None:
        directory_help_text = "Pick the folder to list for selection."
    if picker_help_text is None:
        picker_help_text = "Use arrow keys to choose an entry."
    if picker_prompt is None:
        picker_prompt = "Select a path"

    def _select(directory: str) -> str:
        return prompt_select_path(
            picker_prompt,
            directory=directory,
            allow_files=kind in {"path", "file"},
            allow_dirs=kind in {"path", "dir"},
            include_hidden=include_hidden,
            help_text=picker_help_text,
            context=context,
        )

    def _manual() -> str | None:
        return prompt_optional_path(
            prompt,
            kind=kind,
            help_text=help_text,
            allow_new=allow_new,
            context=context,
        )

    return _run_picker_flow(
        selection_prompt=("Enter path / Pick existing path" if allow_new else selection_prompt),
        selection_help_text=selection_help_text,
        select_label="Pick existing path" if allow_new else "Pick from list",
        manual_label="Enter path",
        default_mode="manual" if allow_new else "select",
        directory_prompt=directory_prompt,
        directory_help_text=directory_help_text,
        picker_help_text=picker_help_text,
        context=context,
        select_func=_select,
        manual_func=_manual,
    )


def validate_path(value: str, *, kind: str, allow_new: bool = False) -> str | None:
    path = Path(expanduser_cli_path(value, preserve_stdin=False) or "")
    if not path.exists():
        if allow_new:
            return None
        return f"{kind} not found: {path}"
    if kind == "file" and not path.is_file():
        return f"path is not a file: {path}"
    if kind == "dir" and not path.is_dir():
        return f"path is not a directory: {path}"
    if kind == "path" and not (path.is_file() or path.is_dir()):
        return f"path is not a file or directory: {path}"
    return None


def _prompt_path(
    prompt: str,
    *,
    kind: str,
    required: bool,
    help_text: str | None,
    allow_stdin: bool = False,
    allow_new: bool = False,
    context: UIContext | None = None,
) -> str | None:
    context = _resolve_context(context)
    while True:
        if required:
            value = prompt_required(prompt, help_text=help_text, context=context)
        else:
            optional_value = prompt_optional(prompt, help_text=help_text, context=context)
            if not optional_value:
                return None
            value = optional_value
        if allow_stdin and value == "-":
            return value
        error = validate_path(value, kind=kind, allow_new=allow_new)
        if error:
            context.console_err.print(f"[error]{error}[/error]")
            continue
        return value


def prompt_optional_path(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_new: bool = False,
    context: UIContext | None = None,
) -> str | None:
    return _prompt_path(
        prompt,
        kind=kind,
        required=False,
        help_text=help_text,
        allow_new=allow_new,
        context=context,
    )


def prompt_required_path(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_stdin: bool = False,
    allow_new: bool = False,
    context: UIContext | None = None,
) -> str:
    value = _prompt_path(
        prompt,
        kind=kind,
        required=True,
        help_text=help_text,
        allow_stdin=allow_stdin,
        allow_new=allow_new,
        context=context,
    )
    if value is None:
        raise KeyboardInterrupt
    return value


def prompt_required_paths(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_stdin: bool = False,
    empty_message: str | None = None,
    stdin_message: str | None = None,
    context: UIContext | None = None,
) -> list[str]:
    context = _resolve_context(context)
    if empty_message is None:
        empty_message = "At least one path is required."
    if stdin_message is None:
        stdin_message = "Stdin input is not supported here."
    while True:
        values = prompt_multiline(
            prompt,
            help_text=help_text,
            stop_on_dash=allow_stdin,
            context=context,
        )
        if not values:
            context.console_err.print(f"[error]{empty_message}[/error]")
            continue
        if "-" in values:
            if allow_stdin:
                if len(values) > 1:
                    context.console_err.print(
                        "[error]Use '-' on its own line to switch to paste mode.[/error]"
                    )
                    continue
                return values
            context.console_err.print(f"[error]{stdin_message}[/error]")
            continue
        invalid_paths: list[str] = []
        for value in values:
            if allow_stdin and value == "-":
                continue
            error = validate_path(value, kind=kind)
            if error:
                invalid_paths.append(error)
        if invalid_paths:
            for message in invalid_paths:
                context.console_err.print(f"[error]{message}[/error]")
            continue
        return values


def prompt_paths_with_picker(
    manual_prompt: str,
    *,
    picker_prompt: str = "Select files or folders",
    selection_prompt: str = "Pick from list / Enter paths",
    selection_help_text: str | None = None,
    kind: str = "path",
    manual_help_text: str | None = None,
    picker_help_text: str | None = None,
    directory_prompt: str = "Directory to list (press Enter for current)",
    directory_help_text: str | None = None,
    allow_stdin: bool = False,
    empty_message: str | None = None,
    stdin_message: str | None = None,
    include_hidden: bool = False,
    context: UIContext | None = None,
) -> list[str]:
    context = _resolve_context(context)
    if manual_help_text is None:
        manual_help_text = "Enter file or directory paths; blank line to finish."
    if picker_help_text is None:
        picker_help_text = "Use space to toggle, Enter to confirm."
    if directory_help_text is None:
        directory_help_text = "Pick the folder to list for selection."

    def _select(directory: str) -> list[str]:
        return prompt_select_paths(
            picker_prompt,
            directory=directory,
            allow_files=kind in {"path", "file"},
            allow_dirs=kind in {"path", "dir"},
            include_hidden=include_hidden,
            help_text=picker_help_text,
            context=context,
        )

    def _manual() -> list[str]:
        return prompt_required_paths(
            manual_prompt,
            help_text=manual_help_text,
            kind=kind,
            allow_stdin=allow_stdin,
            empty_message=empty_message,
            stdin_message=stdin_message,
            context=context,
        )

    return _run_picker_flow(
        selection_prompt=selection_prompt,
        selection_help_text=selection_help_text,
        select_label="Pick from list",
        manual_label="Enter paths",
        default_mode="select",
        directory_prompt=directory_prompt,
        directory_help_text=directory_help_text,
        picker_help_text=picker_help_text,
        context=context,
        select_func=_select,
        manual_func=_manual,
    )
