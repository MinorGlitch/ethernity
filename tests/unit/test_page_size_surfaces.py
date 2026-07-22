from __future__ import annotations

import click

from ethernity.app import workflow_presenter
from ethernity.app.input_parsers import parse_layout
from ethernity.app.workspaces.common import PAPER_OPTIONS
from ethernity.page_sizes import paper_size_display_name, paper_size_names
from ethernity.run.commands.add_files import add_files
from ethernity.run.commands.backup import backup
from ethernity.run.commands.kit import print_kit
from ethernity.run.commands.rebuild import rebuild
from ethernity.run.commands.replace_recovery_docs import replace_recovery_docs


def _paper_choices(command: click.Command) -> tuple[str, ...]:
    option = next(parameter for parameter in command.params if parameter.name == "paper_size")
    assert isinstance(option.type, click.Choice)
    return tuple(str(choice) for choice in option.type.choices)


def test_run_commands_expose_registered_paper_sizes_in_registry_order() -> None:
    expected = paper_size_names()

    for command in (backup, add_files, rebuild, replace_recovery_docs, print_kit):
        assert _paper_choices(command) == expected


def test_app_paper_options_follow_the_registry_with_existing_labels() -> None:
    expected_names = paper_size_names()
    options = workflow_presenter._paper_size_options()

    assert PAPER_OPTIONS == expected_names
    assert tuple((option.key, option.label) for option in options) == tuple(
        (paper_size, paper_size_display_name(paper_size)) for paper_size in expected_names
    )


def test_layout_parser_recognizes_every_registered_paper_size_case_insensitively() -> None:
    for paper_size in paper_size_names():
        assert parse_layout(
            f"{paper_size.lower()} forge",
            fallback=("A4", "sentinel"),
        ) == (paper_size, "forge")
