from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    Input,
    ListView,
    OptionList,
    Select,
    TextArea,
)

from ethernity.app.application import EthernityApp
from ethernity.app.navigation import workspace_focus_selector
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.controls import KeyedRadioSet
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition, wait_for_focus, wait_for_widget


def test_menu_traversal_closes_and_restores_its_invoker() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            for close_key in ("tab", "shift+tab", "escape"):
                await pilot.click("#nav-manage")
                await pilot.pause()
                assert app._nav_menu_open
                assert app.screen.focused is app.query_one("#nav-list", ListView)
                await pilot.press(close_key)
                assert not app._nav_menu_open
                assert app.screen.focused is app.query_one("#nav-manage", Button)

    asyncio.run(run())


def test_menu_selection_leaves_focus_in_a_coherent_workflow() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            await pilot.press("ctrl+b", "right", "right", "enter")
            assert app._nav_menu_open
            assert app.active_task == "backup"
            await pilot.press("enter")
            assert app.active_task == "add_files"
            assert not app._nav_menu_open
            assert app.query_one("#canvas-task-workspaces").has_focus_within

    asyncio.run(run())


@pytest.mark.parametrize("menu,choice", [("manage", "rebuild"), ("tools", "settings")])
@pytest.mark.parametrize("row", [0, 2])
@pytest.mark.portability
def test_menu_padding_selects_the_whole_choice(menu: str, choice: str, row: int) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            assert await pilot.click(f"#nav-{menu}")
            await wait_for_condition(pilot, lambda: app._nav_menu_open, "navigation menu to open")
            assert await pilot.click(f"#{choice}", offset=(1, row))
            await wait_for_condition(
                pilot,
                lambda: app.active_task == choice and not app._nav_menu_open,
                "selected workflow to open",
            )
            assert app.active_task == choice
            assert not app._nav_menu_open

    asyncio.run(run())


def test_tab_remains_stable_for_guided_controls_and_modal_actions() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            await pilot.press("2")
            source_load = app.query_one("#workflow-restore-source-body-load", Button)
            source_load.focus()
            await pilot.pause()

            await pilot.press("tab")

            guided_focus = app.screen.focused
            assert guided_focus is not None
            assert guided_focus is not source_load
            assert guided_focus.has_class("workspace-control")
            assert app.query_one("#canvas-task-workspaces").has_focus_within

            await pilot.press("shift+tab")
            assert app.screen.focused is source_load

            await pilot.click("#nav-manage")
            await pilot.pause()
            assert app._nav_menu_open

            confirm_screen = ConfirmActionScreen(
                title="Confirm action",
                message="Continue?",
                confirm_label="Delete",
            )
            await app.push_screen(confirm_screen)
            await pilot.pause()
            assert app.screen.focused is confirm_screen.query_one("#confirm-action-cancel", Button)

            await pilot.press("tab")
            assert app.screen.focused is confirm_screen.query_one("#confirm-action-confirm", Button)
            assert app._nav_menu_open

            await pilot.press("shift+tab")
            assert app.screen.focused is confirm_screen.query_one("#confirm-action-cancel", Button)
            assert app._nav_menu_open

            await pilot.press("escape")
            assert app.screen is app.screen_stack[0]
            assert app._nav_menu_open

            await pilot.press("tab")
            assert not app._nav_menu_open
            assert app.screen.focused is app.query_one("#nav-manage", Button)

    asyncio.run(run())


def test_clicking_workspace_dismisses_menu() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.click("#nav-manage")
            assert app._nav_menu_open
            await pilot.click("#canvas-title", offset=(1, 0))
            await pilot.pause()
            assert not app._nav_menu_open
            assert app.active_task == "backup"
            await pilot.click("#nav-manage")
            choose_files = app.query_one("#workspace-backup-files", Button)
            assert not app.query_one("#nav-menu").region.contains(
                choose_files.region.x, choose_files.region.y
            )
            await pilot.click(choose_files, offset=(0, 0))
            await pilot.pause()
            assert isinstance(app.screen, FilePickerScreen)
            assert not app._nav_menu_open

    asyncio.run(run())


@pytest.mark.parametrize("size", [(80, 24), (120, 32)])
def test_closed_dropdowns_share_form_focus_order(size: tuple[int, int]) -> None:
    async def run() -> None:
        app = EthernityApp(
            replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                payloads_file=Path("backup.payloads"),
                passphrase="test-only phrase",
            )
        )
        async with run_app_test(app, size=size) as pilot:
            for task, selector in (
                ("backup", "#workspace-backup-design"),
                ("restore", "#workspace-restore-auth-policy"),
                ("add_files", "#workspace-add-files-signature-source"),
                ("rebuild", "#workspace-rebuild-signature-source"),
                ("replace_recovery_docs", "#workspace-replace-signing-key-select"),
                ("kit", "#workspace-kit-variant-select"),
                ("settings", "#setting-control-render_style"),
            ):
                await app._show_task(task)
                await wait_for_focus(pilot, app.query_one(workspace_focus_selector(task)))
                app._reveal_focus_target(selector)
                await pilot.pause()
                control = app.query_one(selector, Select)
                original = control.value
                chain = app.screen.focus_chain
                index = chain.index(control)
                for key, direction in (("down", 1), ("j", 1), ("up", -1), ("k", -1)):
                    control.focus()
                    await wait_for_focus(pilot, control)
                    await pilot.press(key)
                    expected = chain[(index + direction) % len(chain)]
                    await wait_for_focus(pilot, expected)
                    assert app.screen.focused is expected
                    assert not control.expanded
                    assert control.value == original

    asyncio.run(run())


@pytest.mark.parametrize("size", [(80, 24), (120, 32)])
def test_dropdown_commit_cancel_and_traversal(size: tuple[int, int]) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=size) as pilot:
            await app._show_task("restore")
            app._reveal_focus_target("#workspace-restore-auth-policy")
            await pilot.pause()
            control = app.query_one("#workspace-restore-auth-policy", Select)
            before = app.query_one("#workflow-restore-source-body-secondary-1", Button)
            after = app.query_one("#workspace-restore-signature-source", Select)
            original_state = app.restore_state.model_dump()

            for key, target in (("escape", control), ("tab", after), ("shift+tab", before)):
                control.focus()
                await pilot.press("enter", "down")
                assert control.expanded
                assert isinstance(app.screen.focused, OptionList)
                assert app.screen.focused.highlighted == 1
                assert app.restore_state.model_dump() == original_state
                await pilot.press(key)
                assert not control.expanded
                assert app.screen.focused is target
                assert control.value == "require-signed"
                assert app.restore_state.model_dump() == original_state

            control.focus()
            await pilot.press("space", "down", "enter")
            assert control.value == "allow-unsigned"
            assert not control.expanded
            assert app.screen.focused is control
            assert app.restore_state.model_dump() != original_state
            await pilot.press("enter", "home", "enter")
            assert control.value == "require-signed"
            assert app.restore_state.model_dump() == original_state

    asyncio.run(run())


def test_dropdown_typeahead_and_navigation_shortcut_do_not_change_values() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.pause()
            await app._select_workbench_step("print")
            await pilot.pause()
            control = app.query_one("#workspace-backup-design", Select)
            original = control.value
            control.focus()
            await pilot.press("enter", "l", "e", "d")
            assert control.expanded
            overlay = app.screen.focused
            assert isinstance(overlay, OptionList)
            assert overlay.highlighted is not None
            assert "Ledger" in str(overlay.get_option_at_index(overlay.highlighted).prompt)
            await pilot.press("ctrl+b")
            assert not control.expanded
            assert control.value == original
            assert app.screen.focused is app.query_one("#nav-create", Button)

    asyncio.run(run())


def test_arrows_reach_step_rail_open_sections_and_bottom_actions() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            await wait_for_focus(pilot, app.query_one("#workspace-backup-files"))
            steps = app.query_one(WorkbenchSteps)
            steps.button_for("files").focus()
            await wait_for_focus(pilot, steps.button_for("files"))
            await pilot.press("down")
            await wait_for_focus(pilot, steps.button_for("recovery"))
            assert app.screen.focused is steps.button_for("recovery")
            assert steps.button_for("files").has_class("active-step")
            await pilot.press("enter")
            await wait_for_focus(pilot, app.query_one("#workspace-backup-recovery-method"))
            assert steps.button_for("recovery").has_class("active-step")

            await app._show_task("restore")
            await wait_for_focus(pilot, app.query_one("#workflow-restore-source-body-load"))
            last_source = app.query_one("#workflow-restore-source-body-secondary-1", Button)
            last_source.focus()
            await wait_for_focus(pilot, last_source)
            for key, selector in (
                ("down", "#workspace-restore-auth-policy"),
                ("down", "#workspace-restore-signature-source"),
                ("down", "#workspace-restore-expected-head"),
                ("down", "#canvas-primary"),
                ("up", "#workspace-restore-expected-head"),
            ):
                await pilot.press(key)
                expected = app.query_one(selector)
                await wait_for_focus(pilot, expected)
                assert app.screen.focused is expected

    asyncio.run(run())


def test_radio_arrows_and_hjkl_keep_choice_focus_until_tab() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await app._select_workbench_step("recovery")
            radio = app.query_one("#workspace-backup-recovery-method", KeyedRadioSet)
            radio.focus()
            await pilot.press("j", "space")
            assert radio.has_focus
            assert radio.selected_key == "single_phrase"
            await pilot.press("up", "space")
            assert radio.selected_key == "recommended_shards"
            await pilot.press("tab")
            assert not radio.has_focus

    asyncio.run(run())


def test_text_editing_keeps_letters_and_cursor_keys_in_the_editor() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            editor = EditFieldScreen(title="Label", prompt="Enter a label")
            await app.push_screen(editor)
            await pilot.press("h", "j", "k", "l", "left", "left", "X")
            field = editor.query_one(Input)
            assert field.value == "hjXkl"
            assert field.has_focus
            await pilot.press("escape")

            paste = PasteTextScreen(title="Text", prompt="Paste text", value="first\nsecond")
            await app.push_screen(paste)
            area = paste.query_one(TextArea)
            area.move_cursor((1, 3))
            await pilot.press("up", "left")
            assert area.cursor_location == (0, 2)
            assert area.has_focus
            await pilot.press("h", "j", "k", "l")
            assert area.text == "fihjklrst\nsecond"
            assert app.active_task == "backup"

    asyncio.run(run())


def test_returning_to_settings_focuses_the_active_category() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(80, 24)) as pilot:
            await wait_for_focus(pilot, app.query_one("#workspace-backup-files"))
            await pilot.press("7")
            await wait_for_focus(
                pilot, await wait_for_widget(pilot, "#setting-control-render_style")
            )
            form = app.query_one(SettingsForm)
            rail = form.query_one("#settings-categories", WorkbenchSteps)
            rail.button_for("Printing").focus()
            await wait_for_focus(pilot, rail.button_for("Printing"))
            await pilot.press("down")
            await wait_for_focus(pilot, rail.button_for("Backup defaults"))
            await pilot.press("enter")
            await wait_for_focus(pilot, app.query_one("#setting-control-backup_base_dir"))
            assert form.active_group == "Backup defaults"
            assert form.active_pane in app.screen.focused.ancestors

            form.show_group("Advanced")
            await pilot.pause()
            pane = form.active_pane
            control = app.query_one("#setting-control-qr_error", Select)
            control.focus()
            await wait_for_focus(pilot, control)
            await pilot.press("right")
            await wait_for_focus(pilot, control)
            focused = app.screen.focused
            assert focused is not None and pane in focused.ancestors
            assert focused in app.screen.focus_chain
            assert focused.has_class("settings-control")

            await pilot.press("ctrl+b", "1")
            await wait_for_condition(
                pilot, lambda: app.active_task == "backup", "backup workspace to open"
            )
            await pilot.press("ctrl+b", "7")
            await wait_for_condition(
                pilot, lambda: app.active_task == "settings", "settings workspace to reopen"
            )
            # A shortcut from top navigation keeps focus there until an arrow enters the form.
            assert app.active_task == "settings"
            await pilot.press("down")
            await wait_for_focus(pilot, control)
            assert form.active_pane is pane
            focused = app.screen.focused
            assert focused is not None and pane in focused.ancestors
            assert focused in app.screen.focus_chain
            assert focused.has_class("settings-control")

    asyncio.run(run())
