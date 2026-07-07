from __future__ import annotations

from typing import cast

from textual.containers import Vertical
from textual.widgets import Button, Input, OptionList, RadioSet, Select, Switch

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import ActiveTask
from ethernity.app.help_content import build_help_content
from ethernity.app.screens.help import HelpScreen
from ethernity.app.task_catalog import TASK_ORDER


class AppEventHandlers(EthernityAppContext):
    """Textual lifecycle and event routing for the app shell."""

    def on_mount(self) -> None:
        self.query_one("#nav", Vertical).border_title = "Ethernity"
        self.query_one("#nav-list", OptionList).focus()
        self.refresh_task_view()

    async def action_help(self) -> None:
        await self.push_screen(HelpScreen(build_help_content(task=self.active_task)))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "canvas-primary":
            event.stop()
            await self.action_review()
        elif button_id is not None and button_id.startswith("setting-control-"):
            event.stop()
            await self.settings_controller.edit(button_id.removeprefix("setting-control-"))
        elif button_id is not None and button_id.startswith("workspace-"):
            event.stop()
            await self._handle_workspace_button(button_id)
        elif button_id == "preview-diagnostics":
            event.stop()
            await self.action_diagnostics()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        if event.option_list.id == "nav-list":
            event.stop()
            self._show_task(cast(ActiveTask, event.option.id))
        elif event.option_list.id == "preview-issues":
            event.stop()
            issue_index = str(event.option.id).removeprefix("issue-")
            if issue_index.isdecimal():
                self._focus_issue_by_index(int(issue_index))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id is None:
            return
        if event.option_list.id == "nav-list":
            task = cast(ActiveTask, event.option.id)
            if task not in TASK_ORDER or task == self.active_task:
                return
            event.stop()
            self._show_task(task)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id is None:
            return
        if event.select.id.startswith("workspace-"):
            event.stop()
            if event.value in {Select.NULL, "__loading__"}:
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

    async def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id is None or not event.radio_set.id.startswith("workspace-"):
            return
        event.stop()
        if event.pressed.id is None:
            return
        await self._apply_workspace_radio(event.radio_set.id, event.pressed.id)

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
            event.value,
        )
