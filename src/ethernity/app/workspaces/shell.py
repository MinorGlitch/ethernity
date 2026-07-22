from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import ContentSwitcher

from ethernity.app.workflow_registry import workflow_definition
from ethernity.app.workspaces.add_files import AddFilesWorkspace
from ethernity.app.workspaces.backup import BackupWorkspace
from ethernity.app.workspaces.common import BaseWorkspace
from ethernity.app.workspaces.kit import KitWorkspace
from ethernity.app.workspaces.rebuild import RebuildWorkspace
from ethernity.app.workspaces.replace_recovery import ReplaceRecoveryWorkspace
from ethernity.app.workspaces.restore import RestoreWorkspace
from ethernity.tasks.presentation.models import TaskPresentation


class TaskWorkspaces(Widget):
    """Task-specific center workspaces."""

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="backup-workspace", id="task-workspace-switcher"):
            yield BackupWorkspace(id="backup-workspace")
            yield RestoreWorkspace(id="restore-workspace")
            yield AddFilesWorkspace(id="add_files-workspace")
            yield RebuildWorkspace(id="rebuild-workspace")
            yield ReplaceRecoveryWorkspace(id="replace_recovery_docs-workspace")
            yield KitWorkspace(id="kit-workspace")

    def update_presentation(self, presentation: TaskPresentation) -> None:
        if presentation.task_key == "settings":
            return
        definition = workflow_definition(presentation.task_key)
        if definition.workspace_id is None:
            return
        switcher = self.query_one("#task-workspace-switcher", ContentSwitcher)
        switcher.current = definition.workspace_id
        workspace = self.query_one(f"#{definition.workspace_id}", BaseWorkspace)
        workspace.update_presentation(presentation)
