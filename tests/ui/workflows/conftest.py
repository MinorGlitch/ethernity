from pathlib import Path

import pytest

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.settings import SettingsTaskState


@pytest.fixture
def isolated_app_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep TUI tests deterministic and away from the user's real config file."""
    config_path = tmp_path / "default-config.toml"
    config_path.write_bytes(DEFAULT_CONFIG_PATH.read_bytes())
    from_current = SettingsTaskState.from_current.__func__

    def load_settings(
        cls: type[SettingsTaskState],
        requested_path: Path | None = None,
    ) -> SettingsTaskState:
        return from_current(cls, config_path if requested_path is None else requested_path)

    monkeypatch.setattr(SettingsTaskState, "from_current", classmethod(load_settings))
