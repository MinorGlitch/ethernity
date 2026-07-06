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

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, TypeVar, cast

import questionary

from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.ui.prompts_core import (
    _resolve_context,
    prompt_choice,
    prompt_choice_list,
    prompt_multiline,
    prompt_optional,
    prompt_required,
)
from ethernity.cli.shared.ui.state import UIContext

_DEFAULT_PICKER_ID = "default"
_PickerAction = Literal[
    "select",
    "toggle",
    "open",
    "parent",
    "filter",
    "clear_filter",
    "hidden",
    "done",
]


@dataclass(frozen=True)
class _PickerEntry:
    path: Path
    label: str
    is_dir: bool
    selectable: bool


@dataclass
class _PickerState:
    current_dir: Path
    allow_files: bool
    allow_dirs: bool
    include_hidden: bool
    filter_text: str | None = None
    selected: set[str] | None = None


def _picker_dirs(context: UIContext) -> dict[str, str]:
    if context.picker_dirs is None:
        context.picker_dirs = {}
    return context.picker_dirs


def _picker_dir(context: UIContext, picker_id: str | None) -> str:
    key = picker_id or _DEFAULT_PICKER_ID
    return _picker_dirs(context).get(key) or context.last_picker_dir or "."


def _remember_picker_dir(context: UIContext, picker_id: str | None, directory: str) -> None:
    key = picker_id or _DEFAULT_PICKER_ID
    context.last_picker_dir = directory
    _picker_dirs(context)[key] = directory


def _expanded_path(value: str) -> Path:
    return Path(expanduser_cli_path(value, preserve_stdin=False) or "")


def _resolve_picker_directory(directory: str) -> Path:
    error = validate_path(directory, kind="dir")
    if error:
        raise ValueError(error)
    return _expanded_path(directory)


def _entry_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _iter_picker_entries(state: _PickerState) -> list[_PickerEntry]:
    root = _resolve_picker_directory(str(state.current_dir))
    filter_text = (state.filter_text or "").strip().lower()
    entries: list[_PickerEntry] = []
    for entry in sorted(root.iterdir(), key=_entry_sort_key):
        name = entry.name
        if not state.include_hidden and name.startswith("."):
            continue
        if filter_text and filter_text not in name.lower():
            continue
        is_dir = entry.is_dir()
        if is_dir:
            entries.append(
                _PickerEntry(
                    path=entry,
                    label=f"{name}/",
                    is_dir=True,
                    selectable=state.allow_dirs,
                )
            )
            continue
        if not state.allow_files or not entry.is_file():
            continue
        entries.append(
            _PickerEntry(
                path=entry,
                label=name,
                is_dir=False,
                selectable=True,
            )
        )
    return entries


def _choice_value(action: _PickerAction, path: str = "") -> tuple[_PickerAction, str]:
    return action, path


def _selection_marker(path: Path, selected: set[str] | None) -> str:
    if selected is None:
        return "  "
    return "[x]" if str(path) in selected else "[ ]"


def _toggle_selection(selected: set[str], path: str) -> None:
    if path in selected:
        selected.remove(path)
    else:
        selected.add(path)


def _picker_title(prompt: str, state: _PickerState) -> str:
    title = f"{prompt} - {state.current_dir}"
    if state.filter_text:
        title = f"{title} (filter: {state.filter_text})"
    return title


def _prompt_filter(state: _PickerState, *, context: UIContext) -> None:
    value = prompt_optional(
        "Filter entries",
        help_text="Type part of a filename or folder name. Leave blank to clear the filter.",
        context=context,
    )
    state.filter_text = value


def _apply_browser_action(
    action: tuple[_PickerAction, str],
    state: _PickerState,
    *,
    context: UIContext,
) -> str | list[str] | None:
    selected = state.selected
    action_name, value = action
    if action_name == "parent":
        state.current_dir = state.current_dir.parent
        return None
    if action_name == "open":
        state.current_dir = Path(value)
        return None
    if action_name == "filter":
        _prompt_filter(state, context=context)
        return None
    if action_name == "clear_filter":
        state.filter_text = None
        return None
    if action_name == "hidden":
        state.include_hidden = not state.include_hidden
        return None
    if action_name == "toggle":
        if selected is None:
            raise ValueError("internal picker error: missing selection basket")
        _toggle_selection(selected, value)
        return None
    if action_name == "done":
        if selected is None:
            raise ValueError("internal picker error: missing selection basket")
        if not selected:
            context.console_err.print("[error]Select at least one item.[/error]")
            return None
        return sorted(selected)
    if action_name == "select":
        return value
    raise ValueError(f"unknown picker action: {action_name}")


def _single_picker_choices(
    state: _PickerState,
) -> list[tuple[str, str] | questionary.Separator | questionary.Choice]:
    choices: list[tuple[str, str] | questionary.Separator | questionary.Choice] = []
    if state.allow_dirs:
        choices.append(
            questionary.Choice(
                "Choose this folder",
                value=_choice_value("select", str(state.current_dir)),
                description=str(state.current_dir),
            )
        )
    choices.extend(_navigation_choices(state))
    entries = _iter_picker_entries(state)
    if entries:
        choices.append(questionary.Separator(" "))
        choices.append(questionary.Separator("Entries"))
    for entry in entries:
        if entry.is_dir:
            choices.append(
                questionary.Choice(
                    entry.label,
                    value=_choice_value("open", str(entry.path)),
                    description="Open folder",
                )
            )
            continue
        choices.append(
            questionary.Choice(
                entry.label,
                value=_choice_value("select", str(entry.path)),
                description=str(entry.path),
            )
        )
    if not entries:
        choices.append(questionary.Separator("No matching entries"))
    return choices


def _multi_picker_choices(
    state: _PickerState,
) -> list[tuple[str, str] | questionary.Separator | questionary.Choice]:
    selected = state.selected or set()
    choices: list[tuple[str, str] | questionary.Separator | questionary.Choice] = []
    if selected:
        choices.append(
            questionary.Choice(
                f"Done ({len(selected)} selected)",
                value=_choice_value("done"),
            )
        )
        choices.append(questionary.Separator(" "))
    if state.allow_dirs:
        marker = _selection_marker(state.current_dir, selected)
        choices.append(
            questionary.Choice(
                f"{marker} Add/remove this folder",
                value=_choice_value("toggle", str(state.current_dir)),
                description=str(state.current_dir),
            )
        )
    choices.extend(_navigation_choices(state))
    entries = _iter_picker_entries(state)
    if entries:
        choices.append(questionary.Separator(" "))
        choices.append(questionary.Separator("Entries"))
    for entry in entries:
        marker = _selection_marker(entry.path, selected)
        if entry.is_dir:
            choices.append(
                questionary.Choice(
                    f"Open {entry.label}",
                    value=_choice_value("open", str(entry.path)),
                    description="Open folder",
                )
            )
            if entry.selectable:
                choices.append(
                    questionary.Choice(
                        f"{marker} {entry.label}",
                        value=_choice_value("toggle", str(entry.path)),
                        description="Add or remove folder",
                    )
                )
            continue
        choices.append(
            questionary.Choice(
                f"{marker} {entry.label}",
                value=_choice_value("toggle", str(entry.path)),
                description=str(entry.path),
            )
        )
    if not entries:
        choices.append(questionary.Separator("No matching entries"))
    return choices


def _navigation_choices(
    state: _PickerState,
) -> list[tuple[str, str] | questionary.Separator | questionary.Choice]:
    hidden_label = "Hide hidden files" if state.include_hidden else "Show hidden files"
    filter_label = "Change filter" if state.filter_text else "Search/filter entries"
    choices: list[tuple[str, str] | questionary.Separator | questionary.Choice] = [
        questionary.Choice(
            "Open parent folder",
            value=_choice_value("parent"),
            description=str(state.current_dir.parent),
        ),
        questionary.Choice(filter_label, value=_choice_value("filter")),
        questionary.Choice(hidden_label, value=_choice_value("hidden")),
    ]
    if state.filter_text:
        choices.append(questionary.Choice("Clear filter", value=_choice_value("clear_filter")))
    return choices


def _browse_paths(
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
    state = _PickerState(
        current_dir=_resolve_picker_directory(directory),
        allow_files=allow_files,
        allow_dirs=allow_dirs,
        include_hidden=include_hidden,
        selected=set() if multi else None,
    )
    while True:
        choices = _multi_picker_choices(state) if multi else _single_picker_choices(state)
        value = prompt_choice_list(
            choices,
            default=None,
            title=_picker_title(prompt, state),
            help_text=help_text,
            context=context,
        )
        result = _apply_browser_action(
            cast(tuple[_PickerAction, str], value),
            state,
            context=context,
        )
        if result is not None:
            return result


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
    context: UIContext,
    select_func: Callable[[str], T],
    manual_func: Callable[[], T],
    picker_id: str | None = None,
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
            directory = prompt_optional_path(
                directory_prompt,
                kind="dir",
                help_text=directory_help_text,
                context=context,
            )
            directory = directory or _picker_dir(context, picker_id)
            try:
                selected = select_func(directory)
                _remember_picker_directory(context, selected)
                _remember_picker_dir(context, picker_id, context.last_picker_dir)
                return selected
            except ValueError as exc:
                context.console_err.print(f"[error]{exc}[/error]")
                continue
        manual_value = manual_func()
        _remember_picker_directory(context, manual_value)
        _remember_picker_dir(context, picker_id, context.last_picker_dir)
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
    return _browse_paths(
        prompt,
        directory=directory,
        allow_files=allow_files,
        allow_dirs=allow_dirs,
        include_hidden=include_hidden,
        help_text=help_text,
        multi=multi,
        context=context,
    )


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
    picker_id: str | None = None,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    if directory_help_text is None:
        directory_help_text = "Pick the folder to list for selection."
    if picker_help_text is None:
        picker_help_text = "Use arrow keys, j/k, or Ctrl-N/Ctrl-P to choose an entry."
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
        context=context,
        select_func=_select,
        manual_func=_manual,
        picker_id=picker_id or prompt,
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
    picker_id: str | None = None,
    context: UIContext | None = None,
) -> str | None:
    context = _resolve_context(context)
    if directory_help_text is None:
        directory_help_text = "Pick the folder to list for selection."
    if picker_help_text is None:
        picker_help_text = "Use arrow keys, j/k, or Ctrl-N/Ctrl-P to choose an entry."
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
        context=context,
        select_func=_select,
        manual_func=_manual,
        picker_id=picker_id or prompt,
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
    picker_id: str | None = None,
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
        context=context,
        select_func=_select,
        manual_func=_manual,
        picker_id=picker_id or manual_prompt,
    )
