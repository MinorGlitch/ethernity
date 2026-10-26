from __future__ import annotations

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_state import fresh_task_state
from ethernity.app.widgets.passphrase_input import PassphraseInput
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.app.workflow_registry import workflow_definition


class TaskStateMutationActions(EthernityAppContext):
    async def action_back(self) -> None:
        if self._nav_menu_open:
            self._close_nav_menu()
        else:
            self.query_one(TaskCanvas).action_back()

    def action_clear_task(self) -> None:
        workflow = workflow_definition(self.active_task)
        if workflow.workspace_id is not None:
            for field in self.query_one(f"#{workflow.workspace_id}").query(PassphraseInput):
                field.discard_edit()
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
        self._last_reviewed_task = None
        if self.active_task == "backup":
            self.query_one(TaskCanvas).select_step("files")
            self._initial_task_payloads["backup"] = self.backup_state.model_dump_json()
        self.refresh_task_view()
