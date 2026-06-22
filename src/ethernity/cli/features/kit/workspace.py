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

"""Guided workspace for printing the recovery kit sheet."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity.cli.features.kit.workflow import DEFAULT_KIT_CHUNK_SIZE, DEFAULT_KIT_OUTPUT
from ethernity.cli.shared.ui_api import (
    WorkspaceSection,
    build_review_table,
    console,
    panel,
    print_workspace,
    prompt_choice,
    prompt_int,
    prompt_optional_path_with_picker,
    prompt_workspace_action,
    prompt_yes_no,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
    wizard_substep,
)


@dataclass(frozen=True)
class KitWorkspaceArgs:
    bundle: Path | None
    output: Path | None
    config: str | None
    paper: str | None
    design: str | None
    variant: str
    qr_chunk_size: int | None
    quiet: bool


@dataclass
class _KitState:
    config: str | None
    paper: str | None
    design: str | None
    quiet: bool
    bundle: Path | None = None
    output: Path | None = None
    variant: str = "lean"
    qr_chunk_size: int | None = None


def prompt_print_kit_workspace_args(
    *,
    config: str | None,
    paper: str | None,
    design: str | None,
    quiet: bool,
) -> KitWorkspaceArgs | None:
    """Prompt for recovery-kit rendering using a guided task workspace."""

    state = _KitState(config=config, paper=paper, design=design, quiet=quiet)
    with ui_screen_mode(quiet=quiet):
        with wizard_flow(name="Print recovery kit", total_steps=1, quiet=quiet):
            with wizard_stage("Print recovery kit sheet"):
                while True:
                    sections = _workspace_sections(state)
                    print_workspace("Print recovery kit sheet", sections, quiet=quiet)
                    action = prompt_workspace_action(
                        "Choose next step",
                        sections,
                        proceed_label="Review and print kit",
                        help_text=(
                            "Choose where the kit PDF should be saved, then review before "
                            "rendering it."
                        ),
                    )
                    if action == "cancel":
                        console.print("Recovery kit cancelled.")
                        return None
                    if action == "output":
                        _prompt_output(state)
                        continue
                    if action == "contents":
                        _prompt_contents(state)
                        continue
                    if action == "layout":
                        _prompt_layout(state)
                        continue
                    if action != "review":
                        continue

                    args = _build_args(state)
                    if _confirm_review(args):
                        return args


def _workspace_sections(state: _KitState) -> list[WorkspaceSection]:
    return [
        WorkspaceSection(
            key="output",
            title="Output PDF",
            status="ready",
            summary=_output_summary(state),
            action_label="Choose output PDF",
        ),
        WorkspaceSection(
            key="contents",
            title="Kit contents",
            status="ready",
            summary=_contents_summary(state),
            action_label="Choose kit contents",
        ),
        WorkspaceSection(
            key="layout",
            title="Layout",
            status="ready",
            summary=_layout_summary(state),
            action_label="Choose layout",
        ),
    ]


def _output_summary(state: _KitState) -> str:
    return str(state.output) if state.output else f"default ({DEFAULT_KIT_OUTPUT})"


def _contents_summary(state: _KitState) -> str:
    bundle = "custom bundle" if state.bundle else "built-in bundle"
    chunk = state.qr_chunk_size or DEFAULT_KIT_CHUNK_SIZE
    return f"{state.variant} variant, {bundle}, QR payload chunks up to {chunk} bytes"


def _layout_summary(state: _KitState) -> str:
    parts = [state.paper or "configured paper"]
    if state.design:
        parts.append(state.design)
    else:
        parts.append("configured design")
    if state.config:
        parts.append(f"config: {state.config}")
    return ", ".join(parts)


def _prompt_output(state: _KitState) -> None:
    with wizard_substep("Choose output PDF"):
        output = prompt_optional_path_with_picker(
            "Output PDF path",
            kind="file",
            allow_new=True,
            help_text=f"Leave blank to use {DEFAULT_KIT_OUTPUT}.",
            picker_prompt="Select output PDF",
            picker_help_text="Choose an existing file path or enter a new PDF path manually.",
            picker_id="kit-output",
        )
    state.output = Path(output) if output else None


def _prompt_contents(state: _KitState) -> None:
    with wizard_substep("Kit variant"):
        state.variant = prompt_choice(
            "Recovery kit variant",
            {
                "lean": "Lean kit (recommended)",
                "scanner": "Scanner kit with camera scanning",
            },
            default=state.variant,
            help_text="The scanner variant is larger but can scan QR codes in the browser.",
        )
    with wizard_substep("Kit bundle"):
        bundle_mode = prompt_choice(
            "Kit bundle source",
            {
                "built-in": "Use built-in recovery kit bundle",
                "custom": "Use a custom HTML bundle",
            },
            default="custom" if state.bundle else "built-in",
            help_text="Use a custom bundle only when testing or packaging a replacement kit.",
        )
    if bundle_mode == "custom":
        bundle = prompt_optional_path_with_picker(
            "Custom bundle HTML",
            kind="file",
            help_text="Choose the recovery kit HTML bundle to encode.",
            picker_prompt="Select recovery kit bundle",
            picker_help_text="Choose a bundle HTML file.",
            picker_id="kit-bundle",
        )
        state.bundle = Path(bundle) if bundle else None
    else:
        state.bundle = None
    with wizard_substep("QR size"):
        chunk_mode = prompt_choice(
            "QR payload chunk size",
            {
                "auto": "Use automatic size",
                "custom": "Choose a custom size",
            },
            default="custom" if state.qr_chunk_size is not None else "auto",
            help_text="Smaller chunks create more QR codes but can scan more reliably.",
        )
    if chunk_mode == "custom":
        state.qr_chunk_size = prompt_int(
            "QR payload bytes per code",
            minimum=1,
            help_text=f"Default is {DEFAULT_KIT_CHUNK_SIZE} bytes.",
        )
    else:
        state.qr_chunk_size = None


def _prompt_layout(state: _KitState) -> None:
    with wizard_substep("Paper size"):
        paper = prompt_choice(
            "Paper size",
            {
                "configured": "Use configured paper size",
                "A4": "A4",
                "LETTER": "Letter",
            },
            default=state.paper or "configured",
            help_text="Use the configured paper size unless this print job needs an override.",
        )
    state.paper = None if paper == "configured" else paper


def _build_args(state: _KitState) -> KitWorkspaceArgs:
    return KitWorkspaceArgs(
        bundle=state.bundle,
        output=state.output,
        config=state.config,
        paper=state.paper,
        design=state.design,
        variant=state.variant,
        qr_chunk_size=state.qr_chunk_size,
        quiet=state.quiet,
    )


def _confirm_review(args: KitWorkspaceArgs) -> bool:
    rows = [
        ("Output PDF", str(args.output) if args.output else DEFAULT_KIT_OUTPUT),
        ("Variant", args.variant),
        ("Bundle", str(args.bundle) if args.bundle else "built-in"),
        (
            "QR chunk size",
            str(args.qr_chunk_size) if args.qr_chunk_size is not None else "automatic",
        ),
        ("Paper size", args.paper or "configured"),
        ("Design", args.design or "configured"),
    ]
    if args.config:
        rows.append(("Config", args.config))
    console.print(panel("Review recovery kit", build_review_table(rows)))
    return prompt_yes_no(
        "Print this recovery kit sheet",
        default=True,
        help_text="Select no to return to the workspace without rendering.",
    )


__all__ = ["KitWorkspaceArgs", "prompt_print_kit_workspace_args"]
