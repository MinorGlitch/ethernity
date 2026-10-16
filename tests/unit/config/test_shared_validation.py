"""Configuration loading, editing, and task validation enforce the same rules."""

import copy
from pathlib import Path

import pytest

from ethernity.config import load_app_config
from ethernity.config.editing.models import ConfigPatchError
from ethernity.config.editing.service import apply_config_patch, get_config_snapshot
from ethernity.config.editing.toml_writer import update_config_toml
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.config.validation import CONFIG_VALUE_FIELDS, assess_config_values
from ethernity.tasks.settings import SETTING_DESCRIPTORS, SettingsTaskState


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("changes", "section", "conflict"),
    (
        ({"qr_chunk_size": True}, "qr_chunk_size", False),
        ({"qr_chunk_size": "512"}, "qr_chunk_size", False),
        ({"qr_chunk_size": -1}, "qr_chunk_size", False),
        ({"qr_error": "X"}, "qr_error", False),
        ({"ui_no_color": "false"}, "ui_no_color", False),
        ({"backup_base_dir": 123}, "backup_base_dir", False),
        ({"backup_shard_threshold": 2, "backup_shard_count": 256}, "backup_shard_count", False),
        ({"backup_shard_threshold": 2}, "backup_shard_threshold", True),
        ({"backup_shard_threshold": 3, "backup_shard_count": 2}, "backup_shard_count", True),
        ({"backup_signing_key_mode": "sharded"}, "backup_signing_key_mode", True),
        (
            {"backup_signing_key_shard_threshold": 2, "backup_signing_key_shard_count": 3},
            "backup_signing_key_mode",
            True,
        ),
        (
            {
                "backup_shard_threshold": 2,
                "backup_shard_count": 3,
                "backup_signing_key_mode": "sharded",
                "backup_signing_key_shard_threshold": 4,
                "backup_signing_key_shard_count": 3,
            },
            "backup_signing_key_shard_count",
            True,
        ),
        ({"extension_chunk_min": 2048}, "extension_chunk_target", False),
    ),
)
def test_invalid_values_are_rejected_by_every_caller_and_remain_editable(
    config_file: Path, changes: dict[str, object], section: str, conflict: bool
) -> None:
    state = SettingsTaskState.from_current(config_file)
    for key, value in changes.items():
        state.set_setting_value(key, value)
    original = update_config_toml(config_file.read_text(), state.values)
    config_file.write_text(original)

    with pytest.raises(ValueError):
        load_app_config(config_file)
    current = SettingsTaskState.from_current(config_file)
    assert not current.validate_task().ready
    assert any(issue.section == section for issue in current.validate_task().issues)
    for key, value in changes.items():
        assert current.setting_value(key) == value
    with pytest.raises(ConfigPatchError) as raised:
        apply_config_patch(config_file, {"values": {}})
    assert raised.value.code == ("CONFIG_CONFLICT" if conflict else "CONFIG_INVALID_VALUE")
    assert config_file.read_text() == original


def test_all_editable_fields_have_one_constraint_definition() -> None:
    assert CONFIG_VALUE_FIELDS == {".".join(descriptor.path) for descriptor in SETTING_DESCRIPTORS}


def test_normalization_agrees_across_callers_and_preserves_path_case(config_file: Path) -> None:
    state = SettingsTaskState.from_current(config_file)
    state.set_setting_value("page_size", " letter ")
    state.set_setting_value("qr_error", " q ")
    state.set_setting_value("backup_base_dir", " /Data/Secrets ")
    state.set_setting_value("backup_shard_threshold", 0)
    state.set_setting_value("backup_shard_count", 0)
    raw = copy.deepcopy(state.values)
    config_file.write_text(update_config_toml(config_file.read_text(), raw))

    assert state.validate_task().ready
    loaded = load_app_config(config_file)
    assert loaded.paper_size == "LETTER"
    assert loaded.qr_config.error == "Q"
    assert loaded.cli_defaults.backup.base_dir == "/Data/Secrets"
    assert loaded.cli_defaults.backup.shard_threshold is None
    result = apply_config_patch(config_file, {"values": raw})
    assert result.status == "valid"
    assert result.values["page"] == {"size": "LETTER"}
    assert state.values == raw


def test_assessment_reports_all_errors_without_mutating_values(config_file: Path) -> None:
    state = SettingsTaskState.from_current(config_file)
    state.set_setting_value("qr_chunk_size", False)
    state.set_setting_value("backup_shard_count", 256)
    state.set_setting_value("ui_no_color", 1)
    original = copy.deepcopy(state.values)
    _, issues = assess_config_values(state.values)
    assert {issue.field for issue in issues} == {
        "qr.chunk_size",
        "defaults.backup.shard_count",
        "ui.no_color",
        "defaults.backup.shard_threshold",
    }
    assert state.values == original


def test_patch_can_repair_an_invalid_scalar_that_contains_a_table(config_file: Path) -> None:
    config_file.write_text(config_file.read_text().replace('error = "M"', 'error = { name = "M" }'))
    snapshot = get_config_snapshot(config_file)
    assert snapshot.status == "invalid_values"
    assert snapshot.values["qr"]["error"] == {"name": "M"}
    repaired = apply_config_patch(config_file, {"values": {"qr": {"error": "Q"}}})
    assert repaired.status == "valid"
    assert load_app_config(config_file).qr_config.error == "Q"


def test_invalid_sections_report_one_issue_and_reject_unknown_repair_fields(
    config_file: Path,
) -> None:
    values = get_config_snapshot(config_file).values
    values["qr"] = 7
    _, issues = assess_config_values(values)
    assert len(issues) == 1
    assert issues[0].field == "qr"
    assert issues[0].reason == "section"
    config_file.write_text('qr = 7\n[defaults.backup]\nqr_payload_codec = "raw"\n')
    state = SettingsTaskState.from_current(config_file)
    assert state.values["qr"] == 7
    assert not state.validate_task().ready
    with pytest.raises(ConfigPatchError) as raised:
        apply_config_patch(config_file, {"values": {"qr": {"unknown": 1}}})
    assert raised.value.code == "CONFIG_UNKNOWN_FIELD"


def test_save_rejects_a_malformed_table_structure_without_overwriting_it(config_file: Path) -> None:
    original = 'qr = 7\n[defaults.backup]\nqr_payload_codec = "raw"\n'
    config_file.write_text(original)
    with pytest.raises(ConfigPatchError, match="TOML structure"):
        apply_config_patch(config_file, {"values": {"qr": {"error": "M", "chunk_size": 512}}})
    assert config_file.read_text() == original
