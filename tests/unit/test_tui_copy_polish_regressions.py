from __future__ import annotations

import asyncio

from textual.widgets import Collapsible

from ethernity.app.application import EthernityApp
from ethernity.app.bindings import APP_BINDINGS
from ethernity.tasks.backup import BackupTaskState


def test_footer_only_advertises_universal_commands() -> None:
    visible_bindings = {
        (binding.key, binding.description)
        for binding in APP_BINDINGS
        if getattr(binding, "show", False)
    }

    assert visible_bindings == {("q", "Quit"), ("?", "Help")}


def test_backup_primary_action_reveals_and_focuses_invalid_advanced_control(tmp_path) -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[tmp_path / "records.txt"],
                signing_key_shard_threshold=2,
            )
        )
        async with app.run_test(size=(120, 32)) as pilot:
            # Mount applies Settings defaults; introduce the incomplete draft as a user edit.
            app.backup_state.signing_key_shard_threshold = 2
            app.refresh_task_view()
            await pilot.pause()

            panel = app.query_one("#backup-advanced-panel", Collapsible)
            assert panel.collapsed

            await app.action_primary()
            await pilot.pause()

            assert not panel.collapsed
            assert app.screen.focused is not None
            assert app.screen.focused.id == "workspace-backup-signing-key-shards"

    asyncio.run(run())
