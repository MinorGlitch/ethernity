from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.color import Color
from textual.geometry import Region
from textual.widgets import Button, Label, ListView, RadioButton, Select

from ethernity.app.application import EthernityApp
from ethernity.app.help_content import build_help_content
from ethernity.app.navigation import sync_nav_active
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.controls import InlineNotice, KeyedRadioSet
from ethernity.app.workspaces.workspace_controls import SIGNING_KEY_RECOVERY_OPTIONS
from ethernity.page_sizes import paper_size_display_name, paper_size_names
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.presentation.workflow_replace_recovery import (
    replace_signing_key_recovery_summary,
)
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.settings import SettingsTaskState


def test_action_colors_and_primary_focus_survive_both_themes() -> None:
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
                assert cancel.variant == "primary"
                assert confirm.variant == "warning"
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
                assert cancel.styles.text_style.bold
                assert not cancel.styles.text_style.underline

                confirm.focus()
                await pilot.pause()
                assert confirm.styles.text_style.bold
                assert not confirm.styles.text_style.underline
                assert _colors_nearly_equal(
                    confirm.styles.background,
                    Color.parse(app.current_theme.warning),
                )

    asyncio.run(run())


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
@pytest.mark.parametrize("size", [(120, 32), (80, 32), (80, 24), (120, 24)])
def test_focused_buttons_do_not_underline_labels_or_blank_padding(theme, size) -> None:
    async def run() -> None:
        app = EthernityApp()
        app.theme = theme
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            for selector in ("#nav-create", "#workbench-step-0", "#workspace-backup-files"):
                button = app.query_one(selector, Button)
                button.focus()
                await pilot.pause()
                assert_clean_button(button)
                assert button.parent.content_region.contains_region(button.region)

            # Padding is part of the target, even at the edge of the navigation strip.
            restore = app.query_one("#nav-restore", Button)
            await pilot.click(restore, offset=(1, restore.region.height - 1))
            assert app.active_task == "restore"

            await pilot.press("7")
            app.query_one(SettingsForm).show_group("Config file")
            copy = app.query_one("#settings-copy-config", Button)
            copy.focus()
            await pilot.pause()
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


@pytest.mark.parametrize("theme", ["ethernity-dark", "ethernity-light"])
@pytest.mark.parametrize("size", [(120, 32), (80, 32), (80, 24), (120, 24)])
def test_radio_focus_highlights_candidate_without_changing_committed_choice(theme, size) -> None:
    async def run() -> None:
        app = EthernityApp()
        app.theme = theme
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            step = app.query_one(WorkbenchSteps).button_for("recovery")
            await pilot.click(step, offset=(1, step.region.height - 1))
            radio = app.query_one("#workspace-backup-recovery-method", KeyedRadioSet)
            radio.focus()
            await pilot.press("down")
            candidate = radio.query_one("RadioButton.-selected", RadioButton)
            committed = radio.query_one("RadioButton.-on", RadioButton)
            assert radio.has_focus
            assert candidate is not committed
            assert radio.selected_key == "recommended_shards"
            assert candidate.styles.background != committed.styles.background
            height = 1 if size[1] < 28 else 3
            assert candidate.region.height == height
            lines = candidate.render_lines(Region(0, 0, candidate.region.width, height))
            assert [i for i, line in enumerate(lines) if line.text.strip()] == [height // 2]
            assert all(not segment.style.underline for line in lines for segment in line)
            # The fill covers the whole row, including the space after the label.
            for line in lines:
                segments = list(line)
                assert segments[0].style.bgcolor == segments[-1].style.bgcolor
            assert candidate.styles.text_style.bold

            await pilot.click(candidate, offset=(candidate.region.width - 2, height - 1))
            assert radio.selected_key == "single_phrase"
            await pilot.press("up", "space", "tab")
            assert not radio.has_focus
            assert radio.selected_key == "recommended_shards"
            assert not candidate.styles.text_style.bold

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
        async with app.run_test(size=(160, 32)) as pilot:
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
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.pause()

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
            async with app.run_test(size=size) as pilot:
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
                await pilot.pause()
                assert not paper.expanded
                assert paper.value == "LETTER"
                assert app.backup_state.paper_size == "LETTER"

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
