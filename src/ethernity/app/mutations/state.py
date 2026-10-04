from __future__ import annotations

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_state import fresh_task_state
from ethernity.app.workflow_registry import workflow_definition


class TaskStateMutationActions(EthernityAppContext):
    def action_close_navigation(self) -> None:
        if self._nav_menu_open:
            self._close_nav_menu()

    def action_clear_task(self) -> None:
        workflow = workflow_definition(self.active_task)
        state = fresh_task_state(
            self.active_task,
            settings_config_path=(
                self.settings_state.config_path if self.active_task == "settings" else None
            ),
        )
        setattr(self, workflow.state_attribute, state)
        if self.active_task != "settings":
            self._rehydrate_workflow_defaults()
        self._last_execution_result = None
        self.refresh_task_view()
