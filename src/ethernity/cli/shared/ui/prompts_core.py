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

import questionary
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from questionary import utils
from questionary.constants import DEFAULT_SELECTED_POINTER
from questionary.prompts import common
from questionary.prompts.common import InquirerControl
from questionary.question import Question
from questionary.styles import merge_styles_default
from rich.rule import Rule
from rich.text import Text

from ethernity.cli.shared.ui.renderables import hint_box
from ethernity.cli.shared.ui.runtime import clear_screen
from ethernity.cli.shared.ui.state import UIContext, get_context

QUESTIONARY_STYLE = questionary.Style(
    [
        ("question", "bold"),
        ("answer", "bold"),
        ("pointer", "fg:ansicyan bold"),
        ("highlighted", "fg:ansicyan bold"),
        ("separator", "fg:ansibrightblack bold"),
        ("instruction", "fg:ansibrightblack"),
    ]
)

DEFAULT_CONTEXT = get_context()
console = DEFAULT_CONTEXT.console
console_err = DEFAULT_CONTEXT.console_err


def _resolve_context(context: UIContext | None) -> UIContext:
    return context or DEFAULT_CONTEXT


def _ask_question(question: object):
    unsafe_ask = getattr(question, "unsafe_ask", None)
    if callable(unsafe_ask):
        return unsafe_ask()
    ask = getattr(question, "ask")
    return ask()


def print_prompt_header(
    prompt: str,
    help_text: str | None,
    *,
    context: UIContext | None = None,
) -> None:
    context = _resolve_context(context)
    if context.screen_mode:
        if context.stage_prompt_count > 0:
            clear_screen(context=context)
            _print_screen_prompt_context(help_text, context=context)
        elif context.current_substep_title is not None:
            _print_initial_screen_prompt_context(help_text, context=context)
        elif help_text and context.current_stage_title is None:
            context.console.print(hint_box([help_text]))
        context.console.print(Text(f"{prompt}\n", style="bold"))
        context.stage_prompt_count += 1
        return
    output = context.console
    output.print(Rule(style="rule"))
    if help_text:
        output.print(hint_box([help_text]))
    context.stage_prompt_count += 1


def _print_screen_prompt_context(
    help_text: str | None,
    *,
    context: UIContext,
) -> None:
    output = context.console
    state = context.wizard_state
    if state is not None and context.current_stage_title:
        step = max(state.step, 1)
        step_label = f"Step {step} of {state.total_steps}: {context.current_stage_title}"
        output.print(Text(step_label, style="title"))
    elif context.current_stage_title:
        output.print(Text(context.current_stage_title, style="title"))
    if context.current_stage_density == "dense" and context.current_substep_title:
        output.print(Text(context.current_substep_title, style="accent"))

    hint_text: str | None = None
    if help_text:
        hint_text = help_text
    elif context.current_stage_density == "dense":
        hint_text = context.current_substep_help_text or context.current_stage_help_text

    if hint_text:
        output.print(hint_box([hint_text]))


def _print_initial_screen_prompt_context(
    help_text: str | None,
    *,
    context: UIContext,
) -> None:
    output = context.console
    if context.current_stage_density == "dense" and context.current_substep_title:
        output.print(Text(context.current_substep_title, style="accent"))

    hint_text: str | None = None
    if help_text:
        hint_text = help_text
    elif context.current_stage_density == "dense":
        hint_text = context.current_substep_help_text or context.current_stage_help_text

    if hint_text:
        output.print(hint_box([hint_text]))


def _question_message(prompt: str, *, context: UIContext) -> str:
    if context.screen_mode:
        return ""
    return prompt


def prompt_optional_secret(
    prompt: str,
    *,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str | None:
    context = _resolve_context(context)
    print_prompt_header(prompt, help_text, context=context)
    value = _ask_question(
        questionary.password(
            _question_message(prompt, context=context),
            qmark="",
            style=QUESTIONARY_STYLE,
        )
    )
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
        value = _ask_question(
            questionary.password(
                _question_message(prompt, context=context),
                qmark="",
                style=QUESTIONARY_STYLE,
            )
        )
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
    context = _resolve_context(context)
    print_prompt_header(prompt, help_text, context=context)
    value = _ask_question(
        questionary.confirm(
            _question_message(prompt, context=context),
            default=default,
            qmark="",
            style=QUESTIONARY_STYLE,
        )
    )
    if value is None:
        raise KeyboardInterrupt
    return value


def prompt_choice_list(
    items: Sequence[tuple[str, str] | questionary.Separator | questionary.Choice],
    *,
    default: str | None,
    title: str | None = None,
    help_text: str | None = None,
    context: UIContext | None = None,
) -> str:
    context = _resolve_context(context)
    items = list(items)
    if not items:
        raise ValueError("A list of choices needs to be provided.")
    choices = [
        item
        if isinstance(item, (questionary.Separator, questionary.Choice))
        else questionary.Choice(title=item[1], value=item[0])
        for item in items
    ]
    print_prompt_header(title or "Select an option", help_text, context=context)
    value = _select_with_initial_choice(
        _question_message(title or "Select an option", context=context),
        choices=choices,
        initial_choice=default,
        qmark="",
        style=QUESTIONARY_STYLE,
        show_navigation_hint=not context.screen_mode or not context.choice_navigation_hint_seen,
    )
    if context.screen_mode:
        context.choice_navigation_hint_seen = True
    value = _ask_question(value)
    if value is None:
        raise KeyboardInterrupt
    return value


def _select_with_initial_choice(
    message: str,
    *,
    choices: Sequence[questionary.Choice],
    initial_choice: str | None,
    qmark: str,
    style,
    show_navigation_hint: bool,
):
    merged_style = merge_styles_default([style])
    ic = _EthernityInquirerControl(
        choices,
        default=None,
        pointer=DEFAULT_SELECTED_POINTER,
        use_indicator=False,
        use_shortcuts=False,
        show_selected=False,
        show_description=True,
        use_arrow_keys=True,
        initial_choice=initial_choice,
    )

    def get_prompt_tokens():
        tokens = []
        if qmark:
            tokens.append(("class:qmark", qmark))
        if message:
            tokens.append(("class:question", f" {message} "))
        if ic.is_answered and message:
            current = ic.get_pointed_at()
            if isinstance(current.title, list):
                tokens.append(("class:answer", "".join(token[1] for token in current.title)))
            else:
                tokens.append(("class:answer", current.title or ""))
        elif show_navigation_hint:
            tokens.append(("class:instruction", "(Arrows/j/k)"))
        return tokens

    layout = common.create_inquirer_layout(ic, get_prompt_tokens)
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _cancel(event):
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    def move_cursor_down(_event):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    def move_cursor_up(_event):
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
    def _set_answer(event):
        ic.is_answered = True
        event.app.exit(result=ic.get_pointed_at().value)

    @bindings.add(Keys.Any)
    def _other(_event):
        return None

    return Question(
        Application(
            layout=layout,
            key_bindings=bindings,
            style=merged_style,
            **utils.used_kwargs({}, Application.__init__),
        )
    )


class _EthernityInquirerControl(InquirerControl):
    def _get_choice_tokens(self):
        tokens = super()._get_choice_tokens()
        current = self.get_pointed_at()
        if current.description is None or not tokens:
            return tokens
        last_style, last_text = tokens[-1]
        if last_text.startswith("  Description: "):
            tokens[-1] = ("class:instruction", f"  {current.description}")
        else:
            tokens.append(("", "\n"))
            tokens.append(("class:instruction", f"  {current.description}"))
        return tokens


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
        raw = _ask_question(
            questionary.text(
                _question_message(prompt, context=context),
                qmark="",
                style=QUESTIONARY_STYLE,
            )
        )
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
    context = _resolve_context(context)
    print_prompt_header(prompt, help_text, context=context)
    value = _ask_question(
        questionary.text(
            _question_message(prompt, context=context),
            qmark="",
            style=QUESTIONARY_STYLE,
        )
    )
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
        value = _ask_question(
            questionary.text(
                _question_message(prompt, context=context),
                qmark="",
                style=QUESTIONARY_STYLE,
            )
        )
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
    context = _resolve_context(context)
    print_prompt_header(prompt, help_text, context=context)
    items: list[str] = []
    while True:
        line = _ask_question(
            questionary.text(
                _question_message(prompt, context=context),
                qmark="",
                style=QUESTIONARY_STYLE,
            )
        )
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
