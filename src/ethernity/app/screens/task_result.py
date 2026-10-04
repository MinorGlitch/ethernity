#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Grid, Vertical, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widgets import Button, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from ethernity.app.app_types import ActiveTask
from ethernity.app.output_paths import (
    common_output_folder,
    open_documents,
    open_folder,
    single_output_folder,
)
from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, inline_action_group, modal_action_row
from ethernity.app.widgets.collapsible import collapsible_panel
from ethernity.tasks.models import TaskExecutionPlan, TaskExecutionResult, TaskIssue
from ethernity.tasks.recovery_resources import RecoveryResourceRetry

_DOCUMENT_FINGERPRINT_RE = re.compile(r"[0-9a-fA-F]{64}")
ResultContextAction = Literal["test_recovery", "test_printed_pages"]


class TaskResultScreen(EthernityModalScreen[str | None]):
    """Post-run success or failure summary."""

    BINDINGS = [("escape", "close", "Close")]

    class ContextActionRequested(Message):
        """Ask the app to test recovery or begin a test with physical scans."""

        def __init__(self, screen: TaskResultScreen, action: ResultContextAction) -> None:
            super().__init__()
            self.screen = screen
            self.action = action
            self.task = screen._task_key
            assert screen._result is not None
            self.result = screen._result

    def __init__(
        self,
        *,
        task: ActiveTask,
        title: str,
        result: TaskExecutionResult | None = None,
        error: str | None = None,
        error_detail: str | None = None,
        recoverable_errors: tuple[TaskIssue, ...] = (),
        reviewed_plan: TaskExecutionPlan | None = None,
        return_section: str | None = None,
        allow_return: bool = True,
        return_callback: Callable[[], Awaitable[None]] | None = None,
        context_actions_enabled: bool = False,
        resource_retry: RecoveryResourceRetry | None = None,
        retry_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._task_key = task
        self._title = title
        self._result = result
        self._error = error
        self._error_detail = error_detail
        self._recoverable_errors = recoverable_errors
        self._reviewed_plan = reviewed_plan
        self._return_section = return_section
        self._allow_return = allow_return
        self._return_callback = return_callback
        self._context_actions_enabled = context_actions_enabled
        self._resource_retry = resource_retry
        self._retry_callback = retry_callback

    def compose(self) -> ComposeResult:
        success = self._result is not None and self._result.ok
        failure_tone = "warning" if self._resource_retry is not None else "failure"
        result_class = (
            "partial"
            if self._result is not None and self._result.status == "partially_succeeded"
            else "success"
            if success
            else failure_tone
        )
        with Vertical(id="result-modal", classes=f"document {result_class}"):
            with Vertical(id="result-header", classes="document-header"):
                yield Static(
                    self._result_title(success),
                    id="result-title",
                    markup=False,
                    classes="screen-title",
                )
                if self._result is not None and self._result.status == "partially_succeeded":
                    yield Static(
                        "The main write completed, but a follow-up step failed.",
                        id="result-status",
                        classes="warning",
                        markup=False,
                    )
                if not success:
                    yield Static(
                        self._failure_message(),
                        id="result-status",
                        classes=failure_tone,
                        markup=False,
                    )
            with VerticalScroll(id="result-body", classes="document-body"):
                if success:
                    yield from self._compose_success_body()
                else:
                    yield from self._compose_failure_body()

                if self._has_technical_details():
                    with collapsible_panel(
                        "result-details-panel",
                        "Technical details",
                        classes="result-details-panel",
                        title_classes="result-details-title",
                    ):
                        yield from self._compose_technical_details()

            action_buttons: list[ActionButton] = [ActionButton("Close", "result-close")]
            if not success and self._allow_return:
                action_buttons.append(
                    ActionButton(self._return_action_label(), "result-return", variant="primary")
                )
            else:
                action_buttons[0] = ActionButton("Close", "result-close", variant="primary")
            if (
                not success
                and self._resource_retry is not None
                and self._retry_callback is not None
            ):
                action_buttons.append(
                    ActionButton(
                        "Retry with higher limits", "result-retry-resources", variant="warning"
                    )
                )
            yield modal_action_row("result-actions", *action_buttons)

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_result_log)
        for checks in self.query("#result-document-checks"):
            checks.display = False
        selector = (
            "#result-return" if not self._is_success() and self._allow_return else "#result-close"
        )
        self.query_one(selector, Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "result-retry-resources" and self._retry_callback is not None:
            callback = self._retry_callback
            self._retry_callback = None
            self.app.pop_screen()
            self.app.call_later(callback)
            return
        if event.button.id == "result-open-documents":
            self._open_documents()
            return
        context_actions: dict[str, ResultContextAction] = {
            "result-test-recovery": "test_recovery",
            "result-test-printed-pages": "test_printed_pages",
        }
        context_action = context_actions.get(event.button.id or "")
        if context_action is not None and self._context_actions_enabled:
            self.post_message(self.ContextActionRequested(self, context_action))
            return
        if event.button.id == "result-copy-fingerprint":
            self._copy_fingerprint()
            return
        if event.button.id == "result-copy-paths":
            self._copy_paths()
            return
        if event.button.id == "result-open-folder":
            self._open_folder()
            return
        if event.button.id == "result-return":
            if self._return_callback is not None:
                # Pop first so focus is restored within the live workflow rather than this modal.
                self.app.pop_screen()
                scheduled = self.app.call_later(self._return_callback)
                if not scheduled:
                    self.app.notify(
                        "Ethernity could not open the workflow step. Choose the task from the "
                        "sidebar.",
                        severity="error",
                    )
                return
            self.dismiss("return")
            return
        if event.button.id == "result-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def _compose_success_body(self) -> ComposeResult:
        result = self._result
        assert result is not None
        next_steps = self._success_next_steps()

        with VerticalGroup(id="result-outcome"):
            with Grid(id="result-overview", classes="detail-grid"):
                yield Static("Destination", classes="detail-label", markup=False)
                yield Static(
                    self._destination_summary(),
                    classes="detail-value",
                    markup=False,
                )
                yield Static("Files", classes="detail-label", markup=False)
                yield Static(
                    _output_amount(self._task_key, result.output_paths),
                    classes="detail-value",
                    markup=False,
                )
                page_count = self._page_count()
                if page_count is not None:
                    yield Static("PDF pages", classes="detail-label", markup=False)
                    yield Static(
                        str(page_count),
                        classes="detail-value",
                        markup=False,
                    )

        yield from self._compose_context_actions()
        if self._context_actions_enabled and self._document_paths():
            yield inline_action_group(
                ActionButton(
                    "Test recovery",
                    "result-test-recovery",
                    disabled=not result.recovery_check_paths,
                ),
                ActionButton("Test printed pages", "result-test-printed-pages"),
                group_id="result-next-actions",
                classes="result-context-actions",
            )
            yield Static(
                "Test recovery checks the generated PDFs. Test printed pages uses scans of "
                "your actual printouts.",
                id="result-test-guidance",
                classes="detail-text",
                markup=False,
            )
            yield Static("", id="result-document-checks", markup=False)

        if next_steps:
            with VerticalGroup(id="result-next-steps"):
                yield Static("Next steps", classes="section-title", markup=False)
                for index, step in enumerate(next_steps, start=1):
                    yield Static(
                        f"{index}. {step}",
                        classes="result-next-step detail-text",
                        markup=False,
                    )

        if result.output_paths:
            with VerticalGroup(id="result-output", classes="success-output"):
                yield Static(
                    _output_section_title(self._task_key),
                    id="result-output-title",
                    markup=False,
                    classes="section-title",
                )
                yield _result_path_list(result.output_paths)

    def _compose_failure_body(self) -> ComposeResult:
        result = self._result

        tone = "warning" if self._resource_retry is not None else "failure"
        with VerticalGroup(id="result-remediation", classes=tone):
            yield Static(
                self._remediation_title(),
                classes="section-title",
                markup=False,
            )
            if self._resource_retry is not None:
                yield Static(
                    self._resource_retry.message,
                    id="result-resource-estimate",
                    classes="result-remediation-line detail-text",
                    markup=False,
                )
            elif self._recoverable_errors:
                for issue in self._recoverable_errors:
                    yield Static(
                        issue.message,
                        classes="result-remediation-line detail-text",
                        markup=False,
                    )
            else:
                yield Static(
                    self._fallback_remediation(),
                    classes="result-remediation-line detail-text",
                    markup=False,
                )
            destination = self._reviewed_destination_summary()
            if destination is not None:
                yield Static(
                    f"Reviewed destination: {destination}",
                    id="result-reviewed-destination",
                    classes="result-remediation-line detail-text",
                    markup=False,
                )

        yield from self._compose_context_actions()

        if result is not None and result.output_paths:
            with VerticalGroup(id="result-output", classes="partial-output"):
                yield Static(
                    "Partial files may remain",
                    id="result-output-title",
                    markup=False,
                    classes="section-title",
                )
                yield Static(
                    f"Inspect {common_output_folder(result.output_paths)} before retrying.",
                    id="result-partial-warning",
                    markup=False,
                )
                yield Static(
                    _partial_output_amount(result.output_paths),
                    id="result-output-count",
                    markup=False,
                    classes="detail-label",
                )
                yield _result_path_list(result.output_paths)

    def _compose_context_actions(self) -> ComposeResult:
        actions = self._context_actions()
        if actions:
            yield inline_action_group(
                *actions,
                group_id="result-context-actions",
                classes="result-context-actions",
            )

    def _compose_technical_details(self) -> ComposeResult:
        result = self._result
        if result is not None and result.details:
            with VerticalGroup(id="result-metadata"):
                yield Static("Run details", classes="detail-heading", markup=False)
                for detail in result.details:
                    yield Static(
                        f"{detail.label}: {_result_detail_value(detail.value)}",
                        classes="detail-line detail-text",
                        markup=False,
                    )

        if self._technical_detail_lines():
            yield Static("Error log", classes="detail-heading", markup=False)
            yield RichLog(
                id="result-log",
                classes="failure",
                highlight=False,
                markup=False,
                wrap=True,
            )

    def _result_title(self, success: bool) -> str:
        if self._resource_retry is not None:
            return "Restore paused"
        if success and self._result is not None and self._result.message.strip():
            return self._result.message.strip().removesuffix(".")
        if success:
            return _success_outcome_title(self._task_key)
        return _failure_title(self._task_key)

    def _is_success(self) -> bool:
        return self._result is not None and self._result.ok

    def _destination_summary(self) -> str:
        result = self._result
        if result is None or not result.output_paths:
            return "No output path"
        return common_output_folder(result.output_paths)

    def _page_count(self) -> int | None:
        result = self._result
        if result is None:
            return None
        for detail in result.details:
            if (
                detail.key in {"page_count", "pdf_page_count", "printed_pages"}
                and isinstance(detail.value, int)
                and not isinstance(detail.value, bool)
                and detail.value > 0
            ):
                return detail.value
        return None

    def _success_next_steps(self) -> tuple[str, ...]:
        if (
            self._result is not None
            and not self._result.output_paths
            and self._task_key != "settings"
        ):
            return tuple(
                dict.fromkeys(
                    (
                        "Check that the expected output exists before relying on it.",
                        *self._result.next_steps,
                    )
                )
            )
        task_steps = _success_guidance(self._task_key)
        result_steps = self._result.next_steps if self._result is not None else ()
        return tuple(dict.fromkeys((*task_steps, *result_steps)))

    def _return_step_label(self) -> str:
        for issue in self._recoverable_errors:
            if issue.section:
                return _section_label(issue.section)
        if self._return_section is not None:
            return _section_label(self._return_section)
        return "workflow"

    def _return_action_label(self) -> str:
        step = self._return_step_label()
        return "Back to workflow" if step == "workflow" else f"Edit {step}"

    def _remediation_title(self) -> str:
        if self._resource_retry is not None:
            return "Recovery limits"
        if self._recoverable_errors:
            return "Fix before retrying"
        if self._allow_return and self._return_step_label() != "workflow":
            return f"Check {self._return_step_label()}"
        return "Before another write"

    def _fallback_remediation(self) -> str:
        if self._return_section == "output":
            return "Make sure the destination is writable and has enough free space."
        if self._allow_return:
            return "Check the inputs, then run the task again."
        return "Inspect the destination before starting another write."

    def _context_actions(self) -> tuple[ActionButton, ...]:
        actions: list[ActionButton] = []
        if self._is_success() and self._document_paths():
            actions.append(ActionButton("Open documents", "result-open-documents"))
        if self._document_fingerprint() is not None:
            actions.append(ActionButton("Copy fingerprint", "result-copy-fingerprint"))
        if self._copy_paths_text() is not None:
            copy_label = "Copy paths" if self._reported_output_paths() else "Copy destination"
            actions.append(ActionButton(copy_label, "result-copy-paths"))
        if self._open_folder_path() is not None:
            actions.append(ActionButton("Open folder", "result-open-folder"))
        return tuple(actions)

    def _document_paths(self) -> tuple[Path, ...]:
        return tuple(
            path for path in self._reported_output_paths() if path.suffix.lower() == ".pdf"
        )

    def show_context_action_result(
        self, action: ResultContextAction, message: str, *, success: bool
    ) -> None:
        """Display the app's test outcome without implying that paper was verified."""

        checks = self.query_one("#result-document-checks", Static)
        checks.update(message)
        checks.set_class(success, "success")
        checks.set_class(not success, "failure")
        checks.display = True
        self._set_context_actions_disabled(False)

    def set_context_action_running(self, action: ResultContextAction) -> None:
        self._set_context_actions_disabled(True)
        checks = self.query_one("#result-document-checks", Static)
        checks.remove_class("success", "failure")
        checks.update(
            "Testing recovery from generated PDFs..."
            if action == "test_recovery"
            else "Testing recovery from printed-page scans..."
        )
        checks.display = True

    def _set_context_actions_disabled(self, disabled: bool) -> None:
        for button in self.query("#result-next-actions Button").results(Button):
            button.disabled = disabled or (
                button.id == "result-test-recovery"
                and (self._result is None or not self._result.recovery_check_paths)
            )

    def _open_documents(self) -> None:
        try:
            open_documents(self._document_paths())
        except OSError as exc:
            self.app.notify(f"Ethernity could not open the documents: {exc}", severity="error")
            return
        self.app.notify("Opening generated documents.")

    def _has_technical_details(self) -> bool:
        result = self._result
        return bool(
            (result is not None and result.details)
            or self._error_detail
            or any(issue.code for issue in self._recoverable_errors)
        )

    def _open_folder_path(self) -> Path | None:
        reported = self._reported_output_paths()
        if reported:
            return single_output_folder(reported)
        planned = self._planned_output_paths()
        if not planned:
            return None
        if self._task_key in {"backup", "restore", "rebuild", "replace_recovery_docs"}:
            return _nearest_existing_folder(planned[0])
        folder = single_output_folder(planned)
        return _nearest_existing_folder(folder) if folder is not None else None

    def _copy_paths_text(self) -> str | None:
        paths = self._reported_output_paths() or self._planned_output_paths()
        if not paths:
            return None
        return "\n".join(str(path) for path in paths)

    def _reported_output_paths(self) -> tuple[Path, ...]:
        result = self._result
        return result.output_paths if result is not None else ()

    def _planned_output_paths(self) -> tuple[Path, ...]:
        if self._is_success() or self._reviewed_plan is None:
            return ()
        return self._reviewed_plan.output_paths

    def _reviewed_destination_summary(self) -> str | None:
        paths = self._planned_output_paths()
        if not paths:
            return None
        return "\n".join(str(path) for path in paths)

    def _document_fingerprint(self) -> str | None:
        result = self._result
        if result is None or not result.ok:
            return None
        for detail in result.details:
            value = detail.value
            if (
                detail.key == "doc_hash"
                and isinstance(value, str)
                and _DOCUMENT_FINGERPRINT_RE.fullmatch(value) is not None
            ):
                return value
        return None

    def _copy_fingerprint(self) -> None:
        fingerprint = self._document_fingerprint()
        if fingerprint is None:
            return
        self.app.copy_to_clipboard(fingerprint)
        self.app.notify("Document fingerprint copied.")

    def _copy_paths(self) -> None:
        paths_text = self._copy_paths_text()
        if paths_text is None:
            return
        self.app.copy_to_clipboard(paths_text)
        message = "Output paths copied." if self._reported_output_paths() else "Destination copied."
        self.app.notify(message)

    def _open_folder(self) -> None:
        folder = self._open_folder_path()
        if folder is None:
            return
        try:
            open_folder(folder)
        except OSError as exc:
            self.app.notify(f"Ethernity could not open the folder: {exc}", severity="error")
            return
        self.app.notify("Opening output folder.")

    def _technical_detail_lines(self) -> tuple[str, ...]:
        lines = [self._error_detail] if self._error_detail else []
        lines.extend(
            f"{issue.code}: {issue.message}" for issue in self._recoverable_errors if issue.code
        )
        return tuple(lines)

    def _refresh_result_log(self) -> None:
        result_logs = list(self.query("#result-log").results(RichLog))
        if not result_logs:
            return
        log = result_logs[0]
        log.clear()
        for line in self._technical_detail_lines():
            log.write(line)

    def _failure_message(self) -> str:
        if self._error:
            return self._error
        if self._result is not None and self._result.message:
            return self._result.message
        return "The task stopped before it completed."


def _result_path_list(paths: tuple[Path, ...]) -> OptionList:
    return OptionList(
        *(Option(Content.from_text(str(path), markup=False)) for path in paths),
        id="result-output-paths",
        compact=True,
    )


def _nearest_existing_folder(path: Path | None) -> Path | None:
    if path is None:
        return None
    candidate = path if path.is_dir() else path.parent
    for folder in (candidate, *candidate.parents):
        if folder.exists() and folder.is_dir():
            return folder
    return None


def _success_outcome_title(task: ActiveTask) -> str:
    return {
        "backup": "Backup created",
        "restore": "Files restored",
        "add_files": "Backup update created",
        "rebuild": "Backup rebuilt",
        "replace_recovery_docs": "Replacement recovery sheets created",
        "kit": "Offline recovery kit created",
        "settings": "Settings saved",
    }[task]


def _failure_title(task: ActiveTask) -> str:
    return {
        "backup": "Backup failed",
        "restore": "Restore failed",
        "add_files": "Backup update failed",
        "rebuild": "Rebuild failed",
        "replace_recovery_docs": "Recovery sheet replacement failed",
        "kit": "Offline recovery kit failed",
        "settings": "Settings save failed",
    }[task]


def _output_amount(task: ActiveTask, paths: tuple[Path, ...]) -> str:
    pdf_count = sum(path.suffix.lower() == ".pdf" for path in paths)
    if pdf_count:
        documents = f"{pdf_count} {'PDF' if pdf_count == 1 else 'PDFs'}"
        other_count = len(paths) - pdf_count
        if other_count:
            documents += f", {other_count} other {'file' if other_count == 1 else 'files'}"
        return documents
    count = len(paths)
    singular, plural = {
        "backup": ("backup file", "backup files"),
        "restore": ("restored path", "restored paths"),
        "add_files": ("PDF", "PDFs"),
        "rebuild": ("rebuilt backup file", "rebuilt backup files"),
        "replace_recovery_docs": ("replacement file", "replacement files"),
        "kit": ("offline recovery kit PDF", "offline recovery kit PDFs"),
        "settings": ("output", "outputs"),
    }[task]
    return f"{count} {singular if count == 1 else plural}"


def _partial_output_amount(paths: tuple[Path, ...]) -> str:
    noun = "path" if len(paths) == 1 else "paths"
    return f"The task reported {len(paths)} {noun} before it failed."


def _section_label(section: str) -> str:
    return {
        "advanced": "advanced options",
        "authentication": "signature check",
        "backup": "backup source",
        "files": "files",
        "freshness": "source freshness",
        "output": "destination",
        "qr": "QR setup",
        "recovery": "recovery setup",
        "signature": "signing-key recovery",
        "source": "source",
        "target": "backup version",
        "unlock": "unlock method",
    }.get(section, section.replace("_", " "))


def _output_section_title(task: ActiveTask) -> str:
    if task == "restore":
        return "Files restored"
    return "Files created"


def _result_detail_value(value: str | int | bool | None | tuple[str, ...]) -> str:
    if isinstance(value, tuple):
        return ", ".join(value) if value else "none"
    return "none" if value is None else str(value)


def _success_guidance(task: ActiveTask) -> tuple[str, ...]:
    if task == "backup":
        return (
            "Print every PDF at actual size.",
            "Test recovery from scans of the printed set before storing it.",
            "Store recovery sheets apart from encrypted backup documents.",
        )
    if task == "kit":
        return (
            "Print the PDF at actual size.",
            "The kit restores supplied documents. It cannot check for newer copies elsewhere.",
        )
    if task == "restore":
        return (
            "Check the restored files before deleting scans or backup media.",
            "Compare same-name files in the destination with the source files.",
        )
    if task == "replace_recovery_docs":
        return (
            "Print every replacement sheet at actual size.",
            "Test recovery using the required number of matching replacement sheets.",
            "Store the new sheets before retiring the old set.",
        )
    if task == "add_files":
        return (
            "Print every new PDF at actual size.",
            "Test the new backup with the reusable recovery kit.",
            "Keep the original backup and every update needed for recovery.",
        )
    if task == "rebuild":
        return (
            "Print every new PDF at actual size.",
            "Test recovery from the rebuilt documents and new recovery sheets.",
            "Store the sheets with the matching backup version.",
        )
    return ()
