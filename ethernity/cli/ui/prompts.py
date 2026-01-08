#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import questionary
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

from . import state as ui_state

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

console = ui_state.console
console_err = ui_state.console_err


def _print_prompt_header(prompt: str, help_text: str | None) -> None:
    if ui_state.PROMPT_STYLE == "compact":
        console.print(Padding(Text(prompt, style="accent"), (0, 0, 0, 1)))
        if help_text:
            console.print(Padding(ui_state._format_hint(help_text), (0, 0, 0, 2)))
        return
    console.print(Rule(style="rule"))
    console.print(Text(prompt, style="title"))
    if help_text:
        console.print(Padding(ui_state._format_hint(help_text), (0, 0, 0, 1)))


def _prompt_optional_secret(prompt: str, *, help_text: str | None = None) -> str | None:
    _print_prompt_header(prompt, help_text)
    value = questionary.password(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
    if value is None:
        raise KeyboardInterrupt
    return value or None


def _prompt_required_secret(prompt: str, *, help_text: str | None = None) -> str:
    _print_prompt_header(prompt, help_text)
    while True:
        value = questionary.password(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if value is None:
            raise KeyboardInterrupt
        if value:
            return value
        console_err.print("[red]Passphrase cannot be empty.[/red]")


def _prompt_choice(
    prompt: str,
    choices: dict[str, str],
    *,
    default: str | None = None,
    help_text: str | None = None,
) -> str:
    items = list(choices.items())
    return _prompt_choice_list(
        items,
        default=default,
        title=prompt,
        help_text=help_text,
    )


def _prompt_yes_no(prompt: str, *, default: bool, help_text: str | None = None) -> bool:
    _print_prompt_header(prompt, help_text)
    value = questionary.confirm(
        prompt,
        default=default,
        qmark="",
        style=QUESTIONARY_STYLE,
    ).ask()
    if value is None:
        raise KeyboardInterrupt
    return value


def _prompt_choice_list(
    items: Sequence[tuple[str, str]],
    *,
    default: str | None,
    title: str | None = None,
    help_text: str | None = None,
) -> str:
    items = list(items)
    choices = [questionary.Choice(title=label, value=key) for key, label in items]
    if help_text:
        console.print(Padding(ui_state._format_hint(help_text), (0, 0, 0, 1)))
    value = questionary.select(
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


def _prompt_int(prompt: str, *, minimum: int = 1, help_text: str | None = None) -> int:
    if help_text is None:
        help_text = f"Enter a whole number >= {minimum}."
    _print_prompt_header(prompt, help_text)
    while True:
        raw = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if raw is None:
            raise KeyboardInterrupt
        if not raw.strip():
            console_err.print("[red]This value is required.[/red]")
            continue
        try:
            value = int(raw)
        except ValueError:
            console_err.print("[red]Enter a whole number.[/red]")
            continue
        if value < minimum:
            console_err.print(f"[red]Value must be >= {minimum}.[/red]")
            continue
        return value


def _prompt_optional(prompt: str, *, help_text: str | None = None) -> str | None:
    _print_prompt_header(prompt, help_text)
    value = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
    if value is None:
        raise KeyboardInterrupt
    return value.strip() or None


def _prompt_required(prompt: str, *, help_text: str | None = None) -> str:
    _print_prompt_header(prompt, help_text)
    while True:
        value = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if value is None:
            raise KeyboardInterrupt
        if value.strip():
            return value.strip()
        console_err.print("[red]This value is required.[/red]")


def _prompt_multiline(prompt: str, *, help_text: str | None = None) -> list[str]:
    _print_prompt_header(prompt, help_text)
    items: list[str] = []
    while True:
        line = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if line is None:
            raise KeyboardInterrupt
        if not line.strip():
            break
        items.append(line.strip())
    return items


def _validate_path(value: str, *, kind: str) -> str | None:
    path = Path(value).expanduser()
    if not path.exists():
        return f"{kind} not found: {path}"
    if kind == "file" and not path.is_file():
        return f"path is not a file: {path}"
    if kind == "dir" and not path.is_dir():
        return f"path is not a directory: {path}"
    if kind == "path" and not (path.is_file() or path.is_dir()):
        return f"path is not a file or directory: {path}"
    return None


def _prompt_optional_path(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
) -> str | None:
    while True:
        value = _prompt_optional(prompt, help_text=help_text)
        if not value:
            return None
        error = _validate_path(value, kind=kind)
        if error:
            console_err.print(f"[error]{error}[/error]")
            continue
        return value


def _prompt_required_path(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_stdin: bool = False,
) -> str:
    while True:
        value = _prompt_required(prompt, help_text=help_text)
        if allow_stdin and value == "-":
            return value
        error = _validate_path(value, kind=kind)
        if error:
            console_err.print(f"[error]{error}[/error]")
            continue
        return value


def _prompt_required_paths(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_stdin: bool = False,
    empty_message: str | None = None,
    stdin_message: str | None = None,
) -> list[str]:
    if empty_message is None:
        empty_message = "At least one path is required."
    if stdin_message is None:
        stdin_message = "Stdin input is not supported here."
    while True:
        values = _prompt_multiline(prompt, help_text=help_text)
        if not values:
            console_err.print(f"[error]{empty_message}[/error]")
            continue
        if not allow_stdin and "-" in values:
            console_err.print(f"[error]{stdin_message}[/error]")
            continue
        invalid_paths: list[str] = []
        for value in values:
            if allow_stdin and value == "-":
                continue
            error = _validate_path(value, kind=kind)
            if error:
                invalid_paths.append(error)
        if invalid_paths:
            for message in invalid_paths:
                console_err.print(f"[error]{message}[/error]")
            continue
        return values
