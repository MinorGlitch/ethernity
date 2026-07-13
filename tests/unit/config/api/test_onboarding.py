from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ethernity.config.api.contracts import ConfigPatchError
from ethernity.config.api.service import apply_api_config_patch
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from tests.unit.config.api._support import isolated_user_config, temporary_config_path


def test_patch_requires_explicit_onboarding_mark_complete() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        with isolated_user_config(config_root):
            with pytest.raises(ConfigPatchError) as raised:
                apply_api_config_patch(
                    None,
                    {
                        "values": {"page": {"size": "LETTER"}},
                        "onboarding": {"configured_fields": []},
                    },
                )

    assert raised.value.code == "CONFIG_INVALID_VALUE"


def test_patch_rejects_empty_onboarding_object() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        with isolated_user_config(config_root):
            with pytest.raises(ConfigPatchError) as raised:
                apply_api_config_patch(None, {"onboarding": {}})

    assert raised.value.code == "CONFIG_INVALID_VALUE"


def test_patch_rejects_onboarding_for_explicit_config() -> None:
    with temporary_config_path(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) as path:
        with pytest.raises(ConfigPatchError) as raised:
            apply_api_config_patch(
                path,
                {"onboarding": {"mark_complete": True}},
            )

    assert raised.value.code == "CONFIG_CONFLICT"
