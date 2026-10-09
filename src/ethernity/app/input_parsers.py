from __future__ import annotations

from pathlib import Path

from ethernity.crypto.document_identity import DOC_HASH_LEN, normalize_doc_hash_hex
from ethernity.crypto.sharding import MAX_SHARES
from ethernity.page_sizes import is_registered_paper_size, resolve_paper_size
from ethernity.tasks.page_layout import require_workflow_page_size


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
    if threshold < 1 or count < threshold or threshold > MAX_SHARES or count > MAX_SHARES:
        return None
    return threshold, count


def parse_layout(value: str, *, fallback: tuple[str, str]) -> tuple[str, str]:
    paper_size, design = fallback
    for token in value.split():
        normalized = token.strip()
        if is_registered_paper_size(normalized):
            paper_size = resolve_paper_size(normalized).name
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


def validate_quorum(value: str) -> str | None:
    if parse_threshold_count(value.strip().lower()) is not None:
        return None
    return (
        f"Use required/total from 1 to {MAX_SHARES}, such as 2/3. "
        "Required sheets cannot exceed total sheets."
    )


def validate_backup_recovery(value: str) -> str | None:
    if value.strip().lower() in {
        "",
        "recommended",
        "recommended_shards",
        "shards",
        "single",
        "single_phrase",
        "phrase",
    }:
        return None
    return validate_quorum(value)


def validate_new_recovery_sheets(value: str) -> str | None:
    if value.strip().lower() in {"", "off", "none", "no", "recommended", "default"}:
        return None
    return validate_quorum(value)


def validate_optional_positive_integer(value: str) -> str | None:
    if not value.strip():
        return None
    try:
        if int(value.strip()) > 0:
            return None
    except ValueError:
        pass
    return "Use a positive whole number, or clear the value."


def validate_layout(
    value: str,
    *,
    fallback: tuple[str, str],
    candidate_doc_types: frozenset[str],
) -> str | None:
    paper_size, design = parse_layout(value, fallback=fallback)
    try:
        require_workflow_page_size(
            design,
            paper_size,
            candidate_doc_types=candidate_doc_types,
        )
    except ValueError as exc:
        return str(exc)
    return None


def validate_restore_target(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"", "latest", "original"} or parse_update_index(normalized) is not None:
        return None
    return "Use latest, original, or a positive update number."


def validate_optional_fingerprint(value: str) -> str | None:
    if not value.strip():
        return None
    try:
        normalize_doc_hash_hex(value, option="fingerprint")
    except ValueError:
        return f"Use the full {DOC_HASH_LEN * 2}-character hexadecimal fingerprint."
    return None
