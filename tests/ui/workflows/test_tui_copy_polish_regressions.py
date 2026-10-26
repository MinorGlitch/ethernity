from __future__ import annotations

import asyncio

from ethernity.app.application import EthernityApp
from ethernity.app.bindings import APP_BINDINGS
from ethernity.tasks.backup import BackupTaskState
from tests.support.app import run_app_test


def test_global_navigation_and_help_shortcuts_remain_available() -> None:
    bindings = {(binding.key, binding.action) for binding in APP_BINDINGS}

    assert {
        ("q", "quit"),
        ("?", "help"),
        ("escape", "back"),
        ("ctrl+b", "open_navigation"),
        ("ctrl+p", "command_palette"),
    } <= bindings


def test_backup_review_opens_recovery_for_invalid_signing_mode(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[tmp_path / "records.txt"],
                signing_key_shard_threshold=2,
            )
        )
        async with run_app_test(app, size=(120, 32)) as pilot:
            # Mount applies Settings defaults; introduce the incomplete draft as a user edit.
            app.backup_state.signing_key_shard_threshold = 2
            app.refresh_task_view()
            await pilot.pause()

            assert not app.query_one("#backup-signing-section").display

            await app.action_review()
            await pilot.pause()

            assert app.query_one("#backup-signing-section").display
            assert app.screen.focused is not None
            assert app.screen.focused.id == "workspace-backup-signing-key-mode"

    asyncio.run(run())
