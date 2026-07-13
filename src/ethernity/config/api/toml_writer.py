"""Serialize validated API config values into the repository TOML shape."""

from __future__ import annotations

from typing import cast

from ethernity.config._toml_support import toml_quote, upsert_table_key


def update_config_toml(original: str, values: dict[str, object]) -> str:
    line_ending = "\r\n" if "\r\n" in original else "\n"
    updated = original

    render = cast(dict[str, object], values["render"])
    page = cast(dict[str, object], values["page"])
    qr = cast(dict[str, object], values["qr"])
    extension = cast(dict[str, object], values["extension"])
    extension_chunking = cast(dict[str, object], extension["chunking"])
    defaults = cast(dict[str, object], values["defaults"])
    backup = cast(dict[str, object], defaults["backup"])
    recover = cast(dict[str, object], defaults["recover"])
    extend = cast(dict[str, object], defaults["extend"])
    ui = cast(dict[str, object], values["ui"])
    debug = cast(dict[str, object], values["debug"])
    runtime = cast(dict[str, object], values["runtime"])

    updated = upsert_table_key(
        updated,
        table="render",
        key="style",
        value=toml_quote(cast(str, render["style"])),
    )
    updated = upsert_table_key(
        updated,
        table="page",
        key="size",
        value=toml_quote(cast(str, page["size"])),
    )
    updated = upsert_table_key(
        updated,
        table="qr",
        key="error",
        value=toml_quote(cast(str, qr["error"])),
    )
    updated = upsert_table_key(
        updated,
        table="qr",
        key="chunk_size",
        value=str(cast(int, qr["chunk_size"])),
    )
    updated = upsert_table_key(
        updated,
        table="extension.chunking",
        key="target_size",
        value=str(cast(int, extension_chunking["target_size"])),
    )
    updated = upsert_table_key(
        updated,
        table="extension.chunking",
        key="min_size",
        value=str(cast(int, extension_chunking["min_size"])),
    )
    updated = upsert_table_key(
        updated,
        table="extension.chunking",
        key="max_size",
        value=str(cast(int, extension_chunking["max_size"])),
    )

    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="base_dir",
        value=toml_quote(cast(str | None, backup["base_dir"]) or ""),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="output_dir",
        value=toml_quote(cast(str | None, backup["output_dir"]) or ""),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="shard_threshold",
        value=str(cast(int | None, backup["shard_threshold"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="shard_count",
        value=str(cast(int | None, backup["shard_count"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="signing_key_mode",
        value=toml_quote(cast(str | None, backup["signing_key_mode"]) or ""),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="signing_key_shard_threshold",
        value=str(cast(int | None, backup["signing_key_shard_threshold"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="signing_key_shard_count",
        value=str(cast(int | None, backup["signing_key_shard_count"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="payload_codec",
        value=toml_quote(cast(str, backup["payload_codec"])),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.backup",
        key="qr_payload_codec",
        value=toml_quote(cast(str, backup["qr_payload_codec"])),
    )

    updated = upsert_table_key(
        updated,
        table="defaults.recover",
        key="output",
        value=toml_quote(cast(str | None, recover["output"]) or ""),
    )

    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="base_dir",
        value=toml_quote(cast(str | None, extend["base_dir"]) or ""),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="unlock_policy",
        value=toml_quote(cast(str | None, extend["unlock_policy"]) or ""),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="shard_threshold",
        value=str(cast(int | None, extend["shard_threshold"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="shard_count",
        value=str(cast(int | None, extend["shard_count"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="signing_key_mode",
        value=toml_quote(cast(str | None, extend["signing_key_mode"]) or ""),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="signing_key_shard_threshold",
        value=str(cast(int | None, extend["signing_key_shard_threshold"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="signing_key_shard_count",
        value=str(cast(int | None, extend["signing_key_shard_count"]) or 0),
    )
    updated = upsert_table_key(
        updated,
        table="defaults.extend",
        key="qr_payload_codec",
        value=toml_quote(cast(str, extend["qr_payload_codec"])),
    )

    updated = upsert_table_key(
        updated,
        table="ui",
        key="quiet",
        value=_toml_bool(cast(bool, ui["quiet"])),
    )
    updated = upsert_table_key(
        updated,
        table="ui",
        key="no_color",
        value=_toml_bool(cast(bool, ui["no_color"])),
    )
    updated = upsert_table_key(
        updated,
        table="ui",
        key="no_animations",
        value=_toml_bool(cast(bool, ui["no_animations"])),
    )
    updated = upsert_table_key(
        updated,
        table="ui",
        key="show_internals",
        value=_toml_bool(cast(bool, ui["show_internals"])),
    )
    updated = upsert_table_key(
        updated,
        table="debug",
        key="max_bytes",
        value=str(cast(int | None, debug["max_bytes"]) or 0),
    )

    render_jobs = runtime["render_jobs"]
    updated = upsert_table_key(
        updated,
        table="runtime",
        key="render_jobs",
        value=(
            toml_quote(render_jobs)
            if isinstance(render_jobs, str)
            else str(render_jobs)
            if render_jobs is not None
            else toml_quote("")
        ),
    )

    if not updated.endswith(("\n", "\r\n")):
        updated += line_ending
    return updated


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


__all__ = ["update_config_toml"]
