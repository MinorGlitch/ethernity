"""Config loaders and installers."""

from .installer import (
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    PAPER_CONFIGS,
    init_user_config,
    user_config_needs_init,
)
from .loader import AppConfig, build_qr_config, load_app_config

__all__ = [
    "AppConfig",
    "DEFAULT_PAPER_SIZE",
    "DEFAULT_RECOVERY_TEMPLATE_PATH",
    "DEFAULT_SHARD_TEMPLATE_PATH",
    "DEFAULT_TEMPLATE_PATH",
    "PAPER_CONFIGS",
    "build_qr_config",
    "init_user_config",
    "load_app_config",
    "user_config_needs_init",
]
