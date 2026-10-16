"""Load backup documents and present their decoded contents."""

from __future__ import annotations

from textual.containers import HorizontalGroup, VerticalGroup
from textual.widgets import Button, LoadingIndicator, Static

from ethernity.app.widgets.actions import ResponsiveActions
from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    WorkspaceActionRequested,
    child_id,
    merge_classes,
    sync_action,
    sync_static,
)
from ethernity.tasks.presentation.models import SourceBodyPresentation, WorkspaceAction

__all__ = ["SourceChooser"]


class SourceChooser(VerticalGroup):
    """Load a document collection without requiring users to classify its contents."""

    def __init__(
        self,
        presentation: SourceBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._primary = Button(
            "",
            id=child_id(id, "load"),
            variant="primary",
            classes="workspace-control",
        )
        self._secondary = tuple(
            Button("", id=child_id(id, f"secondary-{index}"), classes="workspace-control")
            for index in range(2)
        )
        self._actions = ResponsiveActions(
            self._primary,
            *self._secondary,
            classes="guided-source-actions",
        )
        self._loading_status = HorizontalGroup(
            LoadingIndicator(id=child_id(id, "loading")),
            Static("Reading backup documents...", classes="guided-loading-label", markup=False),
            classes="guided-loading",
        )
        self._source_summary = Static("", classes="guided-detail", markup=False)
        self._identity = Static("", classes="guided-detail", markup=False)
        self._version = Static("", classes="guided-detail", markup=False)
        self._documents = Static("", classes="guided-detail", markup=False)
        self._unlock = Static("", classes="guided-detail", markup=False)
        self._assessment = VerticalGroup(
            self._source_summary,
            self._identity,
            self._version,
            self._documents,
            self._unlock,
            classes="guided-summary",
        )
        self._notice = InlineNotice(presentation.notice)
        super().__init__(
            self._assessment,
            self._actions,
            self._loading_status,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    def sync_presentation(self, presentation: SourceBodyPresentation) -> None:
        self._presentation = presentation
        assessment = presentation.assessment
        sync_static(self._source_summary, assessment.source_summary if assessment else "")
        sync_static(
            self._identity,
            f"Backup {assessment.backup_identity}"
            if assessment and assessment.backup_identity
            else "",
        )
        sync_static(self._version, assessment.version_summary if assessment else "")
        sync_static(self._documents, assessment.document_summary if assessment else "")
        sync_static(self._unlock, assessment.unlock_summary if assessment else "")
        self._assessment.display = assessment is not None and not presentation.loading
        sync_action(self._primary, presentation.primary_action)
        for index, button in enumerate(self._secondary):
            action = (
                presentation.secondary_actions[index]
                if index < len(presentation.secondary_actions)
                else None
            )
            sync_action(button, action)
        self._loading_status.display = presentation.loading
        self._actions.disabled = presentation.loading
        self._notice.sync_presentation(presentation.notice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action: WorkspaceAction | None = None
        if event.button is self._primary:
            action = self._presentation.primary_action
        elif event.button in self._secondary:
            index = self._secondary.index(event.button)
            if index < len(self._presentation.secondary_actions):
                action = self._presentation.secondary_actions[index]
        if action is not None and action.enabled and action.visible:
            event.stop()
            self.post_message(WorkspaceActionRequested(self, action))
