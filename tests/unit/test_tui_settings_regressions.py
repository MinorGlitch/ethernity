from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from textual.containers import Vertical
from textual.widgets import Button, Input, Select, Static, TabbedContent, TabPane

from ethernity.app.app_state import apply_settings_defaults, build_initial_task_states
from ethernity.app.application import EthernityApp
from ethernity.app.settings_controller import SettingsController, SettingsControllerApp
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.settings import SettingsTaskState


def _config_settings(tmp_path: Path) -> SettingsTaskState:
    config_path = tmp_path / "config.toml"
    config_path.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    settings = SettingsTaskState.from_current(config_path)
    settings.set_setting_value("render_style", "forge")
    settings.set_setting_value("page_size", "LETTER")
    settings.set_setting_value("backup_base_dir", str(tmp_path / "source"))
    settings.set_setting_value("backup_output_dir", str(tmp_path / "backup-out"))
    settings.set_setting_value("backup_shard_threshold", 3)
    settings.set_setting_value("backup_shard_count", 5)
    settings.set_setting_value("backup_signing_key_mode", "sharded")
    settings.set_setting_value("backup_signing_key_shard_threshold", 2)
    settings.set_setting_value("backup_signing_key_shard_count", 3)
    settings.set_setting_value("recover_output", str(tmp_path / "recovered"))
    settings.set_setting_value("extend_base_dir", str(tmp_path / "updates"))
    settings.set_setting_value("extend_unlock_policy", "reuse-root")
    settings.set_setting_value("qr_chunk_size", 1024)
    assert settings.execute().ok
    return SettingsTaskState.from_current(config_path)


def test_saved_settings_hydrate_all_workflow_effective_defaults(tmp_path: Path) -> None:
    input_path = tmp_path / "secret.txt"
    input_path.write_text("secret", encoding="utf-8")
    settings = _config_settings(tmp_path)

    app = EthernityApp(
        backup_state=BackupTaskState(input_paths=[input_path]),
        settings_state=settings,
    )

    backup = app.backup_state
    backup_args = backup.to_backup_args()
    assert backup.validate_task().ready
    assert backup.design == backup_args.design == "forge"
    assert backup.paper_size == backup_args.paper == "LETTER"
    assert backup.output_dir == Path(backup_args.output_dir or "") == tmp_path / "backup-out"
    assert (backup.shard_threshold, backup.shard_count) == (3, 5)
    assert (backup_args.shard_threshold, backup_args.shard_count) == (3, 5)
    assert backup.recovery_method == "custom_shards"
    assert "5 recovery sheets; any 3 required" in backup.sections()[1].summary
    assert any(item.label == "5 recovery sheets" for item in backup.preview().items)
    assert backup.signing_key_mode == backup_args.signing_key_mode == "sharded"
    assert backup.qr_chunk_size is backup_args.qr_chunk_size is None

    assert app.restore_state.output_path == tmp_path / "recovered"
    assert app.restore_state.to_recover_args().output == str(tmp_path / "recovered")
    assert app.add_files_state.base_dir == tmp_path / "updates"
    assert app.add_files_state.unlock_policy == "reuse-root"
    assert app.add_files_state.to_extend_args().unlock_policy == "reuse-root"

    for state in (
        app.backup_state,
        app.restore_state,
        app.add_files_state,
        app.rebuild_state,
        app.replace_recovery_docs_state,
        app.kit_state,
    ):
        assert state.config_path == settings.config_path

    for state in (
        app.backup_state,
        app.add_files_state,
        app.rebuild_state,
        app.replace_recovery_docs_state,
        app.kit_state,
    ):
        assert state.design == "forge"
        assert state.paper_size == "LETTER"


def test_settings_changes_only_rehydrate_inherited_workflow_fields(tmp_path: Path) -> None:
    settings = _config_settings(tmp_path)
    states = build_initial_task_states(
        backup_state=BackupTaskState(design="sentinel"),
        restore_state=None,
        add_files_state=None,
        rebuild_state=None,
        replace_recovery_docs_state=None,
        kit_state=None,
        settings_state=settings,
    )
    states.restore.output_path = tmp_path / "manual-restore"

    settings.set_setting_value("render_style", "sentinel")
    settings.set_setting_value("page_size", "A4")
    settings.set_setting_value("backup_output_dir", str(tmp_path / "new-backup-out"))
    settings.set_setting_value("backup_shard_threshold", None)
    settings.set_setting_value("backup_shard_count", None)
    settings.set_setting_value("backup_signing_key_mode", "embedded")
    settings.set_setting_value("backup_signing_key_shard_threshold", None)
    settings.set_setting_value("backup_signing_key_shard_count", None)
    settings.set_setting_value("recover_output", str(tmp_path / "new-recovered"))
    assert settings.execute().ok

    apply_settings_defaults(states)

    assert states.backup.design == "sentinel"
    assert states.backup.paper_size == "A4"
    assert states.backup.output_dir == tmp_path / "new-backup-out"
    assert states.backup.recovery_method == "recommended_shards"
    assert (states.backup.shard_threshold, states.backup.shard_count) == (2, 3)
    assert states.restore.output_path == tmp_path / "manual-restore"


def test_successful_settings_save_rehydrates_only_inherited_app_fields(tmp_path: Path) -> None:
    async def run() -> None:
        settings = _config_settings(tmp_path)
        app = EthernityApp(settings_state=settings)
        app.backup_state.paper_size = "LETTER"

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("7")
            app.query_one("#setting-control-page_size", Select).value = "A4"
            await pilot.pause()

            assert app.backup_state.paper_size == "LETTER"
            assert app.kit_state.paper_size == "A4"
            assert SettingsTaskState.from_current(settings.config_path).paper_size == "A4"

    asyncio.run(run())


def test_cleared_workflow_starts_again_from_saved_settings(tmp_path: Path) -> None:
    async def run() -> None:
        settings = _config_settings(tmp_path)
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[tmp_path / "secret.txt"],
                output_dir=tmp_path / "manual-output",
                design="sentinel",
            ),
            settings_state=settings,
        )
        async with app.run_test(size=(120, 32)) as pilot:
            app.action_clear_task()
            await pilot.pause()

            assert not app.backup_state.input_paths
            assert app.backup_state.output_dir == tmp_path / "backup-out"
            assert app.backup_state.design == "forge"
            assert app.backup_state.paper_size == "LETTER"

    asyncio.run(run())


def test_settings_numeric_input_saves_when_focus_leaves_and_reverts_invalid_draft(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        settings = _config_settings(tmp_path)
        app = EthernityApp(settings_state=settings)
        async with app.run_test(size=(120, 72)) as pilot:
            await pilot.press("7")
            tabs = app.query_one("#settings-tabs", TabbedContent)
            tabs.active = "settings-pane-advanced"
            await pilot.pause()

            field = app.query_one("#setting-control-qr_chunk_size", Input)
            field.focus()
            await pilot.pause()
            field.value = "2048"
            app.query_one("#settings-reset-all", Button).focus()
            await pilot.pause()

            assert app.settings_state.setting_value("qr_chunk_size") == 2048
            assert app.settings_state.save_status == "Saved"
            assert (
                SettingsTaskState.from_current(settings.config_path).setting_value("qr_chunk_size")
                == 2048
            )

            field.focus()
            await pilot.pause()
            field.value = "0"
            app.query_one("#settings-reset-all", Button).focus()
            await pilot.pause()

            assert app.settings_state.setting_value("qr_chunk_size") == 2048
            assert field.value == "2048"
            assert app.settings_state.save_status == "Not saved"
            assert (
                SettingsTaskState.from_current(settings.config_path).setting_value("qr_chunk_size")
                == 2048
            )

            chunk_min = app.query_one("#setting-control-extension_chunk_min", Input)
            chunk_min.focus()
            await pilot.pause()
            chunk_min.value = "32768"
            app.query_one("#settings-reset-all", Button).focus()
            await pilot.pause()

            assert app.settings_state.setting_value("extension_chunk_min") == 32768
            assert app.settings_state.save_status == "Not saved"
            assert "minimum <= target <= maximum" in str(
                app.query_one("#setting-help-extension_chunk_target", Static).content
            )
            assert (
                SettingsTaskState.from_current(settings.config_path).setting_value(
                    "extension_chunk_min"
                )
                == 4096
            )

    asyncio.run(run())


def test_settings_tabs_and_save_status_stay_fixed_while_active_pane_scrolls() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("7")
            tabs = app.query_one("#settings-tabs", TabbedContent)
            tabs.active = "settings-pane-advanced"
            await pilot.pause()

            form = app.query_one("#settings-form", Vertical)
            tab_bar = app.query_one("#settings-tabs Tabs")
            pane = app.query_one("#settings-pane-advanced", TabPane)
            save_row = app.query_one("#settings-save-row")
            save_status = app.query_one("#settings-save-status", Static)
            fixed_regions = (tab_bar.region, save_row.region)

            assert pane.max_scroll_y > 0
            assert tab_bar.region.y == form.region.y
            assert tab_bar.region.bottom <= pane.region.y
            assert pane.region.bottom <= save_row.region.y
            assert str(save_status.content) == "Saved"
            assert save_status.region.x > form.region.x + form.region.width // 2

            pane.scroll_end(animate=False)
            await pilot.pause()

            assert pane.scroll_offset.y == pane.max_scroll_y
            assert (tab_bar.region, save_row.region) == fixed_regions
            assert app.query_one("#setting-row-qr_error").region.y < pane.region.y

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["result", "exception"])
def test_settings_reset_never_reports_success_when_persistence_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    settings = _config_settings(tmp_path)
    notices: list[tuple[str, str]] = []
    app = SimpleNamespace(
        settings_state=settings,
        _last_execution_result=None,
        notify=lambda message, **kwargs: notices.append((message, kwargs.get("severity", ""))),
        refresh_task_view=Mock(),
        _rehydrate_workflow_defaults=Mock(),
    )
    if failure == "result":
        monkeypatch.setattr(
            SettingsTaskState,
            "execute",
            lambda _self: TaskExecutionResult(ok=False, message="disk rejected write"),
        )
    else:

        def raise_write_error(_self: SettingsTaskState) -> TaskExecutionResult:
            raise OSError("disk is read-only")

        monkeypatch.setattr(SettingsTaskState, "execute", raise_write_error)

    controller = SettingsController(cast(SettingsControllerApp, cast(Any, app)))
    controller.reset_group("Printing")

    assert settings.save_status == "Save failed"
    assert not app._rehydrate_workflow_defaults.called
    assert not any("defaults restored" in message.lower() for message, _severity in notices)
    assert notices[-1][1] == "error"


def test_failed_settings_save_retries_when_text_is_resubmitted_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _config_settings(tmp_path)
    notices: list[tuple[str, str]] = []
    app = SimpleNamespace(
        settings_state=settings,
        _last_execution_result=None,
        _running_task=None,
        notify=lambda message, **kwargs: notices.append((message, kwargs.get("severity", ""))),
        refresh_task_view=Mock(),
        _rehydrate_workflow_defaults=Mock(),
    )
    outcomes = iter(
        (
            TaskExecutionResult(ok=False, message="disk rejected write"),
            TaskExecutionResult(ok=True, message="Settings saved."),
        )
    )
    calls: list[None] = []

    def execute(_self: SettingsTaskState) -> TaskExecutionResult:
        calls.append(None)
        return next(outcomes)

    monkeypatch.setattr(SettingsTaskState, "execute", execute)
    controller = SettingsController(cast(SettingsControllerApp, cast(Any, app)))

    assert not controller.apply_text("qr_chunk_size", "2048")
    assert settings.save_status == "Save failed"
    assert settings.save_pending

    assert controller.apply_text("qr_chunk_size", "2048")
    assert len(calls) == 2
    assert settings.save_status == "Saved"
    assert not settings.save_pending
    assert app._rehydrate_workflow_defaults.called
