"""Write validated configuration values to TOML."""

from __future__ import annotations

from collections.abc import Iterator

from ethernity.config._toml_support import toml_quote, upsert_table_key

_EMPTY_STRING_FIELDS = frozenset({"base_dir", "output_dir", "output", "signing_key_mode"})


def update_config_toml(original: str, values: dict[str, object]) -> str:
    """Write normalized scalar values while preserving unrelated config text."""

    updated = original
    for table, key, value in _config_fields(values):
        updated = upsert_table_key(updated, table=table, key=key, value=_toml_value(key, value))
    if not updated.endswith(("\n", "\r\n")):
        updated += "\r\n" if "\r\n" in original else "\n"
    return updated


def _config_fields(
    values: dict[str, object], *, table: str = ""
) -> Iterator[tuple[str, str, object]]:
    for key, value in values.items():
        if isinstance(value, dict):
            nested_table = f"{table}.{key}" if table else key
            yield from _config_fields(value, table=nested_table)
        else:
            yield table, key, value


def _toml_value(key: str, value: object) -> str:
    # TOML has no null. Optional paths/modes use an empty string; optional counts use zero.
    if value is None:
        return '""' if key in _EMPTY_STRING_FIELDS else "0"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return toml_quote(value)
    raise ValueError(f"unsupported config value for {key}: {type(value).__name__}")


__all__ = ["update_config_toml"]
