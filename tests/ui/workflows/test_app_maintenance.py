from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    Input,
    Select,
    Static,
)

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.form import FormSection
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.formats.extension_mode import UpdateMode
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.source_assessment import SourceAssessment
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    wait_for_condition as _wait_for_condition,
    wait_for_focus,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_switches_to_maintenance_tasks() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("3")

            assert app.active_task == "add_files"
            assert "Add files to backup" in workflow_support.static_text(app, "#canvas-title")
            assert app.query_one("#workflow-add_files-source-body", SourceChooser).display

            await pilot.press("4")

            assert app.active_task == "rebuild"
            assert "Rebuild backup" in workflow_support.static_text(app, "#canvas-title")
            assert app.query_one("#workflow-rebuild-source-body", SourceChooser).display

            await pilot.press("5")

            assert app.active_task == "replace_recovery_docs"
            assert "Create replacement recovery sheets" in workflow_support.static_text(
                app, "#canvas-title"
            )
            assert app.query_one(
                "#workflow-replace_recovery_docs-source-body-source", SourceChooser
            ).display

    asyncio.run(run())


def test_textual_app_edit_add_files_state(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.click("#workflow-add_files-source-body-load")
            await workflow_support.choose_picker_paths(app, pilot, Path("scan.pdf"))
            await app.action_edit_primary()
            await workflow_support.choose_picker_paths(app, pilot, Path("README.md"))
            unlock = app.query_one("#workflow-add_files-unlock-body-unlock", UnlockEditor)
            await workflow_support.select_guided_radio(unlock, pilot, "Passphrase")
            unlock.query_one(Input).focus()
            await workflow_support.type_text(pilot, "secret")
            await pilot.press("enter")
            app.query_one("#workspace-add-files-freshness", Button).focus()
            await pilot.press("enter")
            destination = app.query_one("#workflow-add_files-output-body-value", Input)
            destination.focus()
            await workflow_support.type_text(pilot, "update-out")
            await pilot.press("enter")

            assert app.add_files_state.validate_task().ready
            assert app.add_files_state.source_paths == [Path("scan.pdf")]
            assert app.add_files_state.passphrase == "secret"
            assert app.add_files_state.output_dir == Path("update-out")
            assert app.add_files_state.allow_stale_head
            workspace = workflow_support.checklist_text(app)
            assert "README.md" in workspace
            assert destination.value == "update-out"
            assert "Newest loaded version accepted" in workspace
            assert "Destination" in workflow_support.preview_text(app)

    asyncio.run(run())


@pytest.mark.portability
def test_textual_app_edit_rebuild_state(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("4")

            await pilot.click("#workflow-rebuild-source-body-load")
            await workflow_support.choose_picker_paths(app, pilot, Path("docs"))
            unlock = app.query_one("#workflow-rebuild-unlock-body-unlock")
            await workflow_support.select_guided_radio(unlock, pilot, "Passphrase")
            unlock.query_one(Input).focus()
            await workflow_support.type_text(pilot, "secret")
            await pilot.press("enter")
            app.query_one("#workspace-rebuild-freshness", Button).focus()
            await pilot.press("enter")
            destination = app.query_one("#workflow-rebuild-output-body-destination-value", Input)
            destination.focus()
            await workflow_support.type_text(pilot, "rebuilt")
            await pilot.press("enter")

            assert app.rebuild_state.validate_task().ready
            assert app.rebuild_state.passphrase == "secret"
            assert app.rebuild_state.output_dir == Path("rebuilt")
            workspace = workflow_support.checklist_text(app)
            assert "docs" in workspace
            assert destination.value == "rebuilt"
            assert (
                app.query_one("#workflow-rebuild-unlock-body-unlock", UnlockEditor).selected_method
                == "passphrase"
            )
            assert "Print options" not in workspace
            assert app.query_one("#workspace-rebuild-paper", Select).value == "A4"
            assert app.query_one("#workspace-rebuild-design", Select).value == "sentinel"
            assert "Existing backup files" in workflow_support.preview_text(app)
            assert "Left unchanged" in workflow_support.preview_text(app)

            assert "harder to scan" in str(
                app.query_one("#workspace-rebuild-qr-chunk-size", Button).tooltip
            )

            await app._select_workbench_step("output")
            await wait_for_focus(pilot, destination)
            assert app.query_one("#rebuild-qr-section", FormSection).display
            density = app.query_one("#workspace-rebuild-qr-chunk-size", Button)
            density.focus()
            await wait_for_focus(pilot, density)
            await pilot.press("enter")
            await workflow_support.enter_edit_field(app, pilot, "384", plain_input=True)

            assert app.rebuild_state.qr_chunk_size == 384
            assert app.rebuild_state.to_rebuild_request().qr_chunk_size == 384
            assert "Warning:" in workflow_support.static_text(app, "#rebuild-qr-notice")
            assert "Custom QR density can change page count" in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_rebuild_signature_source_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("4")

            assert app.query_one("#rebuild-verification-section", FormSection).display
            app.query_one("#workspace-rebuild-signature-source", Select).value = "payloads"
            await pilot.pause()
            await workflow_support.choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.rebuild_state.auth_text_file is None
            assert app.rebuild_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.rebuild_state.to_rebuild_request().auth_payloads_file == Path(
                "auth-payloads.json"
            )
            assert "Signature payload: auth-payloads.json" in workflow_support.preview_text(app)

            app.query_one("#workspace-rebuild-signature-source", Select).value = "auto"
            await _wait_for_condition(
                pilot,
                lambda: app.rebuild_state.auth_payloads_file is None,
                "automatic rebuild authentication selection",
            )

            assert app.rebuild_state.auth_text_file is None
            assert app.rebuild_state.auth_payloads_file is None

    asyncio.run(run())


def test_textual_app_edit_replace_recovery_docs_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("5")
            await pilot.click("#workflow-replace_recovery_docs-source-body-source-load")
            await workflow_support.choose_picker_paths(app, pilot, Path("README.md"))
            app.query_one("#workspace-replace-freshness", Button).focus()
            await pilot.press("enter")
            unlock = app.query_one("#workflow-replace_recovery_docs-unlock-body")
            await workflow_support.select_guided_radio(unlock, pilot, "Passphrase")
            unlock.query_one(Input).focus()
            await workflow_support.type_text(pilot, "secret")
            await pilot.press("enter")
            destination = app.query_one(
                "#workflow-replace_recovery_docs-output-body-destination-value", Input
            )
            destination.focus()
            await workflow_support.type_text(pilot, "replacement-docs")
            await pilot.press("enter")

            assert app.replace_recovery_docs_state.validate_task().ready
            assert app.replace_recovery_docs_state.passphrase == "secret"
            assert app.replace_recovery_docs_state.output_dir == Path("replacement-docs")
            assert app.replace_recovery_docs_state.allow_stale_head
            workspace = workflow_support.checklist_text(app)
            assert "README.md" in workspace
            assert "Latest loaded version accepted" in workspace
            assert (
                "These scans may not contain the latest backup version"
                in workflow_support.preview_text(app)
            )
            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum", QuorumEditor
            )
            assert quorum.values == (2, 3)
            assert destination.value == "replacement-docs"
            assert "Print options" not in workspace
            assert app.query_one("#workspace-replace-paper", Select).value == "A4"
            assert app.query_one("#workspace-replace-design", Select).value == "sentinel"
            assert "Existing backup files" in workflow_support.preview_text(app)
            assert "Left unchanged" in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_replace_recovery_signing_key_controls_are_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)
    state = ReplaceRecoveryDocsTaskState(
        source_paths=[Path("backup.pdf")],
        passphrase="secret",
        allow_stale_head=True,
    )
    state.assess_source()

    async def run() -> None:
        app = EthernityApp(replace_recovery_docs_state=state)
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("5")
            await app._select_workbench_step("recovery")
            await pilot.pause()
            assert app.query_one("#replace-signing-section", FormSection).display
            await pilot.pause()

            signing_warning = (
                "No separate signing-key recovery sheets will be created. The replacement "
                "documents remain signed."
            )
            assert not app.query("#replace-signing-key-status")
            assert signing_warning in workflow_support.preview_text(app)
            assert app.query_one("#replace-signing-notice").display
            assert not app.replace_recovery_docs_state.create_signing_key_recovery

            app.query_one("#workspace-replace-signing-key-select", Select).value = "same"
            await _wait_for_condition(
                pilot,
                lambda: app.replace_recovery_docs_state.create_signing_key_recovery,
                "signing-key recovery selection",
            )

            assert app.replace_recovery_docs_state.create_signing_key_recovery
            assert app.replace_recovery_docs_state.signing_key_recovery_threshold is None
            assert app.replace_recovery_docs_state.signing_key_recovery_count is None
            request = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert request.create_signing_key_shards
            assert signing_warning not in workflow_support.preview_text(app)
            assert not app.query_one("#replace-signing-notice").display

            app.query_one("#workspace-replace-signing-key-select", Select).value = "custom"
            await workflow_support.enter_edit_field(app, pilot, "3/5", plain_input=True)

            assert app.replace_recovery_docs_state.signing_key_recovery_threshold == 3
            assert app.replace_recovery_docs_state.signing_key_recovery_count == 5
            args = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert args.signing_key_shard_threshold == 3
            assert args.signing_key_shard_count == 5
            assert app.query_one("#workspace-replace-signing-key-select", Select).value == "custom"

            app.query_one("#workspace-replace-signing-key-select", Select).value = "off"
            await _wait_for_condition(
                pilot,
                lambda: not app.replace_recovery_docs_state.create_signing_key_recovery,
                "disabled signing-key recovery selection",
            )

            assert not app.replace_recovery_docs_state.create_signing_key_recovery
            assert app.replace_recovery_docs_state.signing_key_recovery_threshold is None
            assert app.replace_recovery_docs_state.signing_key_recovery_count is None
            request = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert not request.create_signing_key_shards

    asyncio.run(run())


@pytest.mark.portability
def test_textual_app_replace_recovery_passphrase_replacement_count_is_real() -> None:
    async def run() -> None:
        app = EthernityApp(
            replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                recovery_payload_files=[Path("recovery-payloads.txt")]
            )
        )
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("5")

            app.query_one("#workspace-replace-passphrase-select", Select).value = "replace"
            await workflow_support.enter_edit_field(app, pilot, "2", plain_input=True)

            state = app.replace_recovery_docs_state
            assert state.create_passphrase_recovery
            assert state.passphrase_replacement_count == 2
            assert state.to_replacement_recovery_request().passphrase_replacement_count == 2
            assert app.query_one("#workspace-replace-passphrase-select", Select).value == "replace"
            replacement = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-passphrase",
                OptionsEditor,
            )
            assert "Sheets to replace: 2 sheets" in str(
                replacement.query_one(".guided-detail", Static).content
            )

    asyncio.run(run())


def test_textual_app_replace_recovery_signing_key_payloads_are_real_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)
    state = ReplaceRecoveryDocsTaskState(
        source_paths=[Path("backup.pdf")],
        passphrase="secret",
        allow_stale_head=True,
    )
    state.assess_source()

    async def run() -> None:
        app = EthernityApp(replace_recovery_docs_state=state)
        async with run_app_test(app, size=(120, 72)) as pilot:
            await pilot.press("5")
            await app._select_workbench_step("recovery")
            await pilot.pause()
            assert app.query_one("#replace-signing-section", FormSection).display
            app.query_one("#workspace-replace-signing-key-select", Select).value = "replace"
            await workflow_support.enter_edit_field(app, pilot, "1")

            payloads = app.query_one("#workspace-replace-signing-key-payloads", Button)
            payloads.focus()
            await wait_for_focus(pilot, payloads)
            await pilot.press("enter")
            await workflow_support.choose_picker_paths(app, pilot, Path("signing-payloads.txt"))

            assert app.replace_recovery_docs_state.signing_key_recovery_payload_files == [
                Path("signing-payloads.txt")
            ]
            args = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert args.signing_key_shard_payload_files == (Path("signing-payloads.txt"),)
            assert "1 key payload file" in workflow_support.checklist_text(app)

            assert app.replace_recovery_docs_state.signing_key_replacement_count == 1
            args = app.replace_recovery_docs_state.to_replacement_recovery_request()
            assert args.create_signing_key_shards
            assert args.signing_key_replacement_count == 1
            assert "1 replacement sheet" in workflow_support.checklist_text(app)

    asyncio.run(run())


@pytest.mark.portability
def test_update_mode_choice_uses_keyboard_and_existing_series_is_read_only() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 40)) as pilot:
            await pilot.press("3")
            await app._select_workbench_step("files")
            await pilot.pause()
            choice = app.query_one("#workspace-add-files-update-mode", Select)
            assert choice.value == "cumulative"
            choice.focus()
            await wait_for_focus(pilot, choice)
            await pilot.press("enter", "down", "enter")
            await _wait_for_condition(
                pilot,
                lambda: app.add_files_state.update_mode == UpdateMode.INCREMENTAL,
                "incremental update mode selection",
            )
            assert app.add_files_state.to_add_files_request().update_mode == UpdateMode.INCREMENTAL

            app.add_files_state.source_paths = [Path("existing-series.pdf")]
            app.add_files_state.update_mode = None
            request = app.add_files_state.source_assessment_request()
            assert request is not None
            app.add_files_state.store_source_assessment(
                request,
                SourceAssessment(
                    source_kind="scanned_pages",
                    source_label="Backup",
                    source_summary="Loaded",
                    has_updates=True,
                ),
            )
            app.refresh_task_view()
            await pilot.pause()
            assert not app.query_one("#add-files-update-mode-choice").display
            assert app.query_one("#add-files-update-mode-summary").display
            assert app.add_files_state.to_add_files_request().update_mode is None

    asyncio.run(run())


def test_textual_app_add_files_advanced_controls_are_real(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(140, 72)) as pilot:
            await pilot.press("3")

            assert "harder to scan" in str(
                app.query_one("#workspace-add-files-qr-chunk-size", Button).tooltip
            )

            await app._select_workbench_step("files")
            await pilot.pause()
            base_dir = app.query_one("#workspace-add-files-base-dir", Button)
            base_dir.focus()
            await pilot.wait_for_scheduled_animations()
            assert await pilot.click(base_dir)
            await workflow_support.choose_picker_paths(app, pilot, tmp_path)

            assert app.add_files_state.base_dir == tmp_path
            assert display_path(tmp_path) in workflow_support.workspace_text(app)

            await app._select_workbench_step("output")
            await pilot.pause()
            await pilot.click("#workspace-add-files-qr-chunk-size")
            await pilot.pause()
            await workflow_support.enter_edit_field(app, pilot, "384", plain_input=False)

            assert app.add_files_state.qr_chunk_size == 384
            assert app.add_files_state.to_add_files_request().qr_chunk_size == 384
            assert "384 bytes" in workflow_support.workspace_text(app)
            assert "Custom QR density can change page count" in workflow_support.preview_text(app)

            app.query_one("#workspace-add-files-signature-source", Select).value = "payloads"
            await pilot.pause()
            await workflow_support.choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.add_files_state.auth_text_file is None
            assert app.add_files_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.add_files_state.to_add_files_request().auth_payloads_file == (
                "auth-payloads.json"
            )
            assert "Signature payload: auth-payloads.json" in workflow_support.preview_text(app)

            app.query_one("#workspace-add-files-signature-source", Select).value = "auto"
            await _wait_for_condition(
                pilot,
                lambda: app.add_files_state.auth_payloads_file is None,
                "automatic update authentication selection",
            )

            await pilot.click("#workspace-add-files-recovery-sheets")
            await workflow_support.enter_edit_field(app, pilot, "3/5")

            assert app.add_files_state.create_recovery_sheets
            assert app.add_files_state.recovery_threshold == 3
            assert app.add_files_state.recovery_sheet_count == 5
            assert "5 new recovery sheets, 3 needed to restore" in workflow_support.workspace_text(
                app
            )

    asyncio.run(run())
