#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..ui import _prompt_choice, _prompt_optional, _prompt_required_paths


def _resolve_recover_output(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    interactive: bool,
    doc_id: bytes | None,
) -> str | None:
    if output_path or not interactive:
        return output_path
    if not entries:
        return output_path
    if len(entries) == 1:
        choice = _prompt_choice(
            "Recovered file output",
            {"file": "Save to a file", "stdout": "Print to stdout"},
            default="file",
            help_text="Printing binary data to the terminal may be unreadable.",
        )
        if choice == "stdout":
            return None
        entry = entries[0][0]
        default_name = "recovered.bin"
        entry_path = getattr(entry, "path", None)
        if entry_path:
            default_name = Path(entry_path).name
        help_text = f"Leave blank to use {default_name}."
        path = _prompt_optional("Output file path", help_text=help_text)
        return path or default_name

    default_dir = f"recovered-{doc_id.hex()}" if doc_id else "recovered-output"
    help_text = f"Leave blank to use {default_dir}. A directory will be created if needed."
    directory = _prompt_optional("Output directory", help_text=help_text)
    return directory or default_dir


def _prompt_shard_inputs() -> tuple[list[str], list[str], str]:
    choice = _prompt_choice(
        "Shard input",
        {
            "fallback": "Shard fallback text files (z-base-32)",
            "frames": "Shard frame payload files",
        },
        default="fallback",
        help_text="Choose the format you have for the shard documents.",
    )
    if choice == "fallback":
        paths = _prompt_required_paths(
            "Shard fallback text file paths (one per line, blank to finish)",
            help_text="Point at the shard fallback text files saved from the backup.",
            kind="file",
            empty_message="At least one shard fallback file is required.",
        )
        return paths, [], "auto"

    paths = _prompt_required_paths(
        "Shard frame payload file paths (one per line, blank to finish)",
        help_text="Provide files that contain the shard QR payloads.",
        kind="file",
        empty_message="At least one shard frame file is required.",
    )
    encoding = _prompt_choice(
        "Shard frames encoding",
        {"auto": "Auto", "base64": "Base64", "base64url": "Base64 URL-safe", "hex": "Hex"},
        default="auto",
        help_text="How the shard payloads are encoded in the file.",
    )
    return [], paths, encoding
