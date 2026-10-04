from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Collapsible, Static

from ethernity.app import application
from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewDetail, ReviewedTask, build_review_details
from ethernity.app.output_paths import open_documents
from ethernity.app.screens.review_task import ReviewEditRequest, ReviewTaskScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.backup_estimate import BackupEstimate
from ethernity.tasks.models import (
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskPreview,
    TaskResultDetail,
    TaskValidation,
)


def test_review_edit_returns_the_decision_and_keeps_write_safety_visible(tmp_path: Path) -> None:
    destination = tmp_path / "family-records" / "backup-documents"
    destination.mkdir(parents=True)
    outcomes: list[bool | ReviewEditRequest | None] = []
    screen = ReviewTaskScreen(
        title="Review backup",
        validation=TaskValidation(sections=()),
        preview=TaskPreview(title="Documents"),
        plan=TaskExecutionPlan(summary="Create documents", output_paths=(destination,)),
        execute_label="Create backup",
        review_details=(ReviewDetail("Destination", str(destination), "output"),),
    )

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen, outcomes.append)
            await pilot.pause()

            assert str(screen.query_one(".detail-value", Static).content) == str(destination)
            safety = screen.query_one("#review-write-safety")
            assert "may be replaced" in " ".join(
                str(line.content) for line in safety.query(Static).results(Static)
            )
            assert not any(isinstance(node, Collapsible) for node in safety.ancestors_with_self)
            screen.query_one(".review-detail-edit", Button).press()
            await pilot.pause()

    asyncio.run(run())
    assert outcomes == [ReviewEditRequest("output")]


def test_review_inventory_does_not_guess_page_counts(tmp_path: Path) -> None:
    state = BackupTaskState(input_paths=[tmp_path / "records.txt"], output_dir=tmp_path / "backup")
    details = {
        detail.label: detail.value
        for detail in build_review_details("backup", state, state.execution_plan())
    }
    assert "3 recovery sheets" in details["Documents"]
    assert details["Documents"] == (
        "Backup PDF, recovery guide, 3 recovery sheets, document inventory PDF"
    )
    assert details["Destination"] == str(tmp_path / "backup")
    assert "Pages" not in details


def test_new_destination_does_not_warn_about_overwriting(tmp_path: Path) -> None:
    screen = ReviewTaskScreen(
        title="Review",
        validation=TaskValidation(sections=()),
        preview=TaskPreview(title="Documents"),
        plan=TaskExecutionPlan(summary="Create", output_paths=(tmp_path / "new",)),
        execute_label="Create",
    )
    assert not any("replaced" in line for line in screen._write_safety_lines())


def test_reviewed_backup_keeps_the_current_typed_print_estimate(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    state = BackupTaskState(
        input_paths=[tmp_path / "record.txt"],
        output_dir=tmp_path / "backup",
        config_path=config_path,
    )
    request = state.estimate_request()
    assert request is not None
    estimate = BackupEstimate(
        file_count=1, input_bytes=32, document_bytes=80, backup_pages=2, qr_count=3
    )
    assert state.store_estimate(request, estimate)
    reviewed = ReviewedTask.capture("backup", state)
    details = {detail.label: detail.value for detail in reviewed.review_details}
    assert details["Backup pages"] == "About 2 pages in the main PDF"


def test_result_actions_send_typed_requests_and_report_generated_checks(tmp_path: Path) -> None:
    class ResultApp(EthernityApp):
        CSS_PATH = application.EthernityApp.CSS_PATH

        def __init__(self) -> None:
            super().__init__()
            self.requests: list[TaskResultScreen.ContextActionRequested] = []

        async def on_task_result_screen_context_action_requested(
            self, event: TaskResultScreen.ContextActionRequested
        ) -> None:
            event.stop()
            self.requests.append(event)

    result = TaskExecutionResult(
        status="succeeded",
        message="Backup created.",
        output_paths=(tmp_path / "backup.pdf", tmp_path / "guide.pdf", tmp_path / "kit.html"),
        recovery_check_paths=(tmp_path / "backup.pdf",),
        details=(TaskResultDetail(key="page_count", label="Pages", value=7),),
    )
    screen = TaskResultScreen(
        task="backup",
        title="Create backup",
        result=result,
        context_actions_enabled=True,
    )

    async def run() -> None:
        app = ResultApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#result-test-recovery", Button).press()
            await pilot.pause()
            assert app.requests[0].action == "test_recovery"
            assert app.requests[0].result is result
            assert app.requests[0].screen is screen
            screen.set_context_action_running("test_recovery")
            assert screen.query_one("#result-test-recovery", Button).disabled
            assert screen.query_one("#result-test-printed-pages", Button).disabled
            screen.show_context_action_result(
                "test_recovery",
                "Generated PDF recovery passed. Printed pages are untested.",
                success=True,
            )
            assert not screen.query_one("#result-test-recovery", Button).disabled
            assert "Printed pages are untested" in str(
                screen.query_one("#result-document-checks", Static).content
            )
            values = [
                str(value.content)
                for value in screen.query("#result-overview .detail-value").results(Static)
            ]
            assert "2 PDFs, 1 other file" in values
            assert "7" in values
            assert "actual printouts" in str(
                screen.query_one("#result-test-guidance", Static).content
            )

    asyncio.run(run())


def test_open_documents_uses_argument_lists(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr("ethernity.app.output_paths.sys.platform", "darwin")
    monkeypatch.setattr("ethernity.app.output_paths.subprocess.Popen", commands.append)
    documents = (tmp_path / "backup with spaces.pdf", tmp_path / "recovery.pdf")
    open_documents(documents)
    assert commands == [["open", *(str(path) for path in documents)]]


def test_generated_recovery_action_requires_typed_carriers_after_other_check(
    tmp_path: Path,
) -> None:
    screen = TaskResultScreen(
        task="backup",
        title="Backup created",
        result=TaskExecutionResult(
            status="succeeded",
            message="Created.",
            output_paths=(tmp_path / "qr_document.pdf",),
        ),
        context_actions_enabled=True,
    )

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            assert screen.query_one("#result-test-recovery", Button).disabled
            assert not screen.query_one("#result-test-printed-pages", Button).disabled
            screen.set_context_action_running("test_printed_pages")
            screen.show_context_action_result(
                "test_printed_pages", "No printed-page recovery check completed.", success=False
            )
            assert screen.query_one("#result-test-recovery", Button).disabled
            assert not screen.query_one("#result-test-printed-pages", Button).disabled

    asyncio.run(run())
