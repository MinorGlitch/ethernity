from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Collapsible, Input, Select, Static

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.workbench import WorkbenchSteps
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.settings import SettingsTaskState


def test_backup_essentials_fit_80_by_24_with_many_selected_files(tmp_path: Path) -> None:
    paths = [tmp_path / f"note-{index}.txt" for index in range(20)]
    for path in paths:
        path.write_text("paper backup\n")

    async def run() -> None:
        app = EthernityApp(backup_state=BackupTaskState(input_paths=paths))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for _ in range(40):
                if app.backup_state.current_estimate() is not None:
                    break
                await pilot.pause(0.05)
            assert app.backup_state.current_estimate() is not None
            assert "20 files" in str(app.query_one("#backup-files-value", Static).content)
            assert not app.query_one("#backup-files-panel", Collapsible).collapsed
            rail = app.query_one(WorkbenchSteps)
            for step, selectors in (
                ("files", ("#workspace-backup-files", "#backup-files-list")),
                ("recovery", ("#workspace-backup-recovery-method",)),
                (
                    "print",
                    (
                        "#workspace-backup-paper-size",
                        "#workspace-backup-design",
                        "#backup-output-value",
                        "#backup-output-summary",
                    ),
                ),
            ):
                await pilot.click(rail.button_for(step))
                await pilot.pause()
                workspace = app.query_one("#backup-workspace .task-workspace").region
                for selector in selectors:
                    control = app.query_one(selector)
                    control.scroll_visible(animate=False, immediate=True)
                    await pilot.pause()
                    assert control.region.height > 0
                    assert workspace.contains_region(control.region)
            assert "Store recovery sheets separately from backup pages." in str(
                app.query_one("#backup-recovery-help", Static).content
            )
            assert "About" in str(app.query_one("#backup-output-summary", Static).content)

    asyncio.run(run())


def test_custom_backup_quorum_changes_from_the_visible_button() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                recovery_method="custom_shards",
                shard_threshold=3,
                shard_count=5,
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.1)
            assert not list(app.screen.query("#edit-field-modal"))
            await pilot.click(app.query_one(WorkbenchSteps).button_for("recovery"))
            await pilot.click("#workspace-backup-recovery-quorum")
            await pilot.pause()
            field = app.screen.query_one("#edit-field-input", Input)
            assert field.value == "3/5"
            field.value = "2/3"
            await pilot.press("enter")
            await pilot.pause()

            assert not list(app.screen.query("#edit-field-modal"))
            assert app.backup_state.recovery_method == "custom_shards"
            assert (app.backup_state.shard_threshold, app.backup_state.shard_count) == (2, 3)
            assert "2 required" in str(app.query_one("#backup-quorum-value", Static).content)

    asyncio.run(run())


def test_backup_print_overrides_survive_navigation_without_changing_settings() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            original_paper = app.settings_state.paper_size
            original_design = app.settings_state.design
            app.query_one("#workspace-backup-paper-size", Select).value = "LETTER"
            await pilot.pause()
            app.query_one("#workspace-backup-design", Select).value = "maritime"
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()

            assert app.backup_state.paper_size == "LETTER"
            assert app.backup_state.design == "maritime"
            assert app.query_one("#workspace-backup-paper-size", Select).value == "LETTER"
            assert app.query_one("#workspace-backup-design", Select).value == "maritime"
            assert app.settings_state.paper_size == original_paper
            assert app.settings_state.design == original_design

    asyncio.run(run())


@pytest.mark.parametrize(
    "control,value,attribute,expected",
    (
        ("passphrase-words", "18", "passphrase_words", 18),
        ("paper-size", "LETTER", "paper_size", "LETTER"),
        ("design", "maritime", "design", "maritime"),
    ),
)
def test_background_refresh_preserves_pending_select_edits(control, value, attribute, expected):
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(120, 36)) as pilot:
            select = app.query_one(f"#workspace-backup-{control}", Select)
            select.value = value
            # An estimate can finish before the queued Select.Changed is handled.
            app.refresh_task_view()
            await pilot.pause()
            assert getattr(app.backup_state, attribute) == expected
            assert select.value == value

    asyncio.run(run())


@pytest.mark.parametrize(
    "backup_state",
    (
        BackupTaskState(),
        BackupTaskState(
            paper_size="LETTER",
            design="forge",
            recovery_method="custom_shards",
            shard_threshold=3,
            shard_count=5,
            passphrase_words=18,
            qr_chunk_size=1024,
            signing_key_mode="sharded",
            signing_key_shard_threshold=2,
            signing_key_shard_count=3,
        ),
        BackupTaskState(
            paper_size="LETTER",
            design="maritime",
            recovery_method="single_phrase",
            passphrase="manually chosen recovery phrase",
            signing_key_mode="embedded",
        ),
    ),
    ids=("inherited-defaults", "custom-quorums", "single-phrase"),
)
def test_backup_mount_preserves_effective_values_and_explicit_fields(
    tmp_path: Path, backup_state: BackupTaskState
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    file = source / "records.txt"
    file.write_text("family records", encoding="utf-8")
    folder = source / "notes"
    folder.mkdir()
    (folder / "contacts.txt").write_text("family contacts", encoding="utf-8")
    backup_state = backup_state.model_copy(deep=True)
    backup_state.input_paths = [file]
    backup_state.input_dirs = [folder]
    backup_state.base_dir = source
    backup_state.output_dir = tmp_path / "paper-documents"
    backup_state.config_path = config

    async def run() -> None:
        app = EthernityApp(
            backup_state=backup_state,
            settings_state=SettingsTaskState.from_current(config),
        )
        before = app.backup_state.model_dump()
        explicit_fields = set(app.backup_state.model_fields_set)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            assert app.backup_state.model_dump() == before
            assert app.backup_state.model_fields_set == explicit_fields
            assert (
                app.query_one("#workspace-backup-paper-size", Select).value == before["paper_size"]
            )
            assert app.query_one("#workspace-backup-design", Select).value == before["design"]

    asyncio.run(run())
