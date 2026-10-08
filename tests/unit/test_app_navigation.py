from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Input, Label, ListItem, ListView

from ethernity.app.application import EthernityApp
from ethernity.app.backup_context import LoadedBackupContext
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.workflow_registry import WORKFLOWS
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.source_assessment import SourceAssessment
from tests.support.pilot import wait_for_widget


def test_workspaces_load_on_demand_and_keep_unsubmitted_input() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 36)) as pilot:
            assert not app.query("#restore-workspace, #add_files-workspace")
            assert not app.query(SettingsForm)

            await app.action_show_task("restore")
            await wait_for_widget(pilot, "#restore-workspace")
            field = app.query_one("#workflow-restore-destination-body-value", Input)
            field.value = "unsubmitted destination"
            await pilot.pause()
            await app.action_show_task("backup")
            await app.action_show_task("restore")
            assert app.query_one("#workflow-restore-destination-body-value") is field
            assert field.value == "unsubmitted destination"
            assert not app.query("#add_files-workspace")
            assert not app.query(SettingsForm)

            await app.action_show_task("settings")
            await wait_for_widget(pilot, "#settings-form-widget")
            assert app.query_one(SettingsForm).active_group == "Printing"

    asyncio.run(run())


def _assessed_restore(*, identity: str = "0123456789abcdef") -> RestoreTaskState:
    state = RestoreTaskState(
        source_paths=[Path("rearranged-papers.pdf")],
        passphrase="test passphrase",
        expected_head_doc_hash="ab" * 32,
    )
    _store_assessment(state, identity=identity)
    return state


def _store_assessment(state: RestoreTaskState, *, identity: str = "0123456789abcdef") -> None:
    request = state.source_assessment_request()
    assert request is not None
    state.store_source_assessment(
        request,
        SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            backup_identity=identity,
            version_summary="1 backup document found",
        ),
    )


def _visible_nav_tasks(app: EthernityApp) -> list[str]:
    return [
        item.id
        for item in app.query_one("#nav-list", ListView).query(ListItem)
        if item.display and item.id in {workflow.key for workflow in WORKFLOWS}
    ]


def test_primary_navigation_keeps_expert_tasks_in_the_palette() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert not app.query_one("#nav-menu").display
            assert len(app.query("#workbench-navigation Button")) == 4
            command_titles = {command.title for command in app.get_system_commands(app.screen)}
            assert {workflow.title for workflow in WORKFLOWS} <= command_titles
            assert app.query_one("#app-header").region.height == 1

            await pilot.click("#nav-tools")
            await pilot.pause()
            assert _visible_nav_tasks(app) == ["kit", "settings"]

    asyncio.run(run())


def test_loaded_documents_are_reused_without_guessing_identity_from_paths() -> None:
    async def run() -> None:
        app = EthernityApp(restore_state=_assessed_restore())
        _store_assessment(app.restore_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await app._show_task("restore")
            await pilot.pause()
            assert app._loaded_backup_context is not None
            assert app._loaded_backup_context.summary == "Backup 01234567"
            await pilot.click("#nav-manage")
            assert _visible_nav_tasks(app) == [
                "add_files",
                "rebuild",
                "replace_recovery_docs",
            ]

            await app._show_task("add_files")
            await pilot.pause()
            assert app.add_files_state.source_paths == [Path("rearranged-papers.pdf")]
            assert app.add_files_state.passphrase == "test passphrase"
            assert app.add_files_state.expected_head_doc_hash == "ab" * 32
            assert app.add_files_state.current_source_assessment() is not None
            assert (
                str(app.query_one("#app-header-title", Label).content) == "Paper backup & recovery"
            )

    asyncio.run(run())


def test_loaded_backup_does_not_overwrite_existing_target_drafts() -> None:
    async def run() -> None:
        draft = AddFilesTaskState(input_paths=[Path("user-selected-file.txt")])
        app = EthernityApp(restore_state=_assessed_restore(), add_files_state=draft)
        _store_assessment(app.restore_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await app._show_task("restore")
            await pilot.pause()
            assert app._loaded_backup_context is not None
            await app._show_task("add_files")
            await pilot.pause()
            assert app.add_files_state.input_paths == [Path("user-selected-file.txt")]
            assert app.add_files_state.source_paths == []
            assert app.add_files_state.passphrase is None

    asyncio.run(run())


def test_unassessed_selection_does_not_create_loaded_backup_identity() -> None:
    async def run() -> None:
        state = RestoreTaskState(source_paths=[Path("backup-deadbeef-latest.pdf")])
        app = EthernityApp(restore_state=state)
        async with app.run_test(size=(100, 30)) as pilot:
            await app._show_task("restore")
            await pilot.pause()
            assert app._loaded_backup_context is None
            assert not app._nav_menu_open

    asyncio.run(run())


def test_tools_menu_can_be_opened_and_selected_with_the_keyboard() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("ctrl+b")
            await pilot.pause()
            assert app.screen.focused is app.query_one("#nav-create", Button)
            assert not app._nav_menu_open
            await pilot.press("left", "enter")
            await pilot.pause()
            nav = app.query_one("#nav-list", ListView)
            assert app.screen.focused is nav
            assert nav.highlighted_child is app.query_one("#kit", ListItem)
            await pilot.press("j", "k", "enter")
            await pilot.pause()
            assert app.active_task == "kit"
            assert not app._nav_menu_open

    asyncio.run(run())


def test_loaded_backup_preserves_invalid_unsaved_form_drafts() -> None:
    async def run() -> None:
        app = EthernityApp(restore_state=_assessed_restore())
        _store_assessment(app.restore_state)
        app.workflow_ui_states["add_files"].set_invalid_draft(
            "files", {"path": "partially edited path"}, message="Choose a readable file."
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await app._show_task("restore")
            await pilot.pause()
            await app._show_task("add_files")
            await pilot.pause()
            assert app.add_files_state.source_paths == []
            assert app.workflow_ui_states["add_files"].has_invalid_draft("files")

    asyncio.run(run())


def test_context_preserves_unsupported_source_instead_of_dropping_it() -> None:
    state = _assessed_restore()
    state.source_paths = []
    state.payloads_file = Path("exported-qr.txt")
    request = state.source_assessment_request()
    assert request is not None
    state.store_source_assessment(
        request,
        SourceAssessment(
            source_kind=request.source_kind,
            source_label=request.source_label,
            source_summary=request.source_summary,
            backup_identity="0123456789abcdef",
            version_summary="1 backup document found",
        ),
    )
    context = LoadedBackupContext.from_state("restore", state)
    assert context is not None
    target = RebuildTaskState()
    assert not context.apply_to(target)
    assert target.model_fields_set == set()
    assert target.source_paths == []
