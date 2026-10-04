from __future__ import annotations

import pytest

from ethernity.config.api.models import ConfigPatchError
from ethernity.config.api.service import apply_api_config_patch
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from tests.unit.config.api._support import temporary_config_path


def test_patch_rejects_unknown_field() -> None:
    with temporary_config_path(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) as path:
        with pytest.raises(ConfigPatchError) as raised:
            apply_api_config_patch(path, {"values": {"unknown": {"value": True}}})

    assert raised.value.code == "CONFIG_UNKNOWN_FIELD"


def test_patch_accepts_custom_extension_chunking_settings() -> None:
    with temporary_config_path(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) as path:
        snapshot = apply_api_config_patch(
            path,
            {
                "values": {
                    "extension": {
                        "chunking": {
                            "target_size": 32768,
                            "min_size": 8192,
                            "max_size": 131072,
                        }
                    }
                }
            },
        )

    assert snapshot.values["extension"] == {
        "chunking": {
            "target_size": 32768,
            "min_size": 8192,
            "max_size": 131072,
        }
    }


@pytest.mark.parametrize(
    "chunking",
    (
        {"target_size": True},
        {"min_size": 2048},
        {"target_size": 131072, "max_size": 65536},
    ),
)
def test_patch_rejects_invalid_extension_chunking_settings(
    chunking: dict[str, object],
) -> None:
    with temporary_config_path(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) as path:
        with pytest.raises(ConfigPatchError) as raised:
            apply_api_config_patch(
                path,
                {"values": {"extension": {"chunking": chunking}}},
            )

    assert raised.value.code == "CONFIG_INVALID_VALUE"


@pytest.mark.parametrize(
    "patch_values",
    (
        {"shard_threshold": 2, "shard_count": None},
        {"shard_threshold": 3, "shard_count": 2},
        {"unlock_policy": "reuse-root", "shard_threshold": 2, "shard_count": 3},
        {"signing_key_mode": "embedded"},
        {"signing_key_shard_threshold": 2, "signing_key_shard_count": None},
        {"signing_key_shard_threshold": 2, "signing_key_shard_count": 3},
        {
            "signing_key_mode": "sharded",
            "signing_key_shard_threshold": 4,
            "signing_key_shard_count": 3,
        },
    ),
)
def test_patch_rejects_removed_add_files_policy_fields(patch_values: dict[str, object]) -> None:
    with temporary_config_path(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) as path:
        with pytest.raises(ConfigPatchError) as raised:
            apply_api_config_patch(
                path,
                {"values": {"defaults": {"add_files": patch_values}}},
            )

    assert raised.value.code == "CONFIG_UNKNOWN_FIELD"
