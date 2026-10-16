from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.geometry import Region
from textual.widgets import Button, Label, ListView, Select

from ethernity.app.application import EthernityApp
from ethernity.app.help_content import build_help_content
from ethernity.app.navigation import sync_nav_active
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.workspaces.workspace_controls import SIGNING_KEY_RECOVERY_OPTIONS
from ethernity.page_sizes import paper_size_display_name, paper_size_names
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.presentation.workflow_replace_recovery import (
    replace_signing_key_recovery_summary,
)
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.settings import SettingsTaskState
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition, wait_for_focus, wait_for_widget


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
@pytest.mark.parametrize("size", [(120, 32), (80, 32), (80, 24), (120, 24)])
@pytest.mark.portability
def test_focused_buttons_do_not_underline_labels_or_blank_padding(theme, size) -> None:
    async def run() -> None:
        app = EthernityApp()
        app.theme = theme
        async with run_app_test(app, size=size) as pilot:
            await wait_for_focus(pilot, app.query_one("#workspace-backup-files"))
            for selector in ("#nav-create", "#workbench-step-0", "#workspace-backup-files"):
                button = app.query_one(selector, Button)
                button.focus()
                await wait_for_focus(pilot, button)
                assert_clean_button(button)
                assert button.parent.content_region.contains_region(button.region)

            # Padding is part of the target, even at the edge of the navigation strip.
            restore = app.query_one("#nav-restore", Button)
            assert await pilot.click(restore, offset=(1, restore.region.height - 1))
            await wait_for_condition(
                pilot, lambda: app.active_task == "restore", "restore workspace to open"
            )
            assert app.active_task == "restore"
            await wait_for_focus(pilot, app.query_one("#workflow-restore-source-body-load"))

            await pilot.press("7")
            await wait_for_focus(
                pilot, await wait_for_widget(pilot, "#setting-control-render_style")
            )
            app.query_one(SettingsForm).show_group("Config file")
            copy = app.query_one("#settings-copy-config", Button)
            copy.focus()
            await wait_for_focus(pilot, copy)
            assert_clean_button(copy)
            rail = app.query_one(SettingsForm).query_one(WorkbenchSteps)
            assert rail.content_region.contains_region(rail.button_for("Config file").region)

    def assert_clean_button(button: Button) -> None:
        height = 1 if size[1] < 28 else 3
        assert button.has_focus
        assert button.region.height == height
        lines = button.render_lines(Region(0, 0, button.region.width, height))
        assert [i for i, line in enumerate(lines) if line.text.strip()] == [height // 2]
        assert str(button.label) in lines[height // 2].text
        assert all(not segment.style.underline for line in lines for segment in line)
        assert all(segment.style.bold for segment in lines[height // 2] if segment.text.strip())

    asyncio.run(run())


def test_open_directory_current_folder_confirms_immediately(tmp_path: Path) -> None:
    async def run() -> None:
        results: list[tuple[Path, ...] | None] = []
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
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
        async with run_app_test(app, size=(160, 32)) as pilot:
            await pilot.click("#nav-manage")
            await pilot.pause()
            nav = app.query_one("#nav-list", ListView)
            sync_nav_active(
                nav,
                "rebuild",
                {
                    "rebuild": "in-progress",
                    "replace_recovery_docs": "ready",
                    "add_files": "attention",
                },
            )
            await pilot.pause()

            expected = {
                "rebuild": ("WIP", "Work in progress"),
                "replace_recovery_docs": ("OK", "Ready for final review"),
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
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")

            notice = app.query_one("#kit-qr-warning", InlineNotice)
            assert notice.display
            assert "Warning: Custom QR sizing may make codes harder to scan." in str(notice.content)
            assert notice.has_class("notice-warning")

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
    assert "Ctrl+R Review" in help_text
    assert "Ctrl+P Actions" in help_text
    assert "acknowledge that newer documents may be missing" in help_text
    assert "separately saved full fingerprint" in help_text
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
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")

            variant = app.query_one("#workspace-kit-variant-select", Select)
            paper = app.query_one("#workspace-kit-paper", Select)
            design = app.query_one("#workspace-kit-design", Select)
            assert tuple((str(label), value) for label, value in variant._options) == (
                ("Lean", "lean"),
                ("Scanner", "scanner"),
            )
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


def test_dropdown_options_are_visible_and_selectable_in_both_themes() -> None:
    async def run() -> None:
        for theme, size in (
            ("ethernity-dark", (120, 32)),
            ("ethernity-light", (120, 32)),
            ("ethernity-dark", (80, 24)),
            ("ethernity-light", (80, 24)),
        ):
            app = EthernityApp()
            app.theme = theme
            async with run_app_test(app, size=size) as pilot:
                await app._select_workbench_step("print")
                await pilot.pause()
                paper = app.query_one("#workspace-backup-paper-size", Select)
                await pilot.click(paper)
                await pilot.pause()

                assert paper.expanded
                overlay = paper.query_one("SelectOverlay")
                rendered = "\n".join(
                    overlay.render_line(line).text for line in range(overlay.region.height)
                )
                assert "A4" in rendered
                assert "Letter" in rendered
                assert app.screen.region.contains_region(overlay.region)

                await pilot.press("home", "down", "enter")
                assert not paper.expanded
                assert paper.value == "LETTER"
                assert app.backup_state.paper_size == "LETTER"

    asyncio.run(run())
