from __future__ import annotations

from pathlib import Path

from ethernity.tasks.quorum import MAX_SHARDS


def parse_paths(value: str) -> list[Path]:
    return [Path(item.strip()) for item in value.split(",") if item.strip()]


def parse_setting_value(
    value: str,
    *,
    kind: str,
    options: tuple[str, ...],
    default: object,
) -> object:
    text = value.strip()
    if not text:
        return None if default is None else default
    if kind == "enum":
        match = next((option for option in options if option.lower() == text.lower()), None)
        if match is None:
            allowed = ", ".join(options) if options else "a supported value"
            raise ValueError(f"Use one of: {allowed}.")
        return match
    if kind in {"int", "optional_int"}:
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError("Use a positive whole number.") from exc
        if parsed <= 0:
            raise ValueError("Use a positive whole number.")
        return parsed
    if kind == "render_jobs":
        if text.lower() == "auto":
            return "auto"
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError("Use auto or a positive whole number.") from exc
        if parsed <= 0:
            raise ValueError("Use auto or a positive whole number.")
        return parsed
    return text


def parse_threshold_count(value: str) -> tuple[int, int] | None:
    normalized = value.replace(" of ", "/").replace(" ", "")
    separator = "/" if "/" in normalized else "," if "," in normalized else None
    if separator is None:
        return None
    left, right = normalized.split(separator, 1)
    try:
        threshold = int(left)
        count = int(right)
    except ValueError:
        return None
    if threshold < 1 or count < threshold or threshold > MAX_SHARDS or count > MAX_SHARDS:
        return None
    return threshold, count


def parse_layout(value: str, *, fallback: tuple[str, str]) -> tuple[str, str]:
    paper_size, design = fallback
    for token in value.split():
        normalized = token.strip()
        if normalized.upper() in {"A4", "LETTER"}:
            paper_size = normalized.upper()
        elif normalized:
            design = normalized.lower()
    return paper_size, design


def parse_update_index(value: str) -> int | None:
    normalized = value.removeprefix("update").strip()
    if not normalized:
        return None
    try:
        index = int(normalized)
    except ValueError:
        return None
    return index if index > 0 else None
