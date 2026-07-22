from __future__ import annotations

import asyncio
from pathlib import Path

from textual.color import Color
from textual.widgets import Button, Collapsible, Label, ListView, Select

from ethernity.app.application import EthernityApp
from ethernity.app.help_content import build_help_content
from ethernity.app.navigation import sync_nav_active
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.workspaces.common import SIGNING_KEY_RECOVERY_OPTIONS
from ethernity.page_sizes import paper_size_display_name, paper_size_names
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.presentation.workflow_replace_recovery import (
    replace_signing_key_recovery_summary,
)
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.settings import SettingsTaskState


def test_semantic_action_colors_and_primary_focus_survive_both_themes() -> None:
    async def run() -> None:
        for theme in ("ethernity-dark", "ethernity-light"):
            app = EthernityApp()
            app.theme = theme
            async with app.run_test(size=(80, 24)) as pilot:
                await app.push_screen(
                    ConfirmActionScreen(
                        title="Restore defaults",
                        message="This replaces the current values.",
                        confirm_label="Restore",
                    )
                )
                await pilot.pause()

                cancel = app.screen.query_one("#confirm-action-cancel", Button)
                confirm = app.screen.query_one("#confirm-action-confirm", Button)
                assert cancel.has_class("primary-modal-action")
                assert confirm.has_class("warning-modal-action")
                assert _colors_nearly_equal(
                    confirm.styles.background,
                    Color.parse(app.current_theme.warning),
                )
                assert _colors_nearly_equal(
                    confirm.styles.color,
                    Color.parse(app.current_theme.variables["button-color-foreground"]),
                )

                cancel.focus()
                await pilot.pause()
                assert "underline" in str(cancel.styles.text_style)

                confirm.focus()
                await pilot.pause()
                assert "underline" in str(confirm.styles.text_style)
                assert _colors_nearly_equal(
                    confirm.styles.background,
                    Color.parse(app.current_theme.warning),
                )

    asyncio.run(run())


def test_open_directory_current_folder_confirms_immediately(tmp_path: Path) -> None:
    async def run() -> None:
        results: list[tuple[Path, ...] | None] = []
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose output folder",
                prompt="Choose where documents will be written.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_DIRECTORY,
                multiple=False,
            )
            await app.push_screen(picker, results.append)
            await pilot.pause()

            assert str(picker.query_one("#file-picker-current", Button).label) == "Use folder"
            await pilot.click("#file-picker-current")
            await pilot.pause()

            assert results == [(tmp_path,)]
            assert app.screen is not picker

    asyncio.run(run())


def test_navigation_uses_compact_readable_state_cues() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(160, 32)):
            nav = app.query_one("#nav-list", ListView)
            sync_nav_active(
                nav,
                "backup",
                {
                    "backup": "in-progress",
                    "restore": "ready",
                    "add_files": "attention",
                },
            )

            expected = {
                "backup": ("WIP", "Work in progress"),
                "restore": ("OK", "Ready for final review"),
                "add_files": ("FIX", "Fix required inputs"),
            }
            for task, (cue, tooltip) in expected.items():
                state = nav.query_one(f"#{task} .nav-row-state", Label)
                assert str(state.content) == cue
                assert str(state.tooltip) == tooltip
                assert state.region.width == 3

    asyncio.run(run())


def test_kit_custom_qr_sizing_has_visible_consequence(tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp(
            kit_state=PrintKitTaskState(
                output_path=tmp_path / "kit.pdf",
                chunk_size=384,
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            notice = app.query_one("#kit-qr-warning", InlineNotice)
            panel = app.query_one("#kit-advanced-panel", Collapsible)
            assert notice.display
            assert "page count and make codes harder to scan" in str(notice.content)
            assert panel.has_class("workspace-panel-warning")

    asyncio.run(run())


def test_recovery_copy_does_not_conflate_key_sheets_with_document_signing() -> None:
    state = ReplaceRecoveryDocsTaskState()
    option_labels = tuple(label for label, _value in SIGNING_KEY_RECOVERY_OPTIONS)
    summary = replace_signing_key_recovery_summary(state)
    help_content = build_help_content(task="replace_recovery_docs")
    help_text = "\n".join(
        line for section in help_content.mode.sections for line in (section.body, *section.notes)
    )

    assert "Off - not signed" not in option_labels
    assert summary == "No separate key sheets"
    assert "Replacement documents remain signed" in help_text


def test_help_explains_consequences_without_narrating_controls() -> None:
    all_help = tuple(
        build_help_content(task=task)
        for task in ("restore", "add_files", "rebuild", "replace_recovery_docs", "kit")
    )
    help_text = "\n".join(
        (
            *(
                line
                for content in all_help
                for section in content.mode.sections
                for line in (section.body, *section.notes)
            ),
            *(
                " ".join((*shortcut.keys, shortcut.label))
                for content in all_help
                for shortcut in content.mode.shortcuts
            ),
        )
    )

    assert "Tab Shift+Tab Focus" in help_text
    assert "h l Switch pane" in help_text
    assert "confirm you loaded the latest version" in help_text
    assert "fingerprint printed on the version you trust as latest" in help_text
    assert "Use supplied latest version" not in help_text
    assert "Enter expected fingerprint..." not in help_text
    assert "Use this backup" not in help_text
    assert "Show fingerprint" not in help_text


def test_simple_enum_selects_render_human_labels_without_changing_values(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        app = EthernityApp(
            kit_state=PrintKitTaskState(output_path=tmp_path / "kit.pdf"),
            settings_state=SettingsTaskState(
                config_path=tmp_path / "config.toml",
                values={
                    "render": {"style": "sentinel"},
                    "page": {"size": "LETTER"},
                },
                options={
                    "render_styles": ("sentinel", "forge"),
                    "page_sizes": paper_size_names(),
                },
            ),
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()

            variant = app.query_one("#workspace-kit-variant-select", Select)
            paper = app.query_one("#workspace-kit-paper", Select)
            design = app.query_one("#workspace-kit-design", Select)
            assert tuple(str(label) for label, _value in variant._options) == ("Lean", "Scanner")
            expected_paper_labels = tuple(
                paper_size_display_name(paper_size) for paper_size in paper_size_names()
            )
            assert tuple(str(label) for label, _value in paper._options) == expected_paper_labels
            assert tuple(str(label) for label, _value in design._options) == (
                "Archive",
                "Forge",
                "Ledger",
                "Maritime",
                "Sentinel",
            )
            assert variant.value == "lean"
            assert paper.value in set(paper_size_names())

            await pilot.press("7")
            await pilot.pause()
            render_style = app.query_one("#setting-control-render_style", Select)
            page_size = app.query_one("#setting-control-page_size", Select)
            assert tuple(str(label) for label, _value in render_style._options) == (
                "Sentinel",
                "Forge",
            )
            assert (
                tuple(str(label) for label, _value in page_size._options) == expected_paper_labels
            )
            assert render_style.value == "sentinel"
            assert page_size.value == "LETTER"

    asyncio.run(run())


def _colors_nearly_equal(left: Color, right: Color) -> bool:
    return (
        max(
            abs(left.r - right.r),
            abs(left.g - right.g),
            abs(left.b - right.b),
        )
        <= 1
    )
