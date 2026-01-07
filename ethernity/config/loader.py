#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar
import tomllib

from ..encoding.qr_payloads import normalize_qr_payload_encoding
from ..qr.codec import QrConfig
from .installer import (
    DEFAULT_KIT_TEMPLATE_PATH,
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    PACKAGE_ROOT,
    _resolve_config_path,
)

_T = TypeVar("_T")


@dataclass(frozen=True)
class AppConfig:
    template_path: Path
    recovery_template_path: Path
    shard_template_path: Path
    signing_key_shard_template_path: Path
    kit_template_path: Path
    paper_size: str
    qr_config: QrConfig
    qr_payload_encoding: str


def load_app_config(path: str | Path | None = None, *, paper_size: str | None = None) -> AppConfig:
    config_path = _resolve_config_path(path, paper_size=paper_size)
    data = _load_toml(config_path)
    config_dir = config_path.parent

    template_cfg = _get_dict(data, "template")
    template_path_value = template_cfg.get("path")
    template_path = _resolve_path(
        config_dir,
        _coerce_path_value(template_path_value, DEFAULT_TEMPLATE_PATH),
    )

    recovery_cfg = _get_dict(data, "recovery_template")
    recovery_path_value = recovery_cfg.get("path")
    recovery_path = _resolve_path(
        config_dir,
        _coerce_path_value(recovery_path_value, DEFAULT_RECOVERY_TEMPLATE_PATH),
    )

    shard_cfg = _get_dict(data, "shard_template")
    shard_path_value = shard_cfg.get("path")
    shard_path = _resolve_path(
        config_dir,
        _coerce_path_value(shard_path_value, DEFAULT_SHARD_TEMPLATE_PATH),
    )

    signing_key_shard_cfg = _get_dict(data, "signing_key_shard_template")
    signing_key_shard_path_value = signing_key_shard_cfg.get("path")
    signing_key_shard_path = _resolve_path(
        config_dir,
        _coerce_path_value(
            signing_key_shard_path_value,
            DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
        ),
    )

    kit_cfg = _get_dict(data, "kit_template")
    kit_path_value = kit_cfg.get("path")
    kit_path = _resolve_path(
        config_dir,
        _coerce_path_value(kit_path_value, DEFAULT_KIT_TEMPLATE_PATH),
    )

    page_cfg = _get_dict(data, "page")
    resolved_paper_size = (
        paper_size
        or _parse_optional_str(page_cfg.get("size"))
        or DEFAULT_PAPER_SIZE
    )
    qr_section = _get_dict(data, "qr")
    qr_config = build_qr_config(qr_section)
    qr_payload_encoding = normalize_qr_payload_encoding(
        _parse_optional_str(qr_section.get("payload_encoding"))
    )
    return AppConfig(
        template_path=template_path,
        recovery_template_path=recovery_path,
        shard_template_path=shard_path,
        signing_key_shard_template_path=signing_key_shard_path,
        kit_template_path=kit_path,
        paper_size=resolved_paper_size,
        qr_config=qr_config,
        qr_payload_encoding=qr_payload_encoding,
    )


def build_qr_config(cfg: dict[str, object] | None = None) -> QrConfig:
    cfg = cfg or {}
    return QrConfig(
        error=str(cfg.get("error", "Q")),
        scale=_parse_int(cfg.get("scale"), default=4),
        border=_parse_int(cfg.get("border"), default=4),
        kind=str(cfg.get("kind", "png")),
        dark=_parse_color(cfg.get("dark")),
        light=_parse_color(cfg.get("light")),
        module_shape=str(cfg.get("module_shape") or "square"),
        version=_parse_optional_int(cfg.get("version")),
        mask=_parse_optional_int(cfg.get("mask")),
        micro=_parse_optional_bool(cfg.get("micro")),
        boost_error=bool(cfg.get("boost_error", True)),
    )


def _load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _resolve_path(base: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = base / path
    if candidate.exists():
        return candidate
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    package_candidate = PACKAGE_ROOT / path
    if package_candidate.exists():
        return package_candidate
    return candidate


def _coerce_path_value(value: object, default: Path) -> str | Path:
    if isinstance(value, (str, Path)):
        return value
    return default


def _get_dict(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _parse_color(value: object) -> str | tuple[int, int, int] | tuple[int, int, int, int] | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in ("none", "transparent"):
            return None
        return value
    if isinstance(value, (list, tuple)):
        if len(value) == 3:
            return (int(value[0]), int(value[1]), int(value[2]))
        if len(value) == 4:
            return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    return None


def _parse_int(value: object, *, default: int) -> int:
    return _parse_number(value, cast=int, default=default)


def _parse_optional_int(value: object) -> int | None:
    return _parse_optional_number(value, cast=int, label="integer")


def _parse_optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def _parse_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return None


def _parse_float(value: object, *, default: float) -> float:
    return _parse_number(value, cast=float, default=default)


def _parse_optional_float(value: object, *, default: float | None = None) -> float | None:
    return _parse_optional_number(value, cast=float, default=default, label="float")


def _parse_number(value: object, *, cast: Callable[[int | float | str], _T], default: _T) -> _T:
    if isinstance(value, (int, float, str)):
        return cast(value)
    return default


def _parse_optional_number(
    value: object,
    *,
    cast: Callable[[int | float | str], _T],
    default: _T | None = None,
    label: str,
) -> _T | None:
    if value is None:
        return default
    if isinstance(value, (int, float, str)):
        return cast(value)
    raise ValueError(f"expected {label} value")
