"""Config path and packaged resource resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity import resources as resources_pkg
from ethernity.core.app_paths import (
    DEFAULT_CONFIG_FILENAME,
    user_config_dir_path,
    user_config_file_path,
)
from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME


def _resources_root() -> Path:
    resources_file = getattr(resources_pkg, "__file__", None)
    if not isinstance(resources_file, str) or not resources_file:
        raise RuntimeError("unable to resolve ethernity.resources package path")
    return Path(resources_file).resolve().parent


RESOURCES_ROOT = _resources_root()
CONFIG_RESOURCE_ROOT = RESOURCES_ROOT / "config"
CRYPTO_RESOURCE_ROOT = RESOURCES_ROOT / "crypto"
KIT_RESOURCE_ROOT = RESOURCES_ROOT / "kit"
STORAGE_RESOURCE_ROOT = RESOURCES_ROOT / "storage"
TEMPLATES_RESOURCE_ROOT = RESOURCES_ROOT / "templates"

DESIGN_MANIFEST_FILENAME = "design.json"
DESIGN_STYLE_FILENAME = "style.json"
DEFAULT_RENDER_STYLE = "sentinel"
DEFAULT_RENDER_STYLE_PATH = TEMPLATES_RESOURCE_ROOT / DEFAULT_RENDER_STYLE
SUPPORTED_RENDER_STYLES = (
    "archive",
    "forge",
    "ledger",
    "maritime",
    "sentinel",
)
RENDER_STYLE_FILENAMES = (
    DESIGN_MANIFEST_FILENAME,
    DESIGN_STYLE_FILENAME,
)
DEFAULT_PAPER_SIZE = DEFAULT_PAPER_SIZE_NAME
DEFAULT_CONFIG_PATH = CONFIG_RESOURCE_ROOT / "config.toml"


@dataclass(frozen=True)
class ConfigPaths:
    """Resolved user config locations."""

    user_config_dir: Path
    user_config_path: Path
    user_required_files: tuple[Path, ...]


def build_config_paths() -> ConfigPaths:
    """Construct the derived config path set."""

    user_config_dir = user_config_dir_path()
    user_config_path = user_config_file_path(DEFAULT_CONFIG_FILENAME)
    user_required_files = (user_config_path,)
    return ConfigPaths(
        user_config_dir=user_config_dir,
        user_config_path=user_config_path,
        user_required_files=user_required_files,
    )
