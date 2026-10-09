from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import cast

import pytest
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    MarkdownViewer,
    ProgressBar,
    RichLog,
    Static,
)

from ethernity.app.application import EthernityApp
from ethernity.app.screens.task_progress import TaskProgressScreen
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.workflows.shared import events
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    click_when_ready,
    wait_for_condition as _wait_for_condition,
    wait_for_focus,
    wait_for_widget,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_editors_and_review_open_centered() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await app.action_edit_passphrase()
            await pilot.pause()
            edit_region = app.screen.query_one("#edit-field-modal").region
            assert edit_region.x > 0
            assert edit_region.y > 0

            await pilot.press("escape")
            await app.action_edit_primary()
            await pilot.pause()
            picker_region = app.screen.query_one("#file-picker-modal").region
            assert picker_region.x > 0
            assert picker_region.y > 0

            await pilot.press("escape")
            app.backup_state.input_paths = [Path("README.md")]
            app.backup_state.output_dir = Path("backup-out")
            app.refresh_task_view()
            await pilot.press("ctrl+r")
            review_region = app.screen.query_one("#review-modal").region
            assert review_region.x == (120 - review_region.width) // 2
            assert review_region.y == 0
            assert review_region.width == 100
            assert review_region.height == 31

    asyncio.run(run())


def test_textual_app_blocked_review_focuses_first_requirement() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")

            assert not list(app.screen.query("#review-modal"))
            assert app.screen.focused is app.query_one("#workspace-backup-files", Button)
            assert "Next required action" in workflow_support.preview_text(app)
            assert "Choose at least one file or folder" in workflow_support.preview_text(app)

    asyncio.run(run())


@pytest.mark.portability
def test_textual_app_shows_progress_screen_while_task_runs(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        started.set()
        assert release.wait(timeout=30), "Test did not release the backup worker."
        return TaskExecutionResult(
            status="succeeded",
            message="Slow backup complete.",
            output_paths=(Path("backup-out/main.pdf"),),
        )

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            assert not list(app.query("#canvas-loading"))
            await pilot.press("ctrl+r")
            await click_when_ready(pilot, "#review-execute")

            try:
                await _wait_for_condition(pilot, started.is_set, "worker to start")
                destination = await wait_for_widget(pilot, "#progress-destination")
                expected = str(Path("backup-out") / "backup-<id>")
                await _wait_for_condition(
                    pilot,
                    lambda: expected in str(cast(Static, destination).content),
                    "progress destination to populate",
                )

                assert started.is_set()
                assert app.running_task == "backup"
                assert isinstance(app.screen, TaskProgressScreen)
                assert app.screen.query_one("#operation-bar", ProgressBar).total is None
                assert expected in workflow_support.static_text(app, "#progress-destination")
                assert not app.screen.query_one("#progress-cancel", Button).disabled
            finally:
                release.set()
            await wait_for_widget(pilot, "#result-close")

            assert app.running_task is None
            assert "Slow backup complete" in workflow_support.read_result_text(app)
            workflow_support.assert_success_result_modal_layout(app)
            assert not any(isinstance(screen, TaskProgressScreen) for screen in app.screen_stack)

    asyncio.run(run())


def test_textual_app_review_can_execute_ready_backup(monkeypatch) -> None:
    calls: list[BackupTaskState] = []
    copied_paths: list[str] = []

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake backup complete.",
            output_paths=(Path("backup-out/main.pdf"),),
        )

    def fake_copy_to_clipboard(self: EthernityApp, text: str) -> None:
        copied_paths.append(text)

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)
    monkeypatch.setattr(EthernityApp, "copy_to_clipboard", fake_copy_to_clipboard)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")

            assert workflow_support.static_text(app, "#review-title") == "Review backup"
            assert not list(app.screen.query("#review-status"))
            assert not list(app.screen.query("#review-summary"))
            review_text = workflow_support.read_review_text(app)
            assert "Confirm this action" not in review_text
            assert "Create backup documents in backup-out" in review_text
            assert workflow_support.button_label(app, "#review-execute") == "Create backup"
            assert "Reads" in review_text
            assert "secrets.txt" in review_text
            assert "The signing key will be embedded in the backup documents." in review_text
            assert "Store recovery sheets separately from encrypted backup documents." in (
                review_text
            )
            assert str(Path("backup-out").absolute()) in review_text
            assert "A new backup-<id> folder will be created inside the destination." in review_text
            assert "Existing backups stay unchanged." in review_text

            await click_when_ready(pilot, "#review-execute")
            await _wait_for_condition(pilot, lambda: bool(calls), "execution to start")

            assert [str(path) for path in calls[0].input_paths] == ["secrets.txt"]
            await wait_for_widget(pilot, "#result-close")

            result_text = workflow_support.read_result_text(app)
            assert "Fake backup complete" in result_text
            workflow_support.assert_success_result_modal_layout(app)
            assert "Destination\nbackup-out" in result_text
            assert "Files\n1 PDF" in result_text
            assert "\nmain.pdf" in result_text
            assert "Print every PDF at actual size." in result_text
            assert "Create and store a recovery kit if you do not already have one." not in (
                result_text
            )
            assert workflow_support.button_label(app, "#result-copy-paths") == "Copy paths"
            assert workflow_support.button_label(app, "#result-open-folder") == "Open folder"
            await pilot.click("#result-copy-paths")
            await pilot.pause()

            assert copied_paths == [str(Path("backup-out/main.pdf"))]

            await pilot.click("#result-close")
            await pilot.pause()
            assert "Fake backup complete." in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_backup_review_shows_risky_recovery_warning() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
                recovery_method="single_phrase",
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert "Warning" in review_text
            assert "One recovery phrase is a single secret" in review_text
            assert "One recovery phrase" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_backup_review_shows_custom_qr_warning() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
                qr_chunk_size=384,
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert "Warning" in review_text
            assert "Custom QR density can change page count" in review_text
            assert "QR density" in review_text
            assert "384 bytes" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_review_can_execute_print_kit(monkeypatch) -> None:
    calls: list[PrintKitTaskState] = []

    def fake_execute(self: PrintKitTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake kit complete.",
            output_paths=(Path("kit.pdf"),),
        )

    monkeypatch.setattr(PrintKitTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=Path("kit.pdf")))
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")
            assert "kit.pdf (current folder)" in workflow_support.checklist_text(app)

            await pilot.press("ctrl+r")

            assert not list(app.screen.query("#review-status"))
            assert not list(app.screen.query("#review-summary"))
            review_text = workflow_support.read_review_text(app)
            assert "Confirm this action" not in review_text
            assert "Create offline recovery kit PDF at kit.pdf (current folder)" in review_text
            assert workflow_support.button_label(app, "#review-execute") == "Create PDF"
            assert f"Destination\n{Path('kit.pdf').absolute()}" in review_text
            assert "No user files are read before this action runs." not in review_text
            assert (
                "Ethernity will create the PDF at the selected path. Its parent folder must be "
                "writable."
            ) in review_text
            assert "This offline recovery kit cannot authenticate" in review_text

            await click_when_ready(pilot, "#review-execute")
            await _wait_for_condition(pilot, lambda: bool(calls), "execution to start")

            assert str(calls[0].output_path) == "kit.pdf"
            await wait_for_widget(pilot, "#result-close")

            result_text = workflow_support.read_result_text(app)
            assert "Fake kit complete" in result_text
            workflow_support.assert_success_result_modal_layout(app)
            assert "Files\n1 PDF" in result_text
            assert "kit.pdf" in result_text
            assert "Print the PDF at actual size." in result_text
            assert workflow_support.button_label(app, "#result-open-folder") == "Open folder"
            await pilot.click("#result-close")
            await pilot.pause()
            assert "Fake kit complete." in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_print_kit_review_shows_custom_qr_warning() -> None:
    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=Path("kit.pdf"), chunk_size=512))
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")
            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert "Warning" in review_text
            assert "Custom sizing can change page count and make codes harder to scan" in (
                review_text
            )
            assert "QR sizing" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_review_shows_new_backup_inside_existing_parent(tmp_path) -> None:
    async def run() -> None:
        output_dir = tmp_path / "backup-out"
        output_dir.mkdir()
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=output_dir,
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            assert not app.query_one("#backup-destination-status").display
            assert "backup-<id>" in workflow_support.static_text(app, "#backup-output-value")
            assert "Selected output folder already exists" not in workflow_support.preview_text(app)

            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert str(output_dir / "backup-<id>") in review_text
            assert "Existing destination:" not in review_text
            assert "may be replaced" not in review_text
            assert "Existing backups stay unchanged" in review_text

    asyncio.run(run())


def test_write_workflows_apply_their_destination_policy(tmp_path) -> None:
    backup_output = tmp_path / "backup-out"
    rebuild_output = tmp_path / "rebuilt"
    replacement_output = tmp_path / "replacement-docs"
    kit_output = tmp_path / "kit.pdf"
    for output_dir in (backup_output, rebuild_output, replacement_output):
        output_dir.mkdir()
    kit_output.write_text("existing", encoding="utf-8")

    states = (
        (
            BackupTaskState(input_paths=[Path("secrets.txt")], output_dir=backup_output),
            "ready",
            None,
        ),
        (
            RebuildTaskState(
                backup_folder=Path("docs"),
                passphrase="secret",
                allow_stale_head=True,
                output_dir=rebuild_output,
            ),
            "ready",
            None,
        ),
        (
            ReplaceRecoveryDocsTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                allow_stale_head=True,
                output_dir=replacement_output,
            ),
            "blocked",
            None,
        ),
        (
            PrintKitTaskState(output_path=kit_output),
            "warning",
            "Selected PDF file already exists",
        ),
    )

    for state, expected_status, warning_text in states:
        output_section = next(
            section for section in state.validate_task().sections if section.key == "output"
        )
        assert output_section.status == expected_status
        output_warnings = [
            warning for warning in state.preview().warnings if warning.section == "output"
        ]
        if warning_text is None:
            assert not output_warnings
        else:
            assert "Existing" in output_section.summary
            assert any(warning_text in warning.message for warning in output_warnings)


def test_textual_app_restore_review_shows_destination_conflict_safety(tmp_path) -> None:
    async def run() -> None:
        restore_dir = tmp_path / "recovered"
        restore_dir.mkdir()
        (restore_dir / "existing.txt").write_text("keep me")
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=restore_dir,
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("2")

            assert app.query_one("#workflow-restore-destination-body-value", Input).value == str(
                restore_dir
            )
            assert (
                "The restore folder contains files or folders; restored files with matching "
                "names may be replaced." in workflow_support.preview_text(app)
            )

            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert f"Destination\n{restore_dir}" in review_text
            assert (
                "The restore folder contains files or folders; restored files with matching "
                "names may be replaced." in review_text
            )

    asyncio.run(run())


def test_textual_app_review_cancel_returns_without_losing_inputs() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")

            assert not list(app.screen.query("#review-status"))

            await pilot.click("#review-close")
            await pilot.pause()

            assert not list(app.screen.query("#review-modal"))
            assert [str(path) for path in app.backup_state.input_paths] == ["secrets.txt"]
            assert app.backup_state.output_dir == Path("backup-out")
            assert workflow_support.button_label(app, "#canvas-primary") == "Continue >"

    asyncio.run(run())


def test_textual_app_review_can_execute_ready_restore(monkeypatch) -> None:
    calls: list[RestoreTaskState] = []

    def fake_execute(self: RestoreTaskState) -> TaskExecutionResult:
        calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake restore complete.",
            output_paths=(Path("recovered/secrets.txt"), Path("recovered/notes.txt")),
        )

    monkeypatch.setattr(RestoreTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            restore_state=RestoreTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                output_path=Path("recovered"),
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("2")
            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert "Recover files into recovered" in review_text
            assert "Backup source" in review_text
            assert "1 scanned page" in review_text
            assert "scan.pdf" in review_text
            assert "Signature\nTrusted signature required" in review_text
            assert "Signature check: Trusted signatures required" in review_text
            assert "Verification source: Loaded backup" in review_text
            assert "Unlock: Passphrase" in review_text
            assert workflow_support.button_label(app, "#review-execute") == "Restore files"
            assert "The restore folder does not exist and will be created." in review_text

            await click_when_ready(pilot, "#review-execute")
            await _wait_for_condition(pilot, lambda: bool(calls), "execution to start")

            assert calls[0].output_path == Path("recovered")
            await wait_for_widget(pilot, "#result-close")

            result_text = workflow_support.read_result_text(app)
            assert "Fake restore complete" in result_text
            workflow_support.assert_success_result_modal_layout(app)
            assert "Destination\nrecovered" in result_text
            assert "2 restored paths" in result_text
            assert "\nsecrets.txt\nnotes.txt" in result_text
            assert "Check the restored files" in result_text
            assert "Compare same-name files in the destination" in result_text

    asyncio.run(run())


def test_textual_app_rebuild_review_shows_stale_source_warning() -> None:
    async def run() -> None:
        app = EthernityApp(
            rebuild_state=RebuildTaskState(
                source_paths=[Path("scan.pdf")],
                passphrase="secret",
                allow_stale_head=True,
                output_dir=Path("rebuilt"),
            )
        )
        async with run_app_test(app, size=(120, 40)) as pilot:
            await pilot.press("4")
            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert "Warning" in review_text
            assert "The loaded documents may omit a newer backup version" in review_text
            assert "Source version\nLatest loaded version accepted" in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())


def test_textual_app_review_can_execute_maintenance_workflows(monkeypatch) -> None:
    add_calls: list[AddFilesTaskState] = []
    rebuild_calls: list[RebuildTaskState] = []
    replace_calls: list[ReplaceRecoveryDocsTaskState] = []

    def fake_add_files_execute(self: AddFilesTaskState) -> TaskExecutionResult:
        add_calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake update complete.",
            output_paths=(
                Path("update-out/update.pdf"),
                Path("update-out/update-recovery.pdf"),
            ),
        )

    def fake_rebuild_execute(self: RebuildTaskState) -> TaskExecutionResult:
        rebuild_calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake rebuild complete.",
            output_paths=(Path("rebuilt/main.pdf"), Path("rebuilt/recovery.pdf")),
        )

    def fake_replace_execute(self: ReplaceRecoveryDocsTaskState) -> TaskExecutionResult:
        replace_calls.append(self)
        return TaskExecutionResult(
            status="succeeded",
            message="Fake replacement complete.",
            output_paths=(
                Path("replacement-docs/recovery.pdf"),
                Path("replacement-docs/recovery-sheet-01.pdf"),
            ),
        )

    monkeypatch.setattr(AddFilesTaskState, "execute", fake_add_files_execute)
    monkeypatch.setattr(
        AddFilesTaskState,
        "prepare_review",
        lambda _self, *, force=False: None,
    )
    monkeypatch.setattr(RebuildTaskState, "execute", fake_rebuild_execute)
    monkeypatch.setattr(ReplaceRecoveryDocsTaskState, "execute", fake_replace_execute)

    async def run() -> None:
        await workflow_support.exercise_add_files_review()

        await workflow_support.exercise_rebuild_review()

        await workflow_support.exercise_replacement_review()

    asyncio.run(run())


def test_textual_app_execution_failure_shows_result_screen(monkeypatch) -> None:
    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        events.emit_phase(phase="save", label="Saving output")
        raise RuntimeError("Printer path is not writable.")

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await click_when_ready(pilot, "#review-execute")
            await wait_for_widget(pilot, "#result-close")

            result_text = workflow_support.read_result_text(app)
            assert "Backup failed" in result_text
            assert "Printer path is not writable." in result_text
            assert not list(app.screen.query(MarkdownViewer))
            assert "Check destination" in result_text
            assert "Make sure the destination is writable" in result_text
            assert "Reviewed destination: backup-out" in result_text
            assert app.screen.query_one("#result-details-panel", Collapsible).collapsed
            assert app.screen.query_one("#result-log", RichLog)

            app.screen.query_one("#result-details-panel", Collapsible).focus()
            await pilot.press("enter")

            assert not app.screen.query_one("#result-details-panel", Collapsible).collapsed
            assert (
                "RuntimeError: Printer path is not writable."
                in workflow_support.read_result_text(app)
            )
            assert workflow_support.button_label(app, "#result-return") == "Edit destination"

            await click_when_ready(pilot, "#result-return")
            await wait_for_focus(pilot, app.query_one("#workspace-backup-output", Button))

            assert not list(app.screen.query("#result-modal"))
            assert not list(app.screen.query("#review-modal"))
            assert app.active_task == "backup"
            assert app.screen.focused is app.query_one("#workspace-backup-output", Button)

    asyncio.run(run())
