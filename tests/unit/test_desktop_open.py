"""System viewer commands use the same dispatch for folders and documents."""

from unittest.mock import Mock

import pytest

from ethernity.app import output_paths
from ethernity.app.widgets.settings_form import SettingsForm

pytestmark = pytest.mark.portability


@pytest.mark.parametrize(
    "platform,executable", [("darwin", "open"), ("win32", "explorer"), ("linux", "xdg-open")]
)
def test_system_viewer_uses_argument_lists(monkeypatch, tmp_path, platform, executable) -> None:
    commands = []
    paths = (tmp_path / "backup with spaces.pdf", tmp_path / "recovery.pdf")
    monkeypatch.setattr(output_paths.sys, "platform", platform)
    monkeypatch.setattr(output_paths.subprocess, "Popen", commands.append)

    output_paths.open_documents(paths)
    output_paths.open_folder(tmp_path)
    output_paths.open_documents(())

    expected = (
        [[executable, *(str(path) for path in paths)]]
        if platform == "darwin"
        else [[executable, str(path)] for path in paths]
    )
    assert commands == [*expected, [executable, str(tmp_path)]]


@pytest.mark.parametrize("error", [None, OSError("viewer unavailable")])
def test_settings_delegates_folder_opening_and_reports_errors(monkeypatch, tmp_path, error) -> None:
    form = SettingsForm()
    form._config_full_path = str(tmp_path / "config.toml")
    app = Mock()
    launch = Mock(side_effect=error)
    monkeypatch.setattr("ethernity.app.widgets.settings_form.open_folder", launch)
    monkeypatch.setattr(SettingsForm, "app", property(lambda self: app))

    form._open_config_folder()

    launch.assert_called_once_with(tmp_path)
    if error is None:
        app.notify.assert_called_once_with("Opening settings folder.")
    else:
        app.notify.assert_called_once_with(
            "Could not open folder: viewer unavailable", severity="error"
        )
