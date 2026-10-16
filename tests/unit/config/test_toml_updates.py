"""Config edits preserve user text and keep optional values recoverable."""

from __future__ import annotations

import tomllib

import pytest

from ethernity.config._toml_support import upsert_table_key
from ethernity.config.editing.toml_writer import update_config_toml


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    "assignment",
    [
        '  output_dir = "old/#folder" # keep this comment',
        "  output_dir = 'old/#folder' # keep this comment",
        r'  output_dir = "old/\"#folder" # keep this comment',
        r'  output_dir = "old/\\#folder" # keep this comment',
    ],
)
def test_assignment_preserves_quoted_hashes_comments_and_line_endings(
    assignment: str, line_ending: str
) -> None:
    original = line_ending.join(("[defaults.backup]", assignment, "[ui]", "quiet = true", ""))
    updated = upsert_table_key(
        original, table="defaults.backup", key="output_dir", value='"new/#folder"'
    )
    assert updated == line_ending.join(
        (
            "[defaults.backup]",
            '  output_dir = "new/#folder" # keep this comment',
            "[ui]",
            "quiet = true",
            "",
        )
    )
    assert tomllib.loads(updated)["defaults"]["backup"]["output_dir"] == "new/#folder"


def test_config_writer_handles_nested_tables_and_optional_values() -> None:
    original = '# user comment\n[other]\nretained = "yes"\n'
    values = {
        "defaults": {
            "backup": {
                "output_dir": None,
                "shard_count": None,
                "signing_key_mode": None,
            },
            "recover": {"output": None},
        },
        "ui": {"quiet": True, "no_color": False},
        "qr": {"error": "M", "chunk_size": 256},
    }
    updated = update_config_toml(original, values)
    parsed = tomllib.loads(updated)
    assert updated.startswith(original)
    assert parsed["other"] == {"retained": "yes"}
    assert parsed["defaults"]["backup"] == {
        "output_dir": "",
        "shard_count": 0,
        "signing_key_mode": "",
    }
    assert parsed["defaults"]["recover"] == {"output": ""}
    assert parsed["ui"] == values["ui"]
    assert parsed["qr"] == values["qr"]
    assert update_config_toml(updated, values) == updated
