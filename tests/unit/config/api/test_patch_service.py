from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pytest

import ethernity.config.install as installer
from ethernity.config.api.contracts import ConfigPatchError
from ethernity.config.api.service import apply_api_config_patch
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from tests.unit.config.api._support import isolated_user_config, temporary_config_path


def test_patch_updates_values_and_onboarding_marker() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        with isolated_user_config(config_root):
            snapshot = apply_api_config_patch(
                None,
                {
                    "values": {
                        "render": {"style": "ledger"},
                        "page": {"size": "LETTER"},
                        "extension": {
                            "chunking": {
                                "target_size": 16384,
                                "min_size": 4096,
                                "max_size": 65536,
                            }
                        },
                        "defaults": {
                            "backup": {"output_dir": "/tmp/backups"},
                            "extend": {
                                "base_dir": "/tmp/extend-base",
                                "unlock_policy": "self-contained",
                                "shard_threshold": 2,
                                "shard_count": 3,
                                "signing_key_mode": "sharded",
                                "signing_key_shard_threshold": 2,
                                "signing_key_shard_count": 4,
                                "qr_payload_codec": "base64",
                            },
                        },
                    },
                    "onboarding": {
                        "mark_complete": True,
                        "configured_fields": ["page_size", "backup_output_dir"],
                    },
                },
            )
            parsed = tomllib.loads(Path(snapshot.path).read_text(encoding="utf-8"))

    defaults = cast(dict[str, Any], snapshot.values["defaults"])
    render = cast(dict[str, Any], snapshot.values["render"])
    backup = cast(dict[str, Any], defaults["backup"])
    extend = cast(dict[str, Any], defaults["extend"])

    assert snapshot.values["page"] == {"size": "LETTER"}
    assert render["style"] == "ledger"
    assert backup["output_dir"] == "/tmp/backups"
    assert extend["base_dir"] == "/tmp/extend-base"
    assert extend["unlock_policy"] == "self-contained"
    assert extend["shard_threshold"] == 2
    assert extend["shard_count"] == 3
    assert extend["signing_key_mode"] == "sharded"
    assert extend["signing_key_shard_threshold"] == 2
    assert extend["signing_key_shard_count"] == 4
    assert extend["qr_payload_codec"] == "base64"
    assert not snapshot.onboarding["needed"]
    assert snapshot.onboarding["configured_fields"] == ["backup_output_dir", "page_size"]
    assert parsed["page"]["size"] == "LETTER"
    assert parsed["render"]["style"] == "ledger"
    assert parsed["extension"]["chunking"]["target_size"] == 16384
    assert parsed["extension"]["chunking"]["min_size"] == 4096
    assert parsed["extension"]["chunking"]["max_size"] == 65536
    assert parsed["defaults"]["backup"]["output_dir"] == "/tmp/backups"
    assert parsed["defaults"]["extend"]["base_dir"] == "/tmp/extend-base"
    assert parsed["defaults"]["extend"]["unlock_policy"] == "self-contained"
    assert parsed["defaults"]["extend"]["shard_threshold"] == 2
    assert parsed["defaults"]["extend"]["shard_count"] == 3
    assert parsed["defaults"]["extend"]["signing_key_mode"] == "sharded"
    assert parsed["defaults"]["extend"]["signing_key_shard_threshold"] == 2
    assert parsed["defaults"]["extend"]["signing_key_shard_count"] == 4
    assert parsed["defaults"]["extend"]["qr_payload_codec"] == "base64"


def test_patch_repairs_invalid_current_values() -> None:
    with temporary_config_path(
        DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
            'size = "A4"',
            'size = "Letter"',
            1,
        )
    ) as path:
        snapshot = apply_api_config_patch(path, {"values": {"ui": {"quiet": True}}})
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))

    assert snapshot.status == "valid"
    assert parsed["page"]["size"] == "LETTER"
    assert parsed["ui"]["quiet"] is True


def test_patch_repairs_invalid_toml() -> None:
    with temporary_config_path('[defaults.backup\noutput_dir = "oops"\n') as path:
        snapshot = apply_api_config_patch(path, {"values": {"page": {"size": "LETTER"}}})
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))

    assert snapshot.status == "valid"
    assert parsed["page"]["size"] == "LETTER"


def test_patch_resets_onboarding_marker() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        with isolated_user_config(config_root):
            apply_api_config_patch(
                None,
                {
                    "onboarding": {
                        "mark_complete": True,
                        "configured_fields": ["page_size"],
                    }
                },
            )
            snapshot = apply_api_config_patch(
                None,
                {"onboarding": {"mark_complete": False}},
            )

    assert snapshot.onboarding["needed"]
    assert snapshot.onboarding["configured_fields"] == []


def test_patch_preserves_existing_render_style() -> None:
    initial = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
        '[render]\nstyle = "sentinel"',
        '[render]\nstyle = "ledger"',
        1,
    )
    with temporary_config_path(initial) as path:
        snapshot = apply_api_config_patch(path, {"values": {"ui": {"quiet": True}}})
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))

    render = cast(dict[str, Any], snapshot.values["render"])
    assert render["style"] == "ledger"
    assert parsed["render"]["style"] == "ledger"


def test_patch_reverts_config_when_marker_write_fails() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        with isolated_user_config(config_root):
            config_path = installer.resolve_writable_config_path(None)
            original = config_path.read_text(encoding="utf-8")
            original_write_text_atomic = installer._write_text_atomic

            def _fail_on_marker(path: Path, text: str) -> None:
                if path.name == ".first_run_onboarding_v1.done":
                    raise OSError("marker write failed")
                original_write_text_atomic(path, text)

            with (
                mock.patch(
                    "ethernity.config.api.service.write_text_atomic",
                    side_effect=_fail_on_marker,
                ),
                mock.patch.object(
                    installer,
                    "_write_text_atomic",
                    side_effect=_fail_on_marker,
                ),
                pytest.raises(OSError),
            ):
                apply_api_config_patch(
                    None,
                    {
                        "values": {"page": {"size": "LETTER"}},
                        "onboarding": {"mark_complete": True, "configured_fields": []},
                    },
                )

            assert config_path.read_text(encoding="utf-8") == original


def test_invalid_values_do_not_initialize_user_config() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir) / "config"
        config_path = config_root / "config.toml"
        with isolated_user_config(config_root):
            with pytest.raises(ConfigPatchError) as raised:
                apply_api_config_patch(None, {"values": "not-an-object"})

    assert raised.value.code == "CONFIG_INVALID_VALUE"
    assert not config_path.exists()
