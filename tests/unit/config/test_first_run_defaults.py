"""First-run defaults validate both shard quorums before updating the file."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from ethernity.config.install import apply_first_run_defaults

_DEFAULTS = {
    "design": "sentinel",
    "payload_codec": "raw",
    "qr_payload_codec": "raw",
    "qr_error_correction": "M",
    "page_size": "A4",
    "backup_output_dir": None,
    "qr_chunk_size": 256,
    "shard_threshold": 2,
    "shard_count": 3,
    "signing_key_mode": "embedded",
}


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"shard_threshold": None}, "shard_threshold and shard_count must be set together"),
        ({"shard_threshold": 0}, "shard_threshold must be >= 1"),
        ({"shard_threshold": 256}, "shard_threshold must be <= 255"),
        ({"shard_count": 1}, "shard_count must be >= shard_threshold"),
        ({"shard_count": 256}, "shard_count must be <= 255"),
        ({"signing_key_mode": "invalid"}, "signing_key_mode must be"),
        (
            {"shard_threshold": None, "shard_count": None, "signing_key_mode": "sharded"},
            "signing_key_mode='sharded' requires passphrase sharding",
        ),
        (
            {"signing_key_shard_threshold": 2},
            "signing_key_shard_threshold and signing_key_shard_count must be set together",
        ),
        (
            {"signing_key_shard_threshold": 2, "signing_key_shard_count": 3},
            "signing key shard counts require signing_key_mode='sharded'",
        ),
        (
            {
                "signing_key_mode": "sharded",
                "signing_key_shard_threshold": 0,
                "signing_key_shard_count": 3,
            },
            "signing_key_shard_threshold must be >= 1",
        ),
        (
            {
                "signing_key_mode": "sharded",
                "signing_key_shard_threshold": 256,
                "signing_key_shard_count": 3,
            },
            "signing_key_shard_threshold must be <= 255",
        ),
        (
            {
                "signing_key_mode": "sharded",
                "signing_key_shard_threshold": 2,
                "signing_key_shard_count": 1,
            },
            "signing_key_shard_count must be >= signing_key_shard_threshold",
        ),
        (
            {
                "signing_key_mode": "sharded",
                "signing_key_shard_threshold": 2,
                "signing_key_shard_count": 256,
            },
            "signing_key_shard_count must be <= 255",
        ),
    ],
)
def test_invalid_defaults_leave_the_config_unchanged(
    tmp_path: Path, overrides: dict[str, object], error: str
) -> None:
    config_path = tmp_path / "config.toml"
    original = "[ui]\nquiet = false # user setting\n"
    config_path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(error)):
        apply_first_run_defaults(config_path, **(_DEFAULTS | overrides))
    assert config_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("overrides", "expected_mode", "signing_counts"),
    [
        ({"shard_threshold": None, "shard_count": None}, "", (0, 0)),
        ({"signing_key_mode": None}, "embedded", (0, 0)),
        ({}, "embedded", (0, 0)),
        ({"signing_key_mode": "sharded"}, "sharded", (0, 0)),
        (
            {
                "signing_key_mode": "sharded",
                "signing_key_shard_threshold": 1,
                "signing_key_shard_count": 2,
            },
            "sharded",
            (1, 2),
        ),
    ],
)
def test_defaults_keep_the_existing_shard_mode_encoding(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_mode: str,
    signing_counts: tuple[int, int],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[ui]\nquiet = false\n", encoding="utf-8")
    apply_first_run_defaults(config_path, **(_DEFAULTS | overrides))
    backup = tomllib.loads(config_path.read_text(encoding="utf-8"))["defaults"]["backup"]
    assert backup["signing_key_mode"] == expected_mode
    assert (
        backup["signing_key_shard_threshold"],
        backup["signing_key_shard_count"],
    ) == signing_counts
