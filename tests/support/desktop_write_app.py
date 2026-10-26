"""Real desktop-protocol session with a controllable file commit for shutdown tests."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ethernity.app.application import EthernityApp
from ethernity.app.execution import ReviewedTask
from ethernity.core.execution_control import begin_final_write
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.workflows.shared.events import emit_phase

DIRECTORY = Path(sys.argv[1])


class ControlledBackup(BackupTaskState):
    def execute(self) -> TaskExecutionResult:
        begin_final_write()
        emit_phase(phase="save", label="Saving")
        (DIRECTORY / "started").touch()
        deadline = time.monotonic() + 30
        while not (DIRECTORY / "release").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("Test did not release the file commit")
            time.sleep(0.02)
        (DIRECTORY / "saved.txt").write_text("complete", encoding="utf-8")
        return TaskExecutionResult(status="succeeded", message="Backup complete.")


class WriteApp(EthernityApp):
    def on_mount(self) -> None:
        self.call_after_refresh(self.start_backup)

    def start_backup(self) -> None:
        self.execution_controller.start(ReviewedTask.capture("backup", self.backup_state))


WriteApp(
    backup_state=ControlledBackup(input_paths=[DIRECTORY / "input.txt"], output_dir=DIRECTORY)
).run()
