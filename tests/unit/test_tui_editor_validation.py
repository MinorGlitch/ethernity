from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Static

from ethernity.app import input_parsers
from ethernity.app.app_types import ActiveTask
from ethernity.app.application import EthernityApp
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.crypto.sharding import MAX_SHARES
from ethernity.tasks.page_layout import BACKUP_RENDER_DOC_TYPES
from ethernity.tasks.restore import RestoreTaskState


@pytest.mark.parametrize("value", ["", "2/0", "0/2", "3/2", "2/256", "two/three"])
def test_quorum_validator_rejects_unusable_thresholds(value: str) -> None:
    assert input_parsers.validate_quorum(value) is not None


def test_validators_preserve_supported_defaults_and_domain_bounds() -> None:
    assert input_parsers.validate_quorum(f"2/{MAX_SHARES}") is None
    assert input_parsers.validate_backup_recovery("") is None
    assert input_parsers.validate_backup_recovery("single") is None
    assert input_parsers.validate_new_recovery_sheets("") is None
    assert input_parsers.validate_new_recovery_sheets("recommended") is None
    assert input_parsers.validate_optional_positive_integer("") is None
    assert input_parsers.validate_restore_target("") is None
    assert input_parsers.validate_optional_fingerprint("") is None
    assert input_parsers.validate_optional_fingerprint("AB" * 32) is None
    assert (
        input_parsers.validate_layout(
            "", fallback=("A4", "sentinel"), candidate_doc_types=BACKUP_RENDER_DOC_TYPES
        )
        is None
    )


@pytest.mark.parametrize(
    ("task", "editor_method", "invalid", "valid", "error_fragment"),
    [
        ("backup", "_edit_recovery_section", "2/0", f"2/{MAX_SHARES}", "required/total"),
        ("backup", "_edit_backup_signing_key_shards", "0/2", "2/3", "required/total"),
        ("backup", "_edit_qr_chunk_size", "0", "512", "positive"),
        ("add_files", "_edit_add_files_recovery_sheets", "3/2", "off", "required/total"),
        ("restore", "_edit_restore_target", "update 0", "update 1", "positive"),
        ("restore", "_edit_restore_target_fingerprint", "cafe", "ab" * 32, "fingerprint"),
        ("rebuild", "_edit_expected_head_fingerprint", "invalid", "ab" * 32, "fingerprint"),
        ("replace_recovery_docs", "_edit_recovery_section", "2/0", "2/3", "required/total"),
        (
            "replace_recovery_docs",
            "_edit_replace_passphrase_replacement_count",
            "0",
            "1",
            "positive",
        ),
        (
            "replace_recovery_docs",
            "_edit_replace_signing_key_replacement_count",
            "-1",
            "1",
            "positive",
        ),
        (
            "replace_recovery_docs",
            "_edit_replace_signing_key_recovery",
            "2/0",
            "2/3",
            "required/total",
        ),
        ("kit", "_edit_layout_section", "A4 unknown-design", "LETTER forge", "design"),
    ],
)
def test_specific_field_errors_keep_the_draft_open_and_task_values_unchanged(
    task: ActiveTask,
    editor_method: str,
    invalid: str,
    valid: str,
    error_fragment: str,
) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_task(task)
            before = app._current_state().model_dump()
            await getattr(app, editor_method)()
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, EditFieldScreen)
            field = editor.query_one("#edit-field-input", Input)
            field.value = invalid
            await pilot.pause()

            assert editor.query_one("#edit-field-save", Button).disabled
            assert error_fragment in str(editor.query_one("#edit-field-error", Static).content)
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is editor
            assert field.value == invalid
            assert app._current_state().model_dump() == before

            field.value = valid
            await pilot.pause()
            assert not editor.query_one("#edit-field-save", Button).disabled
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is app.screen_stack[0]

    asyncio.run(run())


def test_review_shortcut_does_not_bypass_an_invalid_field_editor() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("root.pdf")],
                passphrase="secret",
                output_path=Path("recovered"),
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_task("restore")
            await app._edit_expected_head_fingerprint()
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, EditFieldScreen)
            editor.query_one("#edit-field-input", Input).value = "invalid"
            await pilot.pause()
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.screen is editor
            assert app.restore_state.expected_head_doc_hash is None

    asyncio.run(run())


def test_review_shortcut_commits_focused_inline_destination_and_phrase() -> None:
    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("root.pdf")],
                passphrase="old phrase",
                output_path=Path("old-destination"),
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_task("restore")
            await pilot.pause()
            await pilot.click(app.query_one(WorkbenchSteps).button_for("destination"))
            await pilot.pause()
            destination = app.query_one("#workflow-restore-destination-body-value", Input)
            destination.focus()
            destination.value = "new-destination"
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.screen.query_one("#review-modal")
            assert app.restore_state.output_path == Path("new-destination")
            await pilot.click("#review-close")
            await pilot.pause()

            await pilot.click(app.query_one(WorkbenchSteps).button_for("unlock"))
            await pilot.pause()
            phrase = app.query_one("#workflow-restore-unlock-body-passphrase", Input)
            phrase.focus()
            phrase.value = "new phrase"
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.screen.query_one("#review-modal")
            assert app.restore_state.passphrase == "new phrase"
            assert phrase.value == ""

    asyncio.run(run())
