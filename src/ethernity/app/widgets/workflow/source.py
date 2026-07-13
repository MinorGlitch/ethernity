"""Source selection widget for guided workflows."""

from __future__ import annotations

from textual.containers import HorizontalGroup, VerticalGroup
from textual.message import Message
from textual.widgets import Button, LoadingIndicator, RadioSet, Static

from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    KeyedRadioSet,
    child_id,
    merge_classes,
    sync_action,
    sync_static,
)
from ethernity.app.widgets.workflow.styles import GUIDED_WORKFLOW_CSS
from ethernity.tasks.presentation.models import SourceBodyPresentation, WorkspaceAction

__all__ = ["SourceChooser"]


class SourceChooser(VerticalGroup):
    """Select a source method and show typed source assessment facts."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

    class MethodChanged(Message):
        def __init__(self, chooser: SourceChooser, method_key: str) -> None:
            super().__init__()
            self.chooser = chooser
            self.method_key = method_key

        @property
        def control(self) -> SourceChooser:
            return self.chooser

    class ActionRequested(Message):
        def __init__(self, chooser: SourceChooser, action: WorkspaceAction) -> None:
            super().__init__()
            self.chooser = chooser
            self.action = action

        @property
        def control(self) -> SourceChooser:
            return self.chooser

    def __init__(
        self,
        presentation: SourceBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._choosing_method = False
        self._methods = KeyedRadioSet(
            presentation.methods,
            id=child_id(id, "methods"),
        )
        self._loading = LoadingIndicator(id=child_id(id, "loading"))
        self._loading_status = HorizontalGroup(
            self._loading,
            Static("Inspecting backup source...", classes="guided-loading-label", markup=False),
            classes="guided-loading",
        )
        self._source_type = Static("", classes="guided-detail", markup=False)
        self._material = Static("", classes="guided-detail", markup=False)
        self._identity = Static("", classes="guided-detail", markup=False)
        self._version = Static("", classes="guided-detail", markup=False)
        self._assessment = VerticalGroup(
            self._source_type,
            self._material,
            self._identity,
            self._version,
            classes="guided-summary",
        )
        self._change = Button(
            "",
            id=child_id(id, "change"),
            compact=True,
            classes="workspace-control",
        )
        self._notice = InlineNotice(presentation.notice)
        super().__init__(
            self._methods,
            self._loading_status,
            self._assessment,
            self._change,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def selected_method(self) -> str | None:
        return self._methods.selected_key

    def sync_presentation(self, presentation: SourceBodyPresentation) -> None:
        if presentation.loading or presentation.assessment != self._presentation.assessment:
            self._choosing_method = False
        self._presentation = presentation
        self._methods.sync_choices(presentation.methods)
        if self._choosing_method:
            self._methods.clear_selection()
        self._loading_status.display = presentation.loading
        assessment = presentation.assessment
        sync_static(
            self._source_type,
            f"Source: {assessment.source_label}" if assessment else "",
        )
        sync_static(
            self._material,
            f"Material: {assessment.material_summary}" if assessment else "",
        )
        sync_static(
            self._identity,
            f"Backup: {assessment.backup_identity}"
            if assessment and assessment.backup_identity
            else "",
        )
        sync_static(
            self._version,
            f"Version: {assessment.version_summary}"
            if assessment and assessment.version_summary
            else "",
        )
        sync_action(self._change, presentation.change_action)
        self._notice.sync_presentation(presentation.notice)
        self._sync_mode()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set is not self._methods:
            return
        event.stop()
        method_key = self._methods.key_for_button(event.pressed)
        if method_key is not None:
            self._choosing_method = False
            self._sync_mode()
            self.post_message(self.MethodChanged(self, method_key))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._change or self._presentation.change_action is None:
            return
        event.stop()
        if self._presentation.assessment is None:
            self.post_message(self.ActionRequested(self, self._presentation.change_action))
            return
        self._choosing_method = True
        self._methods.clear_selection()
        self._sync_mode()
        self._methods.focus()

    def _sync_mode(self) -> None:
        loading = self._presentation.loading
        assessed = self._presentation.assessment is not None
        choosing = assessed and self._choosing_method and not loading
        self._methods.display = (not assessed and not loading) or choosing
        self._assessment.display = assessed and not loading and not choosing
        action = self._presentation.change_action
        self._change.display = action is not None and action.visible and not choosing
        notice = self._presentation.notice
        self._notice.display = notice is not None and bool(notice.message) and not choosing
