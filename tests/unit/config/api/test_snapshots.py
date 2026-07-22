from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

from ethernity.config.api.service import get_api_config_snapshot
from ethernity.config.install import ONBOARDING_FIELDS
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from tests.unit.config.api._support import isolated_user_config, temporary_config_path


def test_snapshot_uses_default_target_when_user_config_is_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        with isolated_user_config(config_root):
            snapshot = get_api_config_snapshot()

    render = cast(dict[str, Any], snapshot.values["render"])
    assert snapshot.source == "default"
    assert snapshot.status == "valid"
    assert snapshot.errors == ()
    assert snapshot.path == str(DEFAULT_CONFIG_PATH)
    assert snapshot.options["render_styles"] == [
        "archive",
        "forge",
        "ledger",
        "maritime",
        "sentinel",
    ]
    assert snapshot.options["onboarding_fields"] == list(ONBOARDING_FIELDS)
    assert not snapshot.onboarding["needed"]
    assert snapshot.onboarding["configured_fields"] == []
    assert render["style"] == "sentinel"


def test_snapshot_uses_user_config_target_when_present() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        config_root.mkdir(parents=True, exist_ok=True)
        (config_root / "config.toml").write_text(
            DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        with isolated_user_config(config_root):
            snapshot = get_api_config_snapshot()

    assert snapshot.source == "user"
    assert snapshot.status == "valid"
    assert snapshot.path.endswith("config.toml")


def test_snapshot_reports_invalid_toml_and_defaults() -> None:
    with temporary_config_path('[defaults.backup\noutput_dir = "oops"\n') as path:
        snapshot = get_api_config_snapshot(path)

    page = cast(dict[str, Any], snapshot.values["page"])
    assert snapshot.status == "invalid_toml"
    assert snapshot.errors
    assert page["size"] == "A4"


def test_snapshot_repairs_invalid_extension_chunking_order() -> None:
    with temporary_config_path(
        DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
            "target_size = 16384\nmin_size = 4096\nmax_size = 65536",
            "target_size = 4096\nmin_size = 16384\nmax_size = 65536",
            1,
        )
    ) as path:
        snapshot = get_api_config_snapshot(path)

    extension = cast(dict[str, Any], snapshot.values["extension"])
    chunking = cast(dict[str, Any], extension["chunking"])
    assert snapshot.status == "invalid_values"
    assert snapshot.errors
    assert chunking == {"target_size": 16384, "min_size": 4096, "max_size": 65536}


def test_snapshot_repairs_out_of_profile_extension_chunking() -> None:
    with temporary_config_path(
        DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
            "target_size = 16384\nmin_size = 4096\nmax_size = 65536",
            "target_size = 1024\nmin_size = 1024\nmax_size = 4096",
            1,
        )
    ) as path:
        snapshot = get_api_config_snapshot(path)

    extension = cast(dict[str, Any], snapshot.values["extension"])
    chunking = cast(dict[str, Any], extension["chunking"])
    assert snapshot.status == "invalid_values"
    assert snapshot.errors
    assert chunking == {"target_size": 16384, "min_size": 4096, "max_size": 65536}


def test_explicit_config_snapshot_hides_onboarding_state() -> None:
    with temporary_config_path(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) as path:
        snapshot = get_api_config_snapshot(path)

    assert snapshot.source == "explicit"
    assert not snapshot.onboarding["needed"]
    assert snapshot.onboarding["configured_fields"] == []
