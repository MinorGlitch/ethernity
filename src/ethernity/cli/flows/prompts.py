#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..api import prompt_choice, prompt_optional, prompt_required_paths


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
        choice = prompt_choice(
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
        path = prompt_optional("Output file path", help_text=help_text)
        return path or default_name

    default_dir = f"recovered-{doc_id.hex()}" if doc_id else "recovered-output"
    help_text = f"Leave blank to use {default_dir}. A directory will be created if needed."
    directory = prompt_optional("Output directory", help_text=help_text)
    return directory or default_dir


def _prompt_shard_inputs() -> tuple[list[str], list[str], str]:
    choice = prompt_choice(
        "Shard input format",
        {
            "fallback": "Text files (human-readable from shard PDFs)",
            "frames": "Binary payload files (from QR scanning)",
        },
        default="fallback",
        help_text="Text files are easier to copy; binary is from QR extraction.",
    )
    if choice == "fallback":
        paths = prompt_required_paths(
            "Shard text file paths (one per line, blank when done)",
            help_text="Enter paths to text files copied from shard documents.",
            kind="file",
            empty_message="At least one shard file is required.",
        )
        return paths, [], "auto"

    paths = prompt_required_paths(
        "Shard payload file paths (one per line, blank when done)",
        help_text="Enter paths to files with extracted QR payloads.",
        kind="file",
        empty_message="At least one shard file is required.",
    )
    encoding = prompt_choice(
        "Payload encoding",
        {
            "auto": "Auto-detect (Recommended)",
            "base64": "Base64",
            "base64url": "Base64 URL-safe",
            "hex": "Hex",
        },
        default="auto",
        help_text="Usually auto-detect works. Only change if you know the encoding.",
    )
    return [], paths, encoding
