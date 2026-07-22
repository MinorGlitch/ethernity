from __future__ import annotations

from typing import cast

from textual import events
from textual.containers import Vertical
from textual.widgets import Button, Input, ListView, MaskedInput, RadioSet, Select, Switch

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import ActiveTask
from ethernity.app.help_content import build_help_content
from ethernity.app.screens.help import HelpScreen
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.app.workspaces.common import WorkspaceRadioSet


class AppEventHandlers(EthernityAppContext):
    """Textual lifecycle and event routing for the app shell."""

    def on_mount(self) -> None:
        self.query_one("#nav", Vertical).border_title = "Ethernity"
        self.query_one("#nav-list", ListView).focus()
        self.refresh_task_view()

    def on_resize(self, event: events.Resize) -> None:
        event.stop()
        self._sync_nav_layout()

    async def action_help(self) -> None:
        await self.push_screen(HelpScreen(build_help_content(task=self.active_task)))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "nav-strip":
            event.stop()
            if self._nav_drawer_open:
                self._close_nav_drawer()
            else:
                self._open_nav_drawer()
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

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        if event.list_view.id == "nav-list":
            event.stop()
            self._show_task(cast(ActiveTask, event.item.id))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.item.id is None:
            return
        if event.list_view.id == "nav-list":
            if self._nav_should_collapse():
                event.stop()
                return
            event.stop()

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id is None:
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
        if not isinstance(event.radio_set, WorkspaceRadioSet):
            return
        choice_key = event.radio_set.key_for_button(event.pressed)
        if event.radio_set.id is None or choice_key is None:
            return
        event.stop()
        await self._apply_workspace_choice(event.radio_set.id, choice_key)

    def on_workflow_step_stack_step_requested(
        self,
        event: WorkflowStepStack.StepRequested,
    ) -> None:
        event.stop()
        ui_state = self.workflow_ui_states.get(self.active_task)
        if ui_state is None:
            return
        ui_state.activate(event.step_key)
        self.refresh_task_view()
        self.call_after_refresh(event.stack.focus_active)

    async def on_source_chooser_method_changed(
        self,
        event: SourceChooser.MethodChanged,
    ) -> None:
        event.stop()
        method_actions = {
            "restore": {
                "scanned_pages": "workspace-restore-source",
                "recovery_text": "workspace-restore-recovery-text",
                "payload_files": "workspace-restore-payloads",
            },
            "add_files": {
                "backup_folder": "workspace-add-files-backup",
                "scanned_pages": "workspace-add-files-source",
            },
            "rebuild": {
                "backup_folder": "workspace-rebuild-backup",
                "scanned_pages": "workspace-rebuild-scans",
            },
            "replace_recovery_docs": {
                "scanned_pages": "workspace-replace-source",
                "recovery_text": "workspace-replace-recovery-text",
                "payload_files": "workspace-replace-payloads",
            },
        }
        button_id = method_actions.get(self.active_task, {}).get(event.method_key)
        if button_id is None:
            return
        self.workflow_ui_states[self.active_task].touch("source")
        await self._handle_workspace_button(button_id)
        self.refresh_task_view()

    async def on_source_chooser_action_requested(
        self,
        event: SourceChooser.ActionRequested,
    ) -> None:
        event.stop()
        await self._handle_workspace_button(event.action.key)

    async def on_unlock_editor_method_changed(
        self,
        event: UnlockEditor.MethodChanged,
    ) -> None:
        event.stop()
        self.workflow_ui_states[self.active_task].touch("unlock")
        await self._apply_workspace_choice(
            f"workspace-{self.active_task.replace('_', '-')}-unlock-method",
            event.method_key,
        )
        self.refresh_task_view()

    async def on_unlock_editor_action_requested(
        self,
        event: UnlockEditor.ActionRequested,
    ) -> None:
        event.stop()
        await self._handle_workspace_button(event.action.key)

    async def on_options_editor_choice_changed(
        self,
        event: OptionsEditor.ChoiceChanged,
    ) -> None:
        event.stop()
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

    async def on_options_editor_action_requested(
        self,
        event: OptionsEditor.ActionRequested,
    ) -> None:
        event.stop()
        await self._handle_workspace_button(event.action.key)

    async def on_options_editor_select_changed(
        self,
        event: OptionsEditor.SelectChanged,
    ) -> None:
        event.stop()
        if event.value is None:
            return
        ui_state = self.workflow_ui_states.get(self.active_task)
        if ui_state is not None:
            ui_state.touch(ui_state.active_step)
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

    async def on_destination_editor_action_requested(
        self,
        event: DestinationEditor.ActionRequested,
    ) -> None:
        event.stop()
        await self._handle_workspace_button(event.action.key)

    async def on_path_selection_editor_action_requested(
        self,
        event: PathSelectionEditor.ActionRequested,
    ) -> None:
        event.stop()
        if (
            self.active_task == "add_files"
            and event.action.key == "workspace-add-files-remove-selected"
        ):
            selected = set(event.editor.selected_keys)
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
        if event.input.id is None or not event.input.id.startswith("setting-control-"):
            return
        event.stop()
        self.settings_controller.apply_text(
            event.input.id.removeprefix("setting-control-"),
            _setting_input_value(event.input, event.value),
        )

    def on_input_blurred(self, event: Input.Blurred) -> None:
        if event.input.id is None or not event.input.id.startswith("setting-control-"):
            return
        event.stop()
        self.settings_controller.apply_text(
            event.input.id.removeprefix("setting-control-"),
            _setting_input_value(event.input, event.value),
        )


def _workspace_select_task(select_id: str) -> ActiveTask | None:
    if select_id.startswith("workspace-add-files-"):
        return "add_files"
    if select_id.startswith("workspace-replace-"):
        return "replace_recovery_docs"
    if select_id.startswith("workspace-backup-"):
        return "backup"
    if select_id.startswith("workspace-restore-"):
        return "restore"
    if select_id.startswith("workspace-rebuild-"):
        return "rebuild"
    if select_id.startswith("workspace-kit-"):
        return "kit"
    return None


def _setting_input_value(input_widget: Input, value: str) -> str:
    return value.replace(" ", "") if isinstance(input_widget, MaskedInput) else value
