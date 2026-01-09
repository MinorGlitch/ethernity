#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import questionary
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

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
    if context.prompt_style == "compact":
        output.print(Padding(Text(prompt, style="accent"), (0, 0, 0, 1)))
        if help_text:
            output.print(Padding(format_hint(help_text), (0, 0, 0, 2)))
        return
    output.print(Rule(style="rule"))
    output.print(Text(prompt, style="title"))
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


def prompt_int(
    prompt: str,
    *,
    minimum: int = 1,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> int:
    context = _resolve_context(context)
    if help_text is None:
        help_text = f"Enter a whole number >= {minimum}."
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
    context: UIContext | None = None,
) -> list[str]:
    print_prompt_header(prompt, help_text, context=context)
    items: list[str] = []
    while True:
        line = questionary.text(prompt, qmark="", style=QUESTIONARY_STYLE).ask()
        if line is None:
            raise KeyboardInterrupt
        if not line.strip():
            break
        items.append(line.strip())
    return items


def validate_path(value: str, *, kind: str) -> str | None:
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


def prompt_optional_path(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str | None:
    context = _resolve_context(context)
    while True:
        value = prompt_optional(prompt, help_text=help_text, context=context)
        if not value:
            return None
        error = validate_path(value, kind=kind)
        if error:
            context.console_err.print(f"[error]{error}[/error]")
            continue
        return value


def prompt_required_path(
    prompt: str,
    *,
    kind: str,
    help_text: str | None = None,
    allow_stdin: bool = False,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    while True:
        value = prompt_required(prompt, help_text=help_text, context=context)
        if allow_stdin and value == "-":
            return value
        error = validate_path(value, kind=kind)
        if error:
            context.console_err.print(f"[error]{error}[/error]")
            continue
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
        values = prompt_multiline(prompt, help_text=help_text, context=context)
        if not values:
            context.console_err.print(f"[error]{empty_message}[/error]")
            continue
        if not allow_stdin and "-" in values:
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
