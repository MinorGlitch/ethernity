from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button, Collapsible, LoadingIndicator, RichLog, Static
from textual.worker import WorkerState

from ethernity.app.application import EthernityApp
from ethernity.app.execution import (
    ExecutionContext,
    build_review_decision_facts,
    infer_execution_failure_section,
    normalize_execution_outcome,
)
from ethernity.app.output_paths import common_output_folder, single_output_folder
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.config import apply_api_config_patch, load_app_config
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionPlan, TaskExecutionResult
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.settings import SettingsTaskState


def test_review_facts_use_plain_security_and_policy_language() -> None:
    plan = TaskExecutionPlan(summary="Review")

    backup_facts = {
        fact.label: fact.value
        for fact in build_review_decision_facts(
            "backup",
            BackupTaskState(input_paths=[Path("secret.txt")]),
            plan,
        )
    }
    assert backup_facts["Signing key"] == "Encrypted in the backup documents"

    default_facts = {
        fact.label: fact.value
        for fact in build_review_decision_facts(
            "add_files",
            AddFilesTaskState(backup_folder=Path("backup"), input_paths=[Path("new.txt")]),
            plan,
        )
    }
    assert default_facts["Recovery sheets"] == "From settings"

    reuse_facts = {
        fact.label: fact.value
        for fact in build_review_decision_facts(
            "add_files",
            AddFilesTaskState(
                backup_folder=Path("backup"),
                input_paths=[Path("new.txt")],
                unlock_policy="reuse-root",
                recovery_document_threshold=2,
                recovery_document_count=3,
            ),
            plan,
        )
    }
    assert reuse_facts["Recovery sheets"] == "3 sheets, 2 required; original recovery set"

    rebuild_facts = {
        fact.label: fact.value
        for fact in build_review_decision_facts(
            "rebuild",
            RebuildTaskState(backup_folder=Path("backup")),
            plan,
        )
    }
    assert rebuild_facts["Source version"] == "Read from backup folder"


async def _wait_for_selector(
    app: EthernityApp,
    pilot: Any,
    selector: str,
    *,
    attempts: int = 80,
) -> None:
    layout_selector = {
        "#result-modal": "#result-close",
        "#review-modal": "#review-close",
    }.get(selector, selector)
    for _ in range(attempts):
        await pilot.pause(0.05)
        widgets = list(app.screen.query(selector))
        layout_widgets = list(app.screen.query(layout_selector))
        if (
            widgets
            and layout_widgets
            and layout_widgets[0].region.width > 0
            and layout_widgets[0].region.height > 0
        ):
            return
    raise AssertionError(
        f"Timed out waiting for {selector}; screen={type(app.screen).__name__}; "
        f"exception={app._exception!r}"
    )


async def _click_when_laid_out(
    app: EthernityApp,
    pilot: Any,
    selector: str,
    *,
    attempts: int = 80,
) -> None:
    for _ in range(attempts):
        await pilot.pause(0.05)
        widgets = list(app.screen.query(selector))
        if widgets and widgets[0].region.width > 0 and widgets[0].region.height > 0:
            assert await pilot.click(selector)
            return
    raise AssertionError(f"Timed out waiting for laid-out {selector}")


def _screen_text(app: EthernityApp) -> str:
    lines = [str(widget.content) for widget in app.screen.query(Static)]
    for log in app.screen.query(RichLog):
        lines.extend(line.text for line in log.lines)
    return "\n".join(lines)


def test_execution_context_keeps_an_isolated_reviewed_snapshot(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    state = BackupTaskState(
        input_paths=[Path("secrets.txt")],
        output_dir=Path("reviewed-output"),
        config_path=config_path,
    )

    context = ExecutionContext.capture("backup", state)
    state.output_dir = Path("edited-output")
    execution_state = cast(BackupTaskState, context.execution_state())
    execution_state.output_dir = Path("attempt-only-output")

    assert cast(BackupTaskState, context.state_snapshot).output_dir == Path("reviewed-output")
    assert context.plan.output_paths == (Path("reviewed-output"),)
    facts = {fact.label: fact.value for fact in context.decision_facts}
    assert facts["Files"] == "1 file"
    assert facts["Destination"] == "reviewed-output"
    assert cast(BackupTaskState, context.execution_state()).output_dir == Path("reviewed-output")
    assert context.reviewed_config.contents == DEFAULT_CONFIG_PATH.read_bytes()


def test_execution_context_rejects_a_missing_explicit_config(tmp_path: Path) -> None:
    missing_config = tmp_path / "missing.toml"
    state = BackupTaskState(
        input_paths=[Path("secrets.txt")],
        output_dir=Path("reviewed-output"),
        config_path=missing_config,
    )

    with pytest.raises(FileNotFoundError, match="config file not found"):
        ExecutionContext.capture("backup", state)


def test_execution_outcomes_normalize_every_terminal_worker_state() -> None:
    success = TaskExecutionResult(ok=True, message="Done.")
    reported_failure = TaskExecutionResult(ok=False, message="Could not write.")

    assert normalize_execution_outcome(WorkerState.SUCCESS, value=success).result is success
    assert (
        normalize_execution_outcome(WorkerState.SUCCESS, value=reported_failure).result
        is reported_failure
    )

    wrong_type = normalize_execution_outcome(WorkerState.SUCCESS, value={"ok": True})
    assert not wrong_type.result.ok
    assert wrong_type.result.message == "Ethernity received an invalid task result."
    assert wrong_type.error_detail == "Expected TaskExecutionResult, got dict."

    exception = normalize_execution_outcome(
        WorkerState.ERROR,
        error=RuntimeError("Output is read-only."),
    )
    assert not exception.result.ok
    assert exception.result.message == "The task failed."
    assert exception.error_message == "Output is read-only."
    assert exception.error_detail == "RuntimeError: Output is read-only."
    assert infer_execution_failure_section("backup", exception) == "output"

    cancelled = normalize_execution_outcome(WorkerState.CANCELLED)
    assert not cancelled.result.ok
    assert not cancelled.allow_retry
    assert "write thread has stopped" in (cancelled.error_detail or "")


def test_review_preparation_is_visible_and_locks_the_workspace_at_80_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def prepare_review(self: AddFilesTaskState, *, force: bool = False) -> None:
        del self, force
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(AddFilesTaskState, "prepare_review", prepare_review)

    async def run() -> None:
        app = EthernityApp(
            add_files_state=AddFilesTaskState(
                backup_folder=Path("backup"),
                input_paths=[Path("new.txt")],
                passphrase="secret",
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("3")
            review_task = asyncio.create_task(app.action_review())
            try:
                for _ in range(40):
                    await pilot.pause(0.05)
                    if started.is_set():
                        break
                assert started.is_set()
                assert str(app.query_one("#canvas-primary", Button).label) == "Preparing review..."
                assert app.query_one("#canvas-primary", Button).disabled
                assert app.query_one("#task-workspaces").disabled
                assert str(app.query_one("#canvas-title", Static).content) == "Add files to backup"
            finally:
                release.set()
            await review_task
            await _wait_for_selector(app, pilot, "#review-modal")

    asyncio.run(run())


def test_background_write_identity_remains_visible_on_a_narrow_workflow() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.execution_controller._running_task = "backup"
            await pilot.press("2")
            await pilot.pause()

            assert not app.query_one("#app-header-status", Static).display
            assert str(app.query_one("#canvas-title", Static).content) == "Restore files"
            assert str(app.query_one("#canvas-primary", Button).label) == "Backup in progress"

    asyncio.run(run())


def test_background_write_identity_remains_visible_on_settings() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.execution_controller._running_task = "backup"
            await pilot.press("7")
            await pilot.pause()

            assert app.query_one("#task-action-bar").display
            assert str(app.query_one("#canvas-primary", Button).label) == "Backup in progress"

    asyncio.run(run())


def test_failure_result_prioritizes_remediation_and_reviewed_destination(tmp_path: Path) -> None:
    async def run() -> None:
        destination = tmp_path / "restored"
        partial = destination / "partial.txt"
        screen = TaskResultScreen(
            task="restore",
            title="Restore files",
            result=TaskExecutionResult(
                ok=False,
                message="Could not write restored files.",
                output_paths=(partial,),
            ),
            reviewed_plan=TaskExecutionPlan(
                summary="Restore files",
                output_paths=(destination,),
            ),
            return_section="output",
        )
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            remediation = screen.query_one("#result-remediation")
            actions = screen.query_one("#result-context-actions")
            output = screen.query_one("#result-output")
            assert remediation.region.y < actions.region.y < output.region.y
            assert str(screen.query_one("#result-reviewed-destination", Static).content).endswith(
                "/restored"
            )
            assert str(screen.query_one("#result-return", Button).label) == ("Edit destination")

    asyncio.run(run())


def test_failure_returns_to_live_workflow_after_switching_workflows(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[BackupTaskState] = []
    exit_calls: list[None] = []

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        calls.append(self.model_copy(deep=True))
        started.set()
        release.wait(timeout=5)
        return TaskExecutionResult(ok=False, message="First attempt was rejected.")

    def fake_exit(self: EthernityApp, *args: object, **kwargs: object) -> None:
        exit_calls.append(None)

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)
    monkeypatch.setattr(EthernityApp, "exit", fake_exit)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("reviewed-output"),
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.click("#review-execute")
            for _ in range(40):
                await pilot.pause(0.05)
                if started.is_set():
                    break
            assert started.is_set()

            await pilot.press("2")
            await pilot.pause()
            app.backup_state.input_paths = []
            app.backup_state.output_dir = Path("edited-while-running")

            assert app.active_task == "restore"
            assert str(app.query_one("#app-header-status", Static).content).startswith("v")
            assert str(app.query_one("#canvas-primary", Button).label) == "Backup in progress"
            assert app.query_one("#canvas-loading", LoadingIndicator).display
            assert app.query_one("#canvas-primary", Button).disabled

            await pilot.press("q")
            await pilot.pause()
            assert exit_calls == []
            assert app._running_task == "backup"

            release.set()
            await _wait_for_selector(app, pilot, "#result-modal")
            assert app._running_task is None
            failure_text = _screen_text(app)
            assert "First attempt was rejected." in failure_text
            assert "Choose at least one file or folder" not in failure_text

            await _click_when_laid_out(app, pilot, "#result-return")
            await pilot.pause()

            assert app.active_task == "backup"
            assert not list(app.query("#review-modal"))
            assert len(calls) == 1
            assert app.backup_state.input_paths == []
            assert app.backup_state.output_dir == Path("edited-while-running")

    asyncio.run(run())


def test_wrong_worker_result_is_presented_and_clears_running_state(monkeypatch) -> None:
    def fake_execute(self: BackupTaskState) -> object:
        return {"ok": True}

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.click("#review-execute")
            await _wait_for_selector(app, pilot, "#result-modal")

            assert app._running_task is None
            assert not list(app.query("#canvas-loading"))
            assert "Ethernity received an invalid task result." in _screen_text(app)
            app.screen.query_one("#result-details-panel", Collapsible).collapsed = False
            await pilot.pause()
            assert "Expected TaskExecutionResult, got dict." in _screen_text(app)
            assert app.screen.query_one("#result-return", Button)

    asyncio.run(run())


def test_return_and_new_review_capture_current_config_contents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    apply_api_config_patch(config_path, {"values": {"qr": {"chunk_size": 640}}})
    settings = SettingsTaskState.from_current(config_path)
    started = threading.Event()
    allow_config_read = threading.Event()
    observed_chunk_sizes: list[int] = []

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        if not observed_chunk_sizes:
            started.set()
            allow_config_read.wait(timeout=5)
        observed_chunk_sizes.append(load_app_config(self.config_path).qr_chunk_size)
        if len(observed_chunk_sizes) == 1:
            return TaskExecutionResult(ok=False, message="Retry with the reviewed settings.")
        return TaskExecutionResult(ok=True, message="Reviewed settings preserved.")

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            ),
            settings_state=settings,
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.click("#review-execute")
            for _ in range(40):
                await pilot.pause(0.05)
                if started.is_set():
                    break
            assert started.is_set()

            apply_api_config_patch(config_path, {"values": {"qr": {"chunk_size": 1024}}})
            allow_config_read.set()
            await _wait_for_selector(app, pilot, "#result-modal")
            await pilot.pause()

            apply_api_config_patch(config_path, {"values": {"qr": {"chunk_size": 2048}}})
            await _click_when_laid_out(app, pilot, "#result-return")
            await pilot.press("ctrl+r")
            await _wait_for_selector(app, pilot, "#review-modal")
            await pilot.pause()
            await pilot.click("#review-execute")
            for _ in range(40):
                await pilot.pause(0.05)
                if len(observed_chunk_sizes) == 2:
                    break
            assert len(observed_chunk_sizes) == 2, (
                app._running_task,
                type(app.screen).__name__,
            )
            await _wait_for_selector(app, pilot, "#result-modal")

            assert observed_chunk_sizes == [640, 2048]
            assert load_app_config(config_path).qr_chunk_size == 2048
            assert "Reviewed settings preserved" in _screen_text(app)

    asyncio.run(run())


def test_settings_persistence_is_locked_while_a_write_is_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    settings = SettingsTaskState.from_current(config_path)
    original_chunk_size = load_app_config(config_path).qr_chunk_size
    started = threading.Event()
    release = threading.Event()

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        started.set()
        release.wait(timeout=5)
        return TaskExecutionResult(ok=True, message="Write complete.")

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            ),
            settings_state=settings,
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.click("#review-execute")
            for _ in range(40):
                await pilot.pause(0.05)
                if started.is_set():
                    break
            assert started.is_set()

            await pilot.press("7")
            await pilot.pause()
            settings_form = app.query_one(SettingsForm)
            assert settings_form.disabled
            assert "Locked while task runs" in _screen_text(app)
            assert not app.settings_controller.apply_text("qr_chunk_size", "2048")

            assert load_app_config(config_path).qr_chunk_size == original_chunk_size
            assert app.settings_state.setting_value("qr_chunk_size") == original_chunk_size
            assert app.settings_state.save_status == "Locked while task runs"

            release.set()
            await _wait_for_selector(app, pilot, "#result-modal")
            assert not settings_form.disabled

    asyncio.run(run())


def test_cancelled_worker_keeps_write_lock_until_thread_returns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    settings = SettingsTaskState.from_current(config_path)
    started = threading.Event()
    release = threading.Event()
    physically_finished = threading.Event()
    execution_calls: list[None] = []
    exit_calls: list[None] = []

    def fake_execute(self: BackupTaskState) -> TaskExecutionResult:
        execution_calls.append(None)
        started.set()
        release.wait(timeout=5)
        physically_finished.set()
        return TaskExecutionResult(ok=True, message="Ignored after cancellation.")

    def fake_exit(self: EthernityApp, *args: object, **kwargs: object) -> None:
        exit_calls.append(None)

    monkeypatch.setattr(BackupTaskState, "execute", fake_execute)
    monkeypatch.setattr(EthernityApp, "exit", fake_exit)

    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            ),
            settings_state=settings,
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.press("ctrl+r")
            await pilot.click("#review-execute")
            for _ in range(40):
                await pilot.pause(0.05)
                if started.is_set():
                    break
            assert started.is_set()
            worker = app.execution_controller.running_worker
            assert worker is not None

            worker.cancel()
            for _ in range(40):
                await pilot.pause(0.05)
                if worker.state == WorkerState.CANCELLED:
                    break

            assert worker.state == WorkerState.CANCELLED
            assert app._running_task == "backup"
            assert app.execution_controller.running_worker is worker
            assert not physically_finished.is_set()
            assert not list(app.screen.query("#result-modal"))

            await pilot.press("q")
            await pilot.pause()
            assert exit_calls == []

            retry_context = ExecutionContext.capture("backup", app.backup_state)
            app.execution_controller.start(retry_context)
            await pilot.pause()
            assert execution_calls == [None]
            assert app.execution_controller.running_worker is worker

            release.set()
            await _wait_for_selector(app, pilot, "#result-modal")

            assert physically_finished.is_set()
            assert app._running_task is None
            assert app.execution_controller.running_worker is None
            assert "The write was cancelled before completion." in _screen_text(app)
            assert not list(app.screen.query("#result-return"))

    asyncio.run(run())


def test_large_result_paths_scroll_while_actions_stay_visible() -> None:
    output_paths = tuple(Path("output") / f"document-{index:03}.pdf" for index in range(50))

    async def run(size: tuple[int, int]) -> None:
        app = EthernityApp()
        async with app.run_test(size=size) as pilot:
            app.push_screen(
                TaskResultScreen(
                    task="backup",
                    title="Create backup",
                    result=TaskExecutionResult(
                        ok=True,
                        message="Backup complete.",
                        output_paths=output_paths,
                    ),
                )
            )
            await pilot.pause()

            modal = app.screen.query_one("#result-modal")
            body = app.screen.query_one("#result-body", VerticalScroll)
            actions = app.screen.query_one("#result-actions")

            assert body.max_scroll_y > 0
            assert body.region.bottom <= actions.region.y
            assert actions.region.bottom <= modal.region.bottom
            assert app.screen.query_one("#result-close", Button).region.bottom <= app.size.height

    asyncio.run(run((80, 24)))
    asyncio.run(run((60, 20)))


def test_replacement_result_reports_only_files_in_the_output_folder(monkeypatch) -> None:
    def fake_execute_mint(args: object) -> SimpleNamespace:
        return SimpleNamespace(
            output_dir="replacement-docs",
            shard_paths=(
                "replacement-docs/passphrase-1.pdf",
                "replacement-docs/passphrase-2.pdf",
            ),
            signing_key_shard_paths=("replacement-docs/signing-key-1.pdf",),
        )

    monkeypatch.setattr(
        "ethernity.tasks.replace_recovery_docs.execute_mint",
        fake_execute_mint,
    )
    state = ReplaceRecoveryDocsTaskState(
        source_paths=[Path("scan.pdf")],
        passphrase="secret",
        allow_stale_head=True,
        output_dir=Path("replacement-docs"),
        mint_signing_key_recovery=True,
    )

    result = state.execute()

    assert result.output_paths == (
        Path("replacement-docs/passphrase-1.pdf"),
        Path("replacement-docs/passphrase-2.pdf"),
        Path("replacement-docs/signing-key-1.pdf"),
    )
    assert single_output_folder(result.output_paths) == Path("replacement-docs")

    screen = TaskResultScreen(
        task="replace_recovery_docs",
        title="Create replacement sheets",
        result=result,
    )
    assert screen._open_folder_path() == Path("replacement-docs")
    assert screen._destination_summary() == "replacement-docs"


def test_output_paths_report_the_nearest_meaningful_common_folder() -> None:
    paths = (
        Path("/archive/restored/photos/family.jpg"),
        Path("/archive/restored/records/birth-certificate.pdf"),
    )

    assert single_output_folder(paths) == Path("/archive/restored")
    assert common_output_folder(paths) == "/archive/restored"
    assert single_output_folder((Path("/one/file.pdf"), Path("/two/file.pdf"))) is None
