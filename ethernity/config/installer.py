#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import shutil

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
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


def init_user_config() -> Path:
    if not _ensure_user_config():
        raise OSError(f"unable to create config dir at {USER_CONFIG_DIR}")
    return USER_CONFIG_DIR


def user_config_needs_init() -> bool:
    return any(not path.exists() for path in USER_REQUIRED_FILES)


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
