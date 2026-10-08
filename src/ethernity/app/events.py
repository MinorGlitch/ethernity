from __future__ import annotations

from pathlib import Path
from typing import cast

from textual import events
from textual.widget import Widget
from textual.widgets import Button, Input, ListView, MaskedInput, RadioSet, Select, Switch

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import UnlockTaskState
from ethernity.app.editing.definitions import OutputEditorDefinition
from ethernity.app.help_content import build_help_content
from ethernity.app.recovery_check_requests import generated_recovery_request
from ethernity.app.screens.help import HelpScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.app.widgets.workflow.controls import (
    KeyedRadioSet,
    WorkspaceActionRequested,
)
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.app.widgets.workflow.steps import WorkflowStep
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.app.workflow_presenter import step_for_section
from ethernity.app.workflow_registry import WORKFLOWS, workflow_definition
from ethernity.app.workspaces.workspace_controls import BaseWorkspace
from ethernity.tasks.task_types import TaskKey


class AppEventHandlers(EthernityAppContext):
    """Textual lifecycle and event routing for the app shell."""

    def on_mount(self) -> None:
        self.refresh_task_view()
        self.call_after_refresh(self._focus_active_task, self.active_task)

    def on_resize(self, event: events.Resize) -> None:
        event.stop()
        if self._nav_menu_open:
            self._close_nav_menu()

    def on_click(self, event: events.Click) -> None:
        if not self._nav_menu_open or self.screen is not self.screen_stack[0]:
            return
        if any(
            self.query_one(selector).region.contains(event.screen_x, event.screen_y)
            for selector in ("#nav-menu", "#workbench-navigation")
        ):
            return
        self._close_nav_menu(restore_focus=False)

    async def action_help(self) -> None:
        await self.push_screen(HelpScreen(build_help_content(task=self.active_task)))

    async def on_task_result_screen_context_action_requested(
        self, event: TaskResultScreen.ContextActionRequested
    ) -> None:
        event.stop()
        reviewed = self._last_reviewed_task
        if (
            reviewed is None
            or event.result is not self._last_execution_result
            or reviewed.task != event.task
            or self.running_task is not None
            or self.recovery_check_controller.running
            or self.screen is not event.screen
        ):
            return
        if not event.result.recovery_check_paths:
            return
        self.recovery_check_controller.start(
            generated_recovery_request(reviewed, event.result), event.screen, event.action
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if self._nav_menu_open and button_id not in {"nav-manage", "nav-tools"}:
            self._close_nav_menu(restore_focus=False)
        if button_id in {"nav-create", "nav-restore"}:
            event.stop()
            await self._show_task("backup" if button_id == "nav-create" else "restore")
            self.call_after_refresh(self._focus_active_task, self.active_task)
        elif button_id in {"nav-manage", "nav-tools"}:
            event.stop()
            self._toggle_navigation_menu(button_id)
        elif button_id == "canvas-back":
            event.stop()
            key = self.query_one(TaskCanvas).adjacent_step(-1)
            if key is not None:
                await self._select_workbench_step(key)
        elif button_id == "canvas-primary":
            event.stop()
            await self.action_primary()
        elif button_id == "canvas-internals":
            event.stop()
            await self.action_diagnostics()
        elif button_id is not None and button_id.startswith("setting-control-"):
            event.stop()
            await self.settings_controller.edit(button_id.removeprefix("setting-control-"))
        elif button_id is not None and button_id.startswith("workspace-"):
            event.stop()
            await self._handle_workspace_button(button_id)

    def _toggle_navigation_menu(self, button_id: str) -> None:
        menu = "manage" if button_id == "nav-manage" else "tools"
        if self._nav_menu_open and self._nav_menu == menu:
            self._close_nav_menu()
        else:
            self._open_nav_menu(menu)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        if event.list_view.id == "nav-list":
            event.stop()
            await self._show_task(cast(TaskKey, event.item.id))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.item.id is None:
            return
        if event.list_view.id == "nav-list":
            event.stop()

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id is None:
            return
        if event.value != event.select.value:
            event.stop()
            return
        if event.select.id.startswith("workspace-"):
            event.stop()
            if event.value in {Select.NULL, "__loading__"}:
                return
            select_task = _workspace_select_task(event.select.id)
            if select_task is not None and select_task != self.active_task:
                return
            await self._apply_workspace_select(event.select.id, str(event.value))
            return
        if not event.select.id.startswith("setting-control-"):
            return
        event.stop()
        if event.value in {Select.NULL, "__loading__"}:
            return
        key = event.select.id.removeprefix("setting-control-")
        self.settings_controller.apply_select(key, event.value)

    async def on_radio_set_changed(
        self,
        event: RadioSet.Changed,
    ) -> None:
        if not isinstance(event.radio_set, KeyedRadioSet) or not event.radio_set.routes_to_app:
            return
        choice_key = event.radio_set.key_for_button(event.pressed)
        if event.radio_set.id is None or choice_key is None:
            return
        event.stop()
        await self._apply_workspace_choice(event.radio_set.id, choice_key)

    async def on_workbench_steps_selected(self, event: WorkbenchSteps.Selected) -> None:
        event.stop()
        await self._select_workbench_step(event.key)

    async def on_unlock_editor_method_changed(
        self,
        event: UnlockEditor.MethodChanged,
    ) -> None:
        event.stop()
        if _owning_task(event.editor) != self.active_task:
            return
        self.workflow_ui_states[self.active_task].touch("unlock")
        if event.method_key == "passphrase":
            ui_state = self.workflow_ui_states[self.active_task]
            ui_state.touch("unlock.passphrase")
            state = self._unlock_state()
            if state is not None:
                state.recovery_documents = []
                state.recovery_payload_files = []
            self.refresh_task_view()
            self.call_after_refresh(event.editor.focus_passphrase)
            return
        await self._apply_workspace_choice(
            f"workspace-{self.active_task.replace('_', '-')}-unlock-method",
            event.method_key,
        )
        self.refresh_task_view()

    def on_unlock_editor_value_changed(self, event: UnlockEditor.ValueChanged) -> None:
        event.stop()
        event.editor.accept_value(event.value)
        task = _owning_task(event.editor)
        if task not in {"restore", "add_files", "rebuild", "replace_recovery_docs"}:
            return
        state = cast(UnlockTaskState, self._state_for_task(task))
        state.passphrase = event.value or None
        if event.value:
            state.recovery_documents = []
            state.recovery_payload_files = []
        ui_state = self.workflow_ui_states[task]
        ui_state.touch("unlock", "unlock.passphrase")
        self.refresh_task_view()

    def _commit_form_inputs(self) -> None:
        """Drain visible field drafts before a keyboard shortcut captures a review."""
        for editor in self.screen.query(DestinationEditor).results(DestinationEditor):
            if editor.region.width > 0 and _owning_task(editor) == self.active_task:
                change = editor.take_pending_change()
                if change is not None:
                    self.on_destination_editor_value_changed(change)
        for editor in self.screen.query(UnlockEditor).results(UnlockEditor):
            if editor.region.width > 0 and _owning_task(editor) == self.active_task:
                change = editor.take_pending_change()
                if change is not None:
                    self.on_unlock_editor_value_changed(change)

    def on_destination_editor_value_changed(self, event: DestinationEditor.ValueChanged) -> None:
        event.stop()
        path = Path(event.value).expanduser() if event.value else None
        task = _owning_task(event.editor)
        if task is None:
            return
        editor = workflow_definition(task).output_editor
        if not isinstance(editor, OutputEditorDefinition):
            return
        editor.set_path(self._state_for_task(task), path)
        step = step_for_section(task, "output")
        if step is not None:
            self.workflow_ui_states[task].touch(step)
        self.refresh_task_view()

    async def on_options_editor_choice_changed(
        self,
        event: OptionsEditor.ChoiceChanged,
    ) -> None:
        event.stop()
        if _owning_task(event.editor) != self.active_task:
            return
        if self.active_task == "replace_recovery_docs":
            ui_state = self.workflow_ui_states["replace_recovery_docs"]
            ui_state.touch("recovery")
            if event.choice_key == "recommended":
                ui_state.untouch("recovery.custom")
                ui_state.clear_draft("recovery")
                self.replace_recovery_docs_state.set_recovery_quorum(2, 3)
            elif event.choice_key == "custom":
                ui_state.touch("recovery.custom")
            self.refresh_task_view()
            return
        if self.active_task != "restore":
            return
        self.workflow_ui_states["restore"].touch("target")
        await self._apply_workspace_choice(
            "workspace-restore-target-method",
            event.choice_key,
        )

    async def on_options_editor_select_changed(
        self,
        event: OptionsEditor.SelectChanged,
    ) -> None:
        event.stop()
        if _owning_task(event.editor) != self.active_task:
            return
        if event.value is None:
            return
        ui_state = self.workflow_ui_states.get(self.active_task)
        if ui_state is not None and (section := _owning_workflow_section(event.editor)) is not None:
            ui_state.touch(section)
        await self._apply_workspace_select(event.select_key, event.value)

    def on_quorum_editor_changed(self, event: QuorumEditor.Changed) -> None:
        event.stop()
        if self.active_task != "replace_recovery_docs":
            return
        ui_state = self.workflow_ui_states["replace_recovery_docs"]
        ui_state.touch("recovery", "recovery.custom")
        if not event.valid or event.threshold is None or event.count is None:
            ui_state.set_invalid_draft(
                "recovery",
                {
                    "threshold": event.threshold_text,
                    "count": event.count_text,
                },
                message=event.error_message,
            )
            self.refresh_task_view()
            self.call_after_refresh(event.editor.ensure_feedback_visible)
            return
        self.replace_recovery_docs_state.set_recovery_quorum(
            event.threshold,
            event.count,
        )
        ui_state.clear_draft("recovery")
        event.editor.commit_draft()
        self.refresh_task_view()

    async def on_workspace_action_requested(
        self,
        event: WorkspaceActionRequested,
    ) -> None:
        event.stop()
        if _owning_task(event.control) != self.active_task:
            return
        if (
            self.active_task == "add_files"
            and event.action.key == "workspace-add-files-remove-selected"
            and isinstance(event.control, PathSelectionEditor)
        ):
            selected = set(event.control.selected_keys)
            self.add_files_state.input_paths = [
                path
                for index, path in enumerate(self.add_files_state.input_paths)
                if f"file-{index}" not in selected
            ]
            self.add_files_state.input_dirs = [
                path
                for index, path in enumerate(self.add_files_state.input_dirs)
                if f"folder-{index}" not in selected
            ]
            self.workflow_ui_states["add_files"].touch("files")
            self.refresh_task_view()
            return
        await self._handle_workspace_button(event.action.key)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id is None or not event.switch.id.startswith("setting-control-"):
            return
        event.stop()
        key = event.switch.id.removeprefix("setting-control-")
        self.settings_controller.apply_switch(key, event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply_setting_input(event, event.input, event.value)

    def on_input_blurred(self, event: Input.Blurred) -> None:
        self._apply_setting_input(event, event.input, event.value)

    def _apply_setting_input(
        self,
        event: Input.Submitted | Input.Blurred,
        input_widget: Input,
        value: str,
    ) -> None:
        if input_widget.id is None or not input_widget.id.startswith("setting-control-"):
            return
        event.stop()
        self.settings_controller.apply_text(
            input_widget.id.removeprefix("setting-control-"),
            _setting_input_value(input_widget, value),
        )


def _owning_task(editor: Widget) -> TaskKey | None:
    return next(
        (
            cast(TaskKey, ancestor.task_key)
            for ancestor in editor.ancestors
            if isinstance(ancestor, BaseWorkspace)
        ),
        None,
    )


def _owning_workflow_section(editor: Widget) -> str | None:
    return next(
        (ancestor.step_key for ancestor in editor.ancestors if isinstance(ancestor, WorkflowStep)),
        None,
    )


def _workspace_select_task(select_id: str) -> TaskKey | None:
    return next(
        (
            workflow.key
            for workflow in WORKFLOWS
            if workflow.workspace_prefix is not None
            and select_id.startswith(workflow.workspace_prefix)
        ),
        None,
    )


def _setting_input_value(input_widget: Input, value: str) -> str:
    return value.replace(" ", "") if isinstance(input_widget, MaskedInput) else value
