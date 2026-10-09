from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    Input,
    RadioButton,
    RadioSet,
    Select,
    Static,
)

from ethernity.app.application import EthernityApp
from ethernity.app.screens.file_picker import FilePickerScreen
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.widgets.form import FormSection
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.source_assessment import SourceAssessment
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    click_when_ready,
    wait_for_condition as _wait_for_condition,
    wait_for_focus,
    wait_for_widget,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_unlock_recovery_documents_are_real_picker() -> None:
    async def run() -> None:
        app = EthernityApp(restore_state=RestoreTaskState(source_paths=[Path("scan.pdf")]))
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.click("#canvas-primary")
            unlock_methods = app.query_one(
                "#workflow-restore-unlock-body-methods",
                RadioSet,
            )
            unlock_methods.focus()
            await pilot.press("right", "space")
            await workflow_support.choose_picker_paths(app, pilot, Path("recovery.pdf"))

            assert [str(path) for path in app.restore_state.recovery_documents] == ["recovery.pdf"]
            assert app.restore_state.passphrase is None
            assert not app.restore_state.recovery_payload_files
            assert "recovery.pdf" in workflow_support.workspace_text(app)

    asyncio.run(run())


def test_textual_app_unlock_input_lists_show_selected_recovery_inputs() -> None:
    async def run() -> None:
        cases = (
            (
                EthernityApp(
                    add_files_state=AddFilesTaskState(recovery_documents=[Path("add-sheet.pdf")])
                ),
                "3",
                "#workflow-add_files-unlock-body-unlock",
                "recovery_documents",
                "add-sheet.pdf",
            ),
            (
                EthernityApp(
                    rebuild_state=RebuildTaskState(
                        recovery_payload_files=[Path("rebuild-payloads.txt")]
                    )
                ),
                "4",
                "#workflow-rebuild-unlock-body-unlock",
                "recovery_payloads",
                "rebuild-payloads.txt",
            ),
            (
                EthernityApp(
                    replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                        recovery_documents=[Path("replace-sheet.pdf")]
                    )
                ),
                "5",
                "#workflow-replace_recovery_docs-unlock-body",
                "recovery_documents",
                "replace-sheet.pdf",
            ),
        )
        for app, key, editor_selector, expected_method, expected_text in cases:
            async with run_app_test(app, size=(120, 48)) as pilot:
                await pilot.press(key)

                editor = app.query_one(editor_selector, UnlockEditor)
                assert editor.selected_method == expected_method
                assert expected_text in str(editor.query_one(".guided-detail", Static).content)

        restore_app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                recovery_payload_files=[Path("restore-payloads.txt")],
            )
        )
        async with run_app_test(restore_app, size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.click("#canvas-primary")
            await pilot.pause()

            assert "restore-payloads.txt" in workflow_support.workspace_text(restore_app)

    asyncio.run(run())


def test_textual_app_restore_source_modes_are_real_pickers() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("2")
            source = app.query_one("#workflow-restore-source-body", SourceChooser)
            assert not source.query(RadioSet)
            await pilot.click("#workflow-restore-source-body-load")
            await pilot.pause()
            assert isinstance(app.screen, FilePickerScreen)
            await pilot.press("escape")
            assert not app.restore_state.source_paths
            assert app.restore_state.recovery_text is None

            await pilot.click("#workflow-restore-source-body-secondary-0")
            await pilot.pause()
            assert isinstance(app.screen, PasteTextScreen)
            await workflow_support.save_pasted_text(app, pilot, "pasted recovery text")

            assert app.restore_state.recovery_text == "pasted recovery text"
            assert app.restore_state.recovery_text_file is None
            assert not app.restore_state.source_paths
            assert app.restore_state.payloads_file is None
            assert "Pasted text, 1 non-empty line" in workflow_support.checklist_text(app)

            await pilot.click("#workflow-restore-source-body-secondary-1")
            await pilot.pause()
            await workflow_support.choose_picker_paths(app, pilot, Path("payloads.json"))

            assert app.restore_state.payloads_file == Path("payloads.json")
            assert app.restore_state.recovery_text is None
            assert app.restore_state.recovery_text_file is None
            assert not app.restore_state.source_paths
            assert "payloads.json" in workflow_support.checklist_text(app)

    asyncio.run(run())


def test_textual_app_restore_expected_head_fingerprint_is_real_control() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("2")
            assert app.query_one("#restore-verification-section", FormSection).display
            app.query_one("#workspace-restore-expected-head", Button).focus()
            await pilot.pause()
            await pilot.press("enter")
            app.screen.query_one("#edit-field-input", Input).value = "ab" * 32
            await pilot.press("enter")

            assert app.restore_state.expected_head_doc_hash == "ab" * 32
            assert app.restore_state.to_recovery_request().expected_head_doc_hash == "ab" * 32
            assert "Latest fingerprint" in workflow_support.preview_text(app)
            assert "Provided" in workflow_support.preview_text(app)

            source_load = app.query_one(
                "#workflow-restore-source-body-load",
                Button,
            )
            source_load.focus()
            await pilot.press("enter")
            await workflow_support.choose_picker_paths(app, pilot, Path("scan.pdf"))

            assert app.restore_state.expected_head_doc_hash is None

    asyncio.run(run())


def test_textual_app_expected_fingerprint_is_real_freshness_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp(
            add_files_state=AddFilesTaskState(
                source_paths=[Path("scan.pdf")],
                input_paths=[Path("new.txt")],
                passphrase="secret",
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("3")
            await pilot.press("ctrl+r")
            assert app.add_files_state.expected_head_doc_hash is None

            app.query_one("#workspace-add-files-fingerprint", Button).focus()
            await pilot.press("enter")
            app.screen.query_one("#edit-field-input", Input).value = "bc" * 32
            await pilot.press("enter")

            assert app.add_files_state.expected_head_doc_hash == "bc" * 32
            assert "Latest fingerprint provided" in workflow_support.workspace_text(app)

    asyncio.run(run())


def test_textual_app_fingerprint_actions_match_configured_sources() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("3")
            assert app.query_one("#workspace-add-files-fingerprint", Button).display

            await pilot.press("4")
            assert not app.query_one("#workspace-rebuild-fingerprint", Button).display

            await pilot.press("5")
            assert not app.query_one("#workspace-replace-fingerprint", Button).display

    asyncio.run(run())


def test_textual_app_restore_target_fingerprint_is_real_control() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
            )
        )
        request = app.restore_state.source_assessment_request()
        assert request is not None
        app.restore_state.store_source_assessment(
            request,
            SourceAssessment(
                source_kind=request.source_kind,
                source_label=request.source_label,
                source_summary=request.source_summary,
                backup_identity="a340606afa811eb9",
                version_summary="2 backup documents found",
                has_updates=True,
                document_count=2,
            ),
        )
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("2")
            await pilot.click(app.query_one(WorkbenchSteps).button_for("target"))
            await pilot.pause()
            target = app.query_one("#workflow-restore-target-body-choices", RadioSet)
            target.focus()
            await wait_for_focus(pilot, target)
            await pilot.press("right", "right", "space")
            await click_when_ready(pilot, "#edit-field-cancel")
            await click_when_ready(pilot, "#workspace-restore-target-fingerprint")
            field = await wait_for_widget(pilot, "#edit-field-input")
            assert isinstance(field, Input)
            field.value = "cd" * 32
            await pilot.press("enter")
            await _wait_for_condition(
                pilot,
                lambda: app.restore_state.extension_doc_hash == "cd" * 32,
                "restore fingerprint to reach task state",
            )

            assert app.restore_state.target == "specific_update"
            assert app.restore_state.extension_index is None
            assert app.restore_state.extension_doc_hash == "cd" * 32
            selected = [str(button.label) for button in target.query(RadioButton) if button.value]
            assert selected == ["Specific version or update"]
            assert "Version matching fingerprint" in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_restore_auth_policy_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("2")

            assert "only when the original has no signatures" in str(
                app.query_one("#workspace-restore-auth-policy", Select).tooltip
            )
            app.query_one("#workspace-restore-auth-policy", Select).value = "allow-unsigned"
            await _wait_for_condition(
                pilot, lambda: app.restore_state.allow_unsigned, "unsigned recovery to be enabled"
            )

            assert app.restore_state.allow_unsigned
            assert app.restore_state.to_recovery_request().allow_unsigned
            assert "Unsigned legacy backups allowed" in workflow_support.preview_text(app)
            assert not app.query("#restore-authentication-help, #restore-authentication-status")
            assert "signatures will not be required" in workflow_support.preview_text(app)

            app.query_one("#workspace-restore-auth-policy", Select).value = "require-signed"
            await _wait_for_condition(
                pilot,
                lambda: not app.restore_state.allow_unsigned,
                "signed recovery to be required",
            )

            assert not app.restore_state.allow_unsigned
            assert not app.query("#workspace-restore-resource-policy")

    asyncio.run(run())


def test_textual_app_restore_signature_source_control_is_real() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 48)) as pilot:
            await pilot.press("2")

            app.query_one("#workspace-restore-signature-source", Select).value = "text"
            await pilot.pause()
            await workflow_support.choose_picker_paths(app, pilot, Path("auth.txt"))

            assert app.restore_state.auth_text_file == Path("auth.txt")
            assert app.restore_state.auth_payloads_file is None
            assert app.restore_state.to_recovery_request().auth_text_file == Path("auth.txt")
            assert "Signature text: auth.txt" in workflow_support.preview_text(app)

            app.query_one("#workspace-restore-signature-source", Select).value = "payloads"
            await pilot.pause()
            await workflow_support.choose_picker_paths(app, pilot, Path("auth-payloads.json"))

            assert app.restore_state.auth_text_file is None
            assert app.restore_state.auth_payloads_file == Path("auth-payloads.json")
            assert app.restore_state.to_recovery_request().auth_payloads_file == Path(
                "auth-payloads.json"
            )

            app.query_one("#workspace-restore-signature-source", Select).value = "auto"
            await _wait_for_condition(
                pilot,
                lambda: app.restore_state.auth_payloads_file is None,
                "automatic signature source to clear the selected file",
            )

            assert app.restore_state.auth_text_file is None
            assert app.restore_state.auth_payloads_file is None

    asyncio.run(run())


def test_textual_app_edit_restore_fields_updates_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_support.allow_ui_source_assessment(monkeypatch)

    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("2")
            await app.action_edit_primary()
            await workflow_support.choose_picker_paths(app, pilot, Path("README.md"))
            await app.action_edit_passphrase()
            await workflow_support.type_text(pilot, "demo passphrase")
            await pilot.press("enter")
            await app.action_edit_output()
            await workflow_support.save_picker_name(app, pilot, "recovered")

            assert app.restore_state.validate_task().ready
            sections = workflow_support.checklist_text(app)
            preview = workflow_support.preview_text(app)
            assert "README.md" in sections
            assert "Passphrase" in preview

    asyncio.run(run())
