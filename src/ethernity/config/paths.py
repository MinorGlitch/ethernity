"""Config path and packaged resource resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity import resources as resources_pkg
from ethernity.core.app_paths import (
    DEFAULT_CONFIG_FILENAME,
    user_config_dir_path,
    user_config_file_path,
    user_templates_design_path,
    user_templates_root_path,
)


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

DEFAULT_TEMPLATE_PATH = TEMPLATES_RESOURCE_ROOT / "sentinel" / "main_document.html.j2"
DEFAULT_RECOVERY_TEMPLATE_PATH = TEMPLATES_RESOURCE_ROOT / "sentinel" / "recovery_document.html.j2"
DEFAULT_SHARD_TEMPLATE_PATH = TEMPLATES_RESOURCE_ROOT / "sentinel" / "shard_document.html.j2"
DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH = (
    TEMPLATES_RESOURCE_ROOT / "sentinel" / "signing_key_shard_document.html.j2"
)
DEFAULT_KIT_TEMPLATE_PATH = TEMPLATES_RESOURCE_ROOT / "sentinel" / "kit_document.html.j2"
DEFAULT_TEMPLATE_STYLE = DEFAULT_TEMPLATE_PATH.parent.name
SUPPORTED_TEMPLATE_DESIGNS = (
    "archive",
    "forge",
    "ledger",
    "maritime",
    "sentinel",
)
TEMPLATE_FILENAMES = (
    DEFAULT_TEMPLATE_PATH.name,
    DEFAULT_RECOVERY_TEMPLATE_PATH.name,
    DEFAULT_SHARD_TEMPLATE_PATH.name,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name,
    DEFAULT_KIT_TEMPLATE_PATH.name,
)
DEFAULT_PAPER_SIZE = "A4"
DEFAULT_CONFIG_PATH = CONFIG_RESOURCE_ROOT / "config.toml"


@dataclass(frozen=True)
class ConfigPaths:
    """Resolved user config and template locations."""

    user_config_dir: Path
    user_templates_root: Path
    user_templates_dir: Path
    user_config_path: Path
    user_template_paths: dict[str, Path]
    user_required_files: tuple[Path, ...]


def build_config_paths() -> ConfigPaths:
    """Construct the derived config/template path set."""

    user_config_dir = user_config_dir_path()
    user_templates_root = user_templates_root_path()
    user_templates_dir = user_templates_design_path(DEFAULT_TEMPLATE_STYLE)
    user_config_path = user_config_file_path(DEFAULT_CONFIG_FILENAME)
    user_template_paths = {
        "main": user_templates_dir / DEFAULT_TEMPLATE_PATH.name,
        "recovery": user_templates_dir / DEFAULT_RECOVERY_TEMPLATE_PATH.name,
        "shard": user_templates_dir / DEFAULT_SHARD_TEMPLATE_PATH.name,
        "signing_key_shard": user_templates_dir / DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name,
        "kit": user_templates_dir / DEFAULT_KIT_TEMPLATE_PATH.name,
    }
    user_required_files = tuple([user_config_path, *user_template_paths.values()])
    return ConfigPaths(
        user_config_dir=user_config_dir,
        user_templates_root=user_templates_root,
        user_templates_dir=user_templates_dir,
        user_config_path=user_config_path,
        user_template_paths=user_template_paths,
        user_required_files=user_required_files,
    )
