from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    Input,
    MaskedInput,
    Select,
    Static,
)

from ethernity.app.application import EthernityApp
from ethernity.app.screens.confirm_action import ConfirmActionScreen
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.settings import SettingsTaskState
from tests.support import workflows as workflow_support
from tests.support.app import run_app_test
from tests.support.pilot import (
    wait_for_condition as _wait_for_condition,
)

pytestmark = pytest.mark.usefixtures("isolated_app_settings")


def test_textual_app_switches_to_kit_and_settings() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")

            assert app.active_task == "kit"
            assert "Create offline recovery kit" in workflow_support.static_text(
                app, "#canvas-title"
            )
            assert "Built-in kit" not in workflow_support.checklist_text(app)
            assert "recovery_kit_qr.pdf" in workflow_support.checklist_text(app)
            assert "Kit type" in workflow_support.checklist_text(app)
            assert "Save as" in workflow_support.checklist_text(app)
            assert app.query_one("#workspace-kit-chunk-size", Button).display
            assert app.query_one("#workspace-kit-variant-select", Select).value == "lean"

            await pilot.press("7")

            assert app.active_task == "settings"
            assert workflow_support.static_text(app, "#canvas-title") == ""
            assert app.query_one("#setting-control-render_style", Select).value == (
                app.settings_state.design
            )

    asyncio.run(run())


def test_textual_app_edit_kit_output() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")
            await app.action_edit_output()
            await workflow_support.save_picker_name(app, pilot, "kit.pdf")

            assert app.kit_state.output_path.name == "kit.pdf"
            assert "kit.pdf" in workflow_support.checklist_text(app)

    asyncio.run(run())


def test_textual_app_edit_kit_qr_chunk_size() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with run_app_test(app, size=(120, 40)) as pilot:
            await pilot.press("6")
            app.query_one("#workspace-kit-chunk-size", Button).focus()
            await pilot.press("enter")
            await workflow_support.type_text(pilot, "512")
            await pilot.press("enter")

            assert app.kit_state.chunk_size == 512
            assert "512 bytes" in workflow_support.checklist_text(app)
            assert "512" in workflow_support.preview_text(app)
            assert "Custom sizing can change page count" in workflow_support.preview_text(app)

    asyncio.run(run())


def test_textual_app_edit_settings_state(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("7")
            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await pilot.pause()
            await app.action_edit_output()
            await workflow_support.save_picker_name(app, pilot, "backup-out")
            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            qr_chunk = app.query_one("#setting-control-qr_chunk_size", Input)
            assert isinstance(qr_chunk, MaskedInput)
            qr_chunk.value = ""
            qr_chunk.focus()
            await workflow_support.type_text(pilot, "1024")
            await pilot.press("enter")

            assert app.settings_state.validate_task().ready
            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert app.settings_state.backup_output_dir is not None
            assert app.settings_state.backup_output_dir.name == "backup-out"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert config_path.exists()
            saved = SettingsTaskState.from_current(config_path)
            assert saved.design == "forge"
            assert saved.paper_size == "LETTER"
            assert saved.backup_output_dir is not None
            assert saved.backup_output_dir.name == "backup-out"
            assert saved.setting_value("qr_chunk_size") == 1024

    asyncio.run(run())


def test_textual_app_settings_categories_show_advanced_and_config_actions(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with run_app_test(app, size=(120, 72)) as pilot:
            await pilot.press("7")

            assert workflow_support.button_label(app, "#settings-reset-section") == "Reset section"
            assert workflow_support.button_label(app, "#settings-reset-all") == "Reset all settings"
            assert workflow_support.button_label(app, "#settings-copy-config") == "Copy path"
            assert workflow_support.button_label(app, "#settings-open-config") == "Open folder"
            settings_form = app.query_one(SettingsForm)
            assert settings_form.active_group == "Printing"
            save_status = app.query_one("#settings-save-status", Static)
            assert save_status.display
            assert save_status.region.height == 3
            assert str(save_status.content) == "Saved"
            assert settings_form.query_one("#settings-heading").region.y < save_status.region.y
            assert save_status.region.x > settings_form.region.x + settings_form.region.width // 2

            settings_form.show_group("Config file")
            await pilot.pause()
            app.query_one("#settings-copy-config", Button).focus()
            await _wait_for_condition(
                pilot,
                lambda: (
                    settings_form.active_group == "Config file"
                    and app.query_one("#settings-copy-config", Button).region.width > 0
                    and app.query_one("#settings-open-config", Button).region.width > 0
                ),
                "config settings pane layout",
            )

            assert settings_form.active_group == "Config file"
            workflow_support.assert_buttons_are_spaced(
                app.query_one("#setting-row-config .inline-action-group")
            )
            copy_path = app.query_one("#settings-copy-config", Button).region
            open_folder = app.query_one("#settings-open-config", Button).region
            assert copy_path.x + copy_path.width < open_folder.x
            assert workflow_support.static_text(app, "#settings-save-status") == "Saved"
            assert (
                workflow_support.static_text(app, "#settings-recovery-summary")
                == "3 recovery sheets; any 2 required"
            )
            assert not app.query_one("#setting-help-backup_signing_key_mode").display
            signing_key_options = app.query_one(
                "#setting-control-backup_signing_key_mode",
                Select,
            )._options
            assert ("Use built-in default (Embedded)", "__none__") in signing_key_options
            compression_options = app.query_one(
                "#setting-control-backup_payload_codec",
                Select,
            )._options
            qr_encoding_options = app.query_one(
                "#setting-control-backup_qr_payload_codec",
                Select,
            )._options
            assert ("Automatic (recommended)", "auto") in compression_options
            assert ("Raw (recommended)", "raw") in qr_encoding_options

            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            app.query_one("#setting-control-qr_chunk_size", Input).focus()
            await _wait_for_condition(
                pilot,
                lambda: "More bytes" in workflow_support.static_text(app, "#settings-focus-help"),
                "advanced settings focus help",
            )

            assert settings_form.active_group == "Advanced"
            assert app.query_one("#setting-row-qr_chunk_size").display
            assert not app.query_one("#setting-help-qr_chunk_size").display
            assert workflow_support.button_label(app, "#settings-reset-section") == "Reset section"
            assert "More bytes can reduce page count" in workflow_support.static_text(
                app, "#settings-focus-help"
            )

    asyncio.run(run())


def test_textual_app_settings_middle_truncates_long_config_path(tmp_path) -> None:
    async def run() -> None:
        config_dir = tmp_path / "one" / "two" / "three" / "four" / "five" / "six"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with run_app_test(app, size=(96, 40)) as pilot:
            await pilot.press("7")

            rendered_path = workflow_support.static_text(app, "#setting-value-config")

            assert "..." in rendered_path
            assert rendered_path.endswith(str(Path("six/config.toml")))
            assert rendered_path != str(config_path)
            assert len(rendered_path) <= 56

    asyncio.run(run())


def test_textual_app_settings_restores_section_and_all_defaults(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        app = EthernityApp(settings_state=SettingsTaskState.from_current(config_path))
        async with run_app_test(app, size=(120, 72)) as pilot:
            await pilot.press("7")

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await _wait_for_condition(
                pilot,
                lambda: (
                    app.settings_state.design == "forge"
                    and app.settings_state.paper_size == "LETTER"
                ),
                "printing settings to be applied",
            )

            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert workflow_support.static_text(app, "#setting-marker-render_style") == "Custom"
            assert workflow_support.static_text(app, "#setting-marker-page_size") == "Custom"

            app.query_one("#settings-reset-section", Button).focus()
            await pilot.press("enter")

            assert app.settings_state.design == "sentinel"
            assert app.settings_state.paper_size == "A4"
            assert workflow_support.static_text(app, "#setting-marker-render_style") == ""
            assert workflow_support.static_text(app, "#setting-marker-page_size") == ""

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one(SettingsForm).show_group("Advanced")
            await pilot.pause()
            qr_chunk = app.query_one("#setting-control-qr_chunk_size", Input)
            qr_chunk.value = ""
            qr_chunk.focus()
            await workflow_support.type_text(pilot, "1024")
            await pilot.press("enter")

            assert app.settings_state.design == "forge"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert workflow_support.static_text(app, "#setting-marker-qr_chunk_size") == "Custom"
            assert (
                "A custom QR size changes page count and scan reliability"
                in workflow_support.preview_text(app)
            )

            await workflow_support.open_reset_all(app, pilot)

            assert isinstance(app.screen, ConfirmActionScreen)
            assert app.settings_state.design == "forge"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            await pilot.click("#confirm-action-cancel")
            await pilot.pause()

            await workflow_support.open_reset_all(app, pilot)
            assert isinstance(app.screen, ConfirmActionScreen)
            await pilot.click("#confirm-action-confirm")
            await pilot.pause()

            workflow_support.assert_default_settings_saved(app, config_path)

    asyncio.run(run())


def test_textual_app_settings_restores_focused_section_from_command_action(tmp_path) -> None:
    async def run() -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            Path("src/ethernity/resources/config/config.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        settings = SettingsTaskState.from_current(config_path)
        settings.set_setting_value("qr_chunk_size", 1024)
        app = EthernityApp(settings_state=settings)
        async with run_app_test(app, size=(120, 72)) as pilot:
            await pilot.press("7")

            app.query_one("#setting-control-render_style", Select).value = "forge"
            await pilot.pause()
            app.query_one("#setting-control-page_size", Select).value = "LETTER"
            await pilot.pause()

            assert app.settings_state.design == "forge"
            assert app.settings_state.paper_size == "LETTER"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024

            app.query_one("#setting-control-render_style", Select).focus()
            await pilot.pause()
            command = next(
                command
                for command in app._workflow_system_commands()
                if command.title == "Reset current section"
            )
            command.callback()
            await pilot.pause()

            assert app.settings_state.design == "sentinel"
            assert app.settings_state.paper_size == "A4"
            assert app.settings_state.setting_value("qr_chunk_size") == 1024
            assert workflow_support.static_text(app, "#setting-marker-render_style") == ""
            assert workflow_support.static_text(app, "#setting-marker-qr_chunk_size") == "Custom"

    asyncio.run(run())


def test_textual_app_print_kit_warns_before_replacing_existing_pdf(tmp_path) -> None:
    async def run() -> None:
        output_path = tmp_path / "kit.pdf"
        output_path.write_text("existing", encoding="utf-8")
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=output_path))
        async with run_app_test(app, size=(120, 32)) as pilot:
            await pilot.press("6")

            assert (
                "Warning: This PDF exists. Creating the kit will replace it."
                in workflow_support.static_text(app, "#kit-output-notice")
            )
            assert "Selected PDF file already exists" in workflow_support.preview_text(app)

            await pilot.press("ctrl+r")

            review_text = workflow_support.read_review_text(app)
            assert "Warning" in review_text
            assert "Selected PDF file already exists" in review_text
            assert str(output_path) in review_text
            assert "Existing files at the destination may be replaced." in review_text
            assert not app.screen.query_one("#review-execute", Button).disabled

    asyncio.run(run())
