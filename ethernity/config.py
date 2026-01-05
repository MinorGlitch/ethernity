#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar
import os
import shutil
import tomllib

from .qr_codec import QrConfig
from .qr_payloads import normalize_qr_payload_encoding

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_PATH = PACKAGE_ROOT / "templates/main_document.toml.j2"
DEFAULT_RECOVERY_TEMPLATE_PATH = PACKAGE_ROOT / "templates/recovery_document.toml.j2"
DEFAULT_SHARD_TEMPLATE_PATH = PACKAGE_ROOT / "templates/shard_document.toml.j2"
PAPER_CONFIGS = {
    "A4": PACKAGE_ROOT / "config/a4.toml",
    "LETTER": PACKAGE_ROOT / "config/letter.toml",
}
DEFAULT_PAPER_SIZE = "A4"
DEFAULT_CONFIG_PATH = PAPER_CONFIGS[DEFAULT_PAPER_SIZE]
PAPER_SIZE_ENV = "ETHERNITY_PAPER_SIZE"
XDG_CONFIG_ENV = "XDG_CONFIG_HOME"
_XDG_CONFIG_BASE = (
    Path(os.environ[XDG_CONFIG_ENV])
    if os.environ.get(XDG_CONFIG_ENV)
    else Path.home() / ".config"
)
USER_CONFIG_DIR = _XDG_CONFIG_BASE / "ethernity"
USER_TEMPLATES_DIR = USER_CONFIG_DIR / "templates"
USER_PAPER_CONFIGS = {key: USER_CONFIG_DIR / path.name for key, path in PAPER_CONFIGS.items()}
USER_TEMPLATE_PATHS = {
    "main": USER_TEMPLATES_DIR / DEFAULT_TEMPLATE_PATH.name,
    "recovery": USER_TEMPLATES_DIR / DEFAULT_RECOVERY_TEMPLATE_PATH.name,
    "shard": USER_TEMPLATES_DIR / DEFAULT_SHARD_TEMPLATE_PATH.name,
}
USER_REQUIRED_FILES = [*USER_PAPER_CONFIGS.values(), *USER_TEMPLATE_PATHS.values()]
_T = TypeVar("_T")


@dataclass(frozen=True)
class AppConfig:
    template_path: Path
    recovery_template_path: Path
    shard_template_path: Path
    context: dict[str, object]
    qr_config: QrConfig
    qr_payload_encoding: str
    compression: "CompressionConfig"


@dataclass(frozen=True)
class CompressionConfig:
    enabled: bool
    algorithm: str
    level: int


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

    context = _get_dict(data, "context")
    qr_section = _get_dict(data, "qr")
    qr_config = build_qr_config(qr_section)
    qr_payload_encoding = normalize_qr_payload_encoding(
        _parse_optional_str(qr_section.get("payload_encoding"))
    )
    compression = build_compression_config(_get_dict(data, "compression"))
    return AppConfig(
        template_path=template_path,
        recovery_template_path=recovery_path,
        shard_template_path=shard_path,
        context=context,
        qr_config=qr_config,
        qr_payload_encoding=qr_payload_encoding,
        compression=compression,
    )


def init_user_config() -> Path:
    if not _ensure_user_config():
        raise OSError(f"unable to create config dir at {USER_CONFIG_DIR}")
    return USER_CONFIG_DIR


def user_config_needs_init() -> bool:
    return any(not path.exists() for path in USER_REQUIRED_FILES)


def build_compression_config(cfg: dict[str, object] | None = None) -> CompressionConfig:
    cfg = cfg or {}
    return CompressionConfig(
        enabled=bool(cfg.get("enabled", False)),
        algorithm=str(cfg.get("algorithm", "zstd")),
        level=_parse_int(cfg.get("level"), default=3),
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


def _resolve_config_path(path: str | Path | None, *, paper_size: str | None) -> Path:
    if path:
        return Path(path)

    use_user_config = _ensure_user_config()
    user_configs = USER_PAPER_CONFIGS if use_user_config else {}

    if paper_size:
        key = paper_size.strip().upper()
        config_path = user_configs.get(key) or PAPER_CONFIGS.get(key)
        if not config_path:
            raise ValueError(f"unknown paper size: {paper_size}")
        return config_path

    env_paper = os.environ.get(PAPER_SIZE_ENV)
    if env_paper:
        key = env_paper.strip().upper()
        config_path = user_configs.get(key) or PAPER_CONFIGS.get(key)
        if not config_path:
            raise ValueError(f"unknown paper size: {env_paper}")
        return config_path

    default_user_config = user_configs.get(DEFAULT_PAPER_SIZE)
    if default_user_config and default_user_config.exists():
        return default_user_config

    return DEFAULT_CONFIG_PATH


def _ensure_user_config() -> bool:
    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        USER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        _copy_if_missing(DEFAULT_TEMPLATE_PATH, USER_TEMPLATE_PATHS["main"])
        _copy_if_missing(DEFAULT_RECOVERY_TEMPLATE_PATH, USER_TEMPLATE_PATHS["recovery"])
        _copy_if_missing(DEFAULT_SHARD_TEMPLATE_PATH, USER_TEMPLATE_PATHS["shard"])
        for key, src in PAPER_CONFIGS.items():
            _copy_if_missing(src, USER_PAPER_CONFIGS[key])
    except OSError:
        return False
    return True


def _copy_if_missing(source: Path, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)


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
