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
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

import questionary
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from questionary import utils
from questionary.constants import DEFAULT_QUESTION_PREFIX, DEFAULT_SELECTED_POINTER
from questionary.prompts import common
from questionary.prompts.common import Choice, InquirerControl
from questionary.question import Question
from questionary.styles import merge_styles_default
from rich.padding import Padding
from rich.rule import Rule

from .state import UIContext, format_hint, get_context

QUESTIONARY_STYLE = questionary.Style(
    [
        ("question", "bold"),
        ("answer", "bold"),
        ("pointer", "bold"),
        ("highlighted", "reverse"),
        ("selected", "fg:ansibrightblack"),
        ("text", "fg:default bg:default noreverse"),
        ("instruction", "fg:ansibrightblack"),
        ("separator", "fg:ansibrightblack"),
    ]
)

DEFAULT_CONTEXT = get_context()
console = DEFAULT_CONTEXT.console
console_err = DEFAULT_CONTEXT.console_err


def _resolve_context(context: UIContext | None) -> UIContext:
    return context or DEFAULT_CONTEXT


def print_prompt_header(
    prompt: str,
    help_text: str | None,
    *,
    context: UIContext | None = None,
) -> None:
    context = _resolve_context(context)
    output = context.console
    output.print(Rule(style="rule"))
    if help_text:
        output.print(Padding(format_hint(help_text), (0, 0, 0, 1)))


def prompt_optional_secret(
    prompt: str,
    *,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str | None:
    print_prompt_header(prompt, help_text, context=context)
    value = questionary.password(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
    if value is None:
        raise KeyboardInterrupt
    return value or None


def prompt_required_secret(
    prompt: str,
    *,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    print_prompt_header(prompt, help_text, context=context)
    while True:
        value = questionary.password(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if value is None:
            raise KeyboardInterrupt
        if value:
            return value
        context.console_err.print("[red]Passphrase cannot be empty.[/red]")


def prompt_choice(
    prompt: str,
    choices: dict[str, str],
    *,
    default: str | None = None,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    items = list(choices.items())
    return prompt_choice_list(
        items,
        default=default,
        title=prompt,
        help_text=help_text,
        context=context,
    )


def prompt_yes_no(
    prompt: str,
    *,
    default: bool,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> bool:
    print_prompt_header(prompt, help_text, context=context)
    value = questionary.confirm(
        prompt,
        default=default,
        qmark="",
        style=QUESTIONARY_STYLE,
    ).ask()
    if value is None:
        raise KeyboardInterrupt
    return value


def _select_without_default_highlight(
    message: str,
    choices: Sequence[str | Choice | dict[str, Any]],
    default: str | Choice | dict[str, Any] | None,
    *,
    qmark: str = DEFAULT_QUESTION_PREFIX,
    pointer: str | None = DEFAULT_SELECTED_POINTER,
    style: questionary.Style | None = None,
    instruction: str | None = None,
    **kwargs: Any,
) -> Question:
    if not choices:
        raise ValueError("A list of choices needs to be provided.")

    merged_style = merge_styles_default([style])
    ic = InquirerControl(
        choices,
        None,
        pointer=pointer,
        use_indicator=False,
        use_shortcuts=False,
        show_selected=False,
        show_description=True,
        use_arrow_keys=True,
        initial_choice=default,
    )

    def get_prompt_tokens():
        tokens = [("class:qmark", qmark), ("class:question", f" {message} ")]

        if ic.is_answered:
            if isinstance(ic.get_pointed_at().title, list):
                tokens.append(
                    (
                        "class:answer",
                        "".join([token[1] for token in ic.get_pointed_at().title]),
                    )
                )
            else:
                tokens.append(("class:answer", ic.get_pointed_at().title))
        else:
            tokens.append(
                (
                    "class:instruction",
                    instruction or "(Use arrow keys)",
                )
            )

        return tokens

    layout = common.create_inquirer_layout(ic, get_prompt_tokens, **kwargs)

    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _(event):
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    def move_cursor_down(event):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    def move_cursor_up(event):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    bindings.add(Keys.Down, eager=True)(move_cursor_down)
    bindings.add(Keys.Up, eager=True)(move_cursor_up)
    bindings.add("j", eager=True)(move_cursor_down)
    bindings.add("k", eager=True)(move_cursor_up)
    bindings.add(Keys.ControlN, eager=True)(move_cursor_down)
    bindings.add(Keys.ControlP, eager=True)(move_cursor_up)

    @bindings.add(Keys.ControlM, eager=True)
    def set_answer(event):
        ic.is_answered = True
        event.app.exit(result=ic.get_pointed_at().value)

    @bindings.add(Keys.Any)
    def other(event):
        """Disallow inserting other text."""

    return Question(
        Application(
            layout=layout,
            key_bindings=bindings,
            style=merged_style,
            **utils.used_kwargs(kwargs, Application.__init__),
        )
    )


def prompt_choice_list(
    items: Sequence[tuple[str, str]],
    *,
    default: str | None,
    title: str | None = None,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    items = list(items)
    choices = [questionary.Choice(title=label, value=key) for key, label in items]
    if help_text:
        context.console.print(Padding(format_hint(help_text), (0, 0, 0, 1)))
    value = _select_without_default_highlight(
        title or "Select an option",
        choices=choices,
        default=default,
        qmark="",
        pointer=">",
        style=QUESTIONARY_STYLE,
    ).ask()
    if value is None:
        if default is not None:
            return default
        raise KeyboardInterrupt
    return value


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
    root = Path(directory).expanduser()
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
        raise ValueError(f"No entries found in {root}.")
    return entries


T = TypeVar("T")


def _run_picker_flow(
    *,
    selection_prompt: str,
    selection_help_text: str | None,
    manual_label: str,
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
                "select": "Pick from list",
                "manual": manual_label,
            },
            default="select",
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
            directory = directory or "."
            try:
                return select_func(directory)
            except ValueError as exc:
                context.console_err.print(f"[error]{exc}[/error]")
                continue
        return manual_func()


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
        values = questionary.checkbox(
            prompt,
            choices=choices,
            qmark="",
            style=QUESTIONARY_STYLE,
        ).ask()
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
        manual_label="Enter path",
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
        selection_prompt=selection_prompt,
        selection_help_text=selection_help_text,
        manual_label="Enter path",
        directory_prompt=directory_prompt,
        directory_help_text=directory_help_text,
        picker_help_text=picker_help_text,
        context=context,
        select_func=_select,
        manual_func=_manual,
    )


def prompt_int(
    prompt: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> int:
    context = _resolve_context(context)
    if help_text is None:
        if maximum is None:
            help_text = f"Enter a whole number >= {minimum}."
        else:
            help_text = f"Enter a whole number between {minimum} and {maximum}."
    print_prompt_header(prompt, help_text, context=context)
    while True:
        raw = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if raw is None:
            raise KeyboardInterrupt
        if not raw.strip():
            context.console_err.print("[red]This value is required.[/red]")
            continue
        try:
            value = int(raw)
        except ValueError:
            context.console_err.print("[red]Enter a whole number.[/red]")
            continue
        if value < minimum:
            context.console_err.print(f"[red]Value must be >= {minimum}.[/red]")
            continue
        if maximum is not None and value > maximum:
            context.console_err.print(f"[red]Value must be <= {maximum}.[/red]")
            continue
        return value


def prompt_optional(
    prompt: str,
    *,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str | None:
    print_prompt_header(prompt, help_text, context=context)
    value = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
    if value is None:
        raise KeyboardInterrupt
    return value.strip() or None


def prompt_required(
    prompt: str,
    *,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    print_prompt_header(prompt, help_text, context=context)
    while True:
        value = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if value is None:
            raise KeyboardInterrupt
        if value.strip():
            return value.strip()
        context.console_err.print("[red]This value is required.[/red]")


def prompt_multiline(
    prompt: str,
    *,
    help_text: str | None = None,
    stop_on_dash: bool = False,
    context: UIContext | None = None,
) -> list[str]:
    print_prompt_header(prompt, help_text, context=context)
    items: list[str] = []
    while True:
        line = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if line is None:
            raise KeyboardInterrupt
        if not line:
            break
        parts = line.splitlines() if ("\n" in line or "\r" in line) else [line]
        for part in parts:
            stripped = part.strip()
            if not stripped:
                return items
            if stop_on_dash and stripped == "-":
                items.append("-")
                return items
            items.append(stripped)
    return items


def validate_path(value: str, *, kind: str, allow_new: bool = False) -> str | None:
    path = Path(value).expanduser()
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
        manual_label="Enter paths",
        directory_prompt=directory_prompt,
        directory_help_text=directory_help_text,
        picker_help_text=picker_help_text,
        context=context,
        select_func=_select,
        manual_func=_manual,
    )
