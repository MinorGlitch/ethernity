# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.widgets import Static

from ethernity.app.application import EthernityApp
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.restore import RestoreTaskState
from tests.support.app import run_app_test
from tests.support.pilot import click_when_ready, wait_for_condition, wait_for_widget
from tests.test_support import temp_env


async def _run_final_review(app: EthernityApp, pilot: Any) -> None:
    await pilot.press("ctrl+r")
    await click_when_ready(pilot, "#review-execute")
    await wait_for_condition(
        pilot,
        lambda: app._last_execution_result is not None,
        "backup or restore to finish",
        timeout=60,
    )
    result = app._last_execution_result
    assert result is not None
    if not result.ok:
        screen = app.screen
        error = getattr(screen, "_error", None)
        detail = getattr(screen, "_error_detail", None)
        raise AssertionError(f"task failed: {error}; {detail}")


def test_textual_app_backup_and_restore_round_trip(tmp_path: Path) -> None:
    async def run() -> None:
        payload = "textual app round trip\n"
        passphrase = "correct horse battery staple"
        input_path = tmp_path / "secret.txt"
        backup_dir = tmp_path / "backup"
        restored_path = tmp_path / "restored.txt"
        input_path.write_text(payload, encoding="utf-8")

        with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
            backup_app = EthernityApp(
                backup_state=BackupTaskState(
                    input_paths=[input_path],
                    output_dir=backup_dir,
                    passphrase=passphrase,
                )
            )
            async with run_app_test(backup_app, size=(140, 40)) as pilot:
                await _run_final_review(backup_app, pilot)
                check_button = await wait_for_widget(pilot, "#result-test-recovery")
                check_button.focus()
                await pilot.wait_for_scheduled_animations()
                await click_when_ready(pilot, "#result-test-recovery")
                checks = backup_app.screen.query_one("#result-document-checks", Static)
                await wait_for_condition(
                    pilot,
                    lambda: not backup_app.recovery_check_controller.running and checks.display,
                    "generated document recovery to finish",
                    timeout=60,
                )
                assert "Generated PDF recovery passed: 1 file recovered" in str(checks.content)
                assert "using 2 recovery sheets" in str(checks.content)

            [backup_dir] = backup_dir.glob("backup-*")
            restore_app = EthernityApp(
                restore_state=RestoreTaskState(
                    source_paths=[backup_dir],
                    output_path=restored_path,
                    passphrase=passphrase,
                )
            )
            async with run_app_test(restore_app, size=(140, 40)) as pilot:
                await pilot.press("2")
                await _run_final_review(restore_app, pilot)

        assert (backup_dir / "qr_document.pdf").read_bytes().startswith(b"%PDF")
        assert (backup_dir / "recovery_document.pdf").read_bytes().startswith(b"%PDF")
        assert any(backup_dir.glob("shard-*-1-of-3.pdf"))
        assert restored_path.read_text(encoding="utf-8") == payload

    asyncio.run(run())
