from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    Collapsible,
    Select,
    Static,
)

from ethernity.app.application import EthernityApp
from ethernity.app.input_parsers import parse_threshold_count
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.options import QuorumEditor
from ethernity.app.widgets.workflow.paths import PathSelectionEditor
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.file_summary import display_path
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    click_when_ready,
    wait_for_condition as _wait_for_condition,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_custom_quorum_updates_do_not_trip_assignment_validation() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            app._apply_backup_recovery("4/5")
            app._apply_replace_recovery_set("4/5")

            assert app.backup_state.shard_threshold == 4
            assert app.backup_state.shard_count == 5
            assert app.replace_recovery_docs_state.recovery_threshold == 4
            assert app.replace_recovery_docs_state.recovery_document_count == 5

            # Task shortcuts must leave the numeric editor before consuming a digit.
            await pilot.press("ctrl+b", "5")
            assert app.active_task == "replace_recovery_docs"

            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum",
                QuorumEditor,
            )
            assert quorum.values == (4, 5)
            assert str(quorum.query_one(".guided-summary", Static).content) == (
                "Create 5 sheets; any 4 can restore"
            )
            assert (
                "A custom quorum changes how many sheets you need to restore"
                in workflow_support.preview_text(app)
            )

    asyncio.run(run())


def test_textual_app_quorum_parser_rejects_counts_above_shamir_limit() -> None:
    assert parse_threshold_count("2/255") == (2, 255)
    assert parse_threshold_count("2/256") is None
    assert parse_threshold_count("256/256") is None


@pytest.mark.portability
def test_textual_app_backup_advanced_controls_are_real(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(140, 72)) as pilot:
            await pilot.pause()

            assert not app.backup_state.validate_task().ready
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"

            await pilot.click(app.query_one(WorkbenchSteps).button_for("recovery"))

            assert "harder to scan" in str(
                app.query_one("#workspace-backup-qr-chunk-size", Button).tooltip
            )

            words_select = app.query_one("#workspace-backup-passphrase-words", Select)
            words_select.value = "18"
            await _wait_for_condition(
                pilot, lambda: app.backup_state.passphrase_words == 18, "phrase length selection"
            )

            assert app.backup_state.passphrase_words == 18
            assert app.backup_state.passphrase is None

            await pilot.click("#workspace-backup-passphrase")
            await pilot.pause()
            await workflow_support.enter_edit_field(app, pilot, "manual secret", plain_input=False)

            assert app.backup_state.passphrase == "manual secret"
            assert app.backup_state.passphrase_words is None

            words_select.value = "24"
            await _wait_for_condition(
                pilot,
                lambda: (
                    app.backup_state.passphrase is None and app.backup_state.passphrase_words == 24
                ),
                "generated phrase to replace the manual phrase",
            )

            assert app.backup_state.passphrase is None
            assert app.backup_state.passphrase_words == 24

            app.query_one("#workspace-backup-signing-key-mode", Select).value = "sharded"
            await click_when_ready(pilot, "#workspace-backup-signing-key-shards")
            await workflow_support.enter_edit_field(app, pilot, "3/5", plain_input=True)

            assert app.backup_state.signing_key_mode == "sharded"
            assert app.backup_state.signing_key_shard_threshold == 3
            assert app.backup_state.signing_key_shard_count == 5
            assert "5 key sheets; any 3 can recover the key" in workflow_support.workspace_text(app)

            await app._select_workbench_step("files")
            await pilot.pause()
            await pilot.click("#workspace-backup-base-dir")
            await pilot.pause()
            await workflow_support.choose_picker_paths(app, pilot, tmp_path)

            assert app.backup_state.base_dir == tmp_path
            assert display_path(tmp_path) in workflow_support.workspace_text(app)

            await app._select_workbench_step("print")
            await pilot.pause()
            await pilot.click("#workspace-backup-qr-chunk-size")
            await pilot.pause()
            await workflow_support.enter_edit_field(app, pilot, "384", plain_input=False)

            assert app.backup_state.qr_chunk_size == 384
            assert app.backup_state.to_backup_request().qr_chunk_size == 384
            assert "Warning:" in workflow_support.static_text(app, "#backup-qr-notice")
            assert "384 bytes" in workflow_support.workspace_text(app)
            assert "Custom QR density can change page count" in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_edit_and_clear_backup_state() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await app.action_edit_primary()
            await workflow_support.choose_picker_paths(app, pilot, Path("README.md"))
            await app.action_edit_output()
            await workflow_support.save_picker_name(app, pilot, "backup-out")

            assert app.backup_state.validate_task().ready
            workspace = workflow_support.checklist_text(app)
            assert "README.md" in workspace
            assert "backup-out" in workspace

            await pilot.press("c")

            assert app.backup_state.validate_task().ready
            assert "README.md" in workflow_support.checklist_text(app)

            app.action_clear_task()
            await pilot.pause()

            assert not app.backup_state.validate_task().ready
            assert "No files selected" in workflow_support.checklist_text(app)

    asyncio.run(run())


def test_textual_app_file_sections_can_clear_selected_paths() -> None:
    async def run() -> None:
        backup_app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("README.md")],
                output_dir=Path("backup-out"),
            )
        )
        async with run_app_test(backup_app, size=(120, 32)) as pilot:
            assert "README.md" in workflow_support.checklist_text(backup_app)

            assert not backup_app.query_one("#backup-files-panel", Collapsible).collapsed
            await pilot.click("#workspace-backup-clear-files")
            await pilot.pause()

            assert backup_app.backup_state.input_paths == []
            assert backup_app.backup_state.input_dirs == []
            assert "No files selected" in workflow_support.checklist_text(backup_app)

        add_app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[Path("docs")],
                output_dir=Path("update-out"),
                allow_stale_head=True,
                input_paths=[Path("new.txt")],
                passphrase="secret",
            )
        )
        async with run_app_test(add_app, size=(120, 32)) as pilot:
            await pilot.press("3")
            assert "new.txt" in workflow_support.checklist_text(add_app)
            assert (
                workflow_support.button_label(add_app, "#workspace-add-files-clear-files")
                == "Clear all"
            )

            await pilot.click(add_app.query_one(WorkbenchSteps).button_for("files"))
            add_app.query_one("#workspace-add-files-clear-files", Button).focus()
            await pilot.press("enter")

            assert add_app.add_files_state.input_paths == []
            assert add_app.add_files_state.input_dirs == []
            assert "No files or folders selected" in workflow_support.checklist_text(add_app)

    asyncio.run(run())


def test_textual_app_selected_file_sections_show_size_and_base_folder(tmp_path) -> None:
    async def run() -> None:
        selected_file = tmp_path / "secret.txt"
        selected_file.write_text("twelve bytes", encoding="utf-8")

        backup_app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[selected_file],
                base_dir=tmp_path,
                output_dir=tmp_path / "backup-out",
            )
        )
        async with run_app_test(backup_app, size=(120, 32)) as pilot:
            await _wait_for_condition(
                pilot,
                lambda: backup_app.backup_state.current_estimate() is not None,
                "backup file size estimate",
            )
            status = workflow_support.static_text(backup_app, "#backup-files-value")

            assert "1 file" in status
            assert "12 bytes" in status
            assert workflow_support.static_text(
                backup_app, "#backup-base-dir-value"
            ) == display_path(tmp_path)

        add_app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[tmp_path / "docs"],
                output_dir=tmp_path / "update-out",
                allow_stale_head=True,
                input_paths=[selected_file],
                base_dir=tmp_path,
                passphrase="secret",
            )
        )
        async with run_app_test(add_app, size=(120, 32)) as pilot:
            await pilot.press("3")
            editor = add_app.query_one(
                "#workflow-add_files-files-body",
                PathSelectionEditor,
            )
            status = str(editor.query_one(".guided-summary", Static).content)

            assert status == "1 file"
            assert "12 bytes" in workflow_support.preview_text(add_app)
            assert f"base folder: {display_path(tmp_path)}" in workflow_support.preview_text(
                add_app
            )

    asyncio.run(run())
