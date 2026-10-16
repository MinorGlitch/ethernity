"""One operation screen for every task, using the shared workflow events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalGroup, VerticalScroll
from textual.widgets import Button, ProgressBar, Static

from ethernity.app.operation_progress import OperationProgress, operation_steps
from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row
from ethernity.app.widgets.collapsible import collapsible_panel


class TaskProgressScreen(EthernityModalScreen[None]):
    """Keep the operation visible until its worker and cleanup have finished."""

    BINDINGS = [("escape", "request_cancel", "Cancel")]

    def __init__(
        self, *, title: str, destination: str, cancel: Callable[[], bool], task: str = "backup"
    ) -> None:
        super().__init__()
        self._title = title
        self._cancel = cancel
        self._started = monotonic()
        self._steps = operation_steps(task)
        self._active_step = 0
        self.progress = OperationProgress(destination=destination)

    def compose(self) -> ComposeResult:
        with Vertical(id="progress-modal", classes="document"):
            with Vertical(classes="document-header"):
                yield Static(self._title, classes="screen-title", markup=False)
                yield Static(id="progress-elapsed", classes="detail-label")
            with VerticalScroll(id="progress-body", classes="document-body"):
                with VerticalGroup(id="progress-steps"):
                    for index, (label, _phases) in enumerate(self._steps):
                        yield Static(label, id=f"operation-step-{index}", classes="operation-step")
                yield Static(id="progress-stage", classes="section-title", markup=False)
                yield ProgressBar(
                    total=None, show_percentage=False, show_eta=False, id="operation-bar"
                )
                yield Static(id="progress-count", markup=False)
                yield Static(id="progress-destination", markup=False, classes="detail-text")
                yield Static(id="progress-notice", markup=False, classes="detail-label")
                with collapsible_panel(
                    "progress-details", "Activity", classes="", title_classes=""
                ):
                    yield Static(id="progress-activity", markup=False)
            yield modal_action_row("progress-actions", ActionButton("Cancel", "progress-cancel"))

    def on_mount(self) -> None:
        self.set_interval(1, self._update_elapsed)
        self._update_elapsed()
        # Mount handlers run before is_mounted becomes true. Read the latest
        # progress after mounting so a queued worker update is not overwritten.
        self.call_after_refresh(lambda: self.update_progress(self.progress))
        self.query_one("#progress-cancel", Button).focus()

    def _update_elapsed(self) -> None:
        seconds = int(monotonic() - self._started)
        self.query_one("#progress-elapsed", Static).update(
            f"Elapsed {seconds // 60}:{seconds % 60:02d}"
        )

    def update_progress(self, progress: OperationProgress) -> None:
        # A queued worker update must not undo a cancellation shown immediately on click.
        if self.progress.stopping or progress.stopping:
            progress = replace(progress, stopping=True, can_cancel=False)
        if not progress.destination:
            progress = replace(progress, destination=self.progress.destination)
        self.progress = progress
        if not self.is_mounted:
            return
        for index, (_label, phases) in enumerate(self._steps):
            if progress.phase in phases:
                self._active_step = index
        for index, (label, _phases) in enumerate(self._steps):
            row = self.query_one(f"#operation-step-{index}", Static)
            row.set_class(index < self._active_step, "complete")
            row.set_class(index == self._active_step, "current")
            marker = (
                "+" if index < self._active_step else ">" if index == self._active_step else " "
            )
            row.update(f"{marker} {label}")
        self.query_one("#progress-stage", Static).update(
            "Stopping safely" if progress.stopping else progress.stage
        )
        self.query_one("#operation-bar", ProgressBar).update(
            total=None if progress.stopping else progress.total,
            progress=progress.current or 0,
        )
        self.query_one("#progress-count", Static).update(progress.count_text)
        self.query_one("#progress-destination", Static).update(
            f"Save to\n{progress.destination}" if progress.destination else ""
        )
        notice = ""
        if progress.stopping:
            notice = "Waiting for the current operation, then removing temporary files."
        elif not progress.can_cancel:
            notice = "Finishing the save. Cancellation is no longer available."
        self.query_one("#progress-notice", Static).update(notice)
        self.query_one("#progress-activity", Static).update("\n".join(progress.activity))
        self.query_one("#progress-cancel", Button).disabled = not progress.can_cancel
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "request_cancel":
            return self.progress.can_cancel
        return super().check_action(action, parameters)

    def action_request_cancel(self) -> None:
        if self._cancel():
            self.update_progress(replace(self.progress, stopping=True, can_cancel=False))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "progress-cancel":
            event.stop()
            self.action_request_cancel()
