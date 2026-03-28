# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Config loaders, path resolution, and installer helpers."""

from ethernity.config.api_patch import (
    ApiConfigSnapshot,
    ConfigPatchError,
    apply_api_config_patch,
    get_api_config_snapshot,
)
from ethernity.config.install import (
    ONBOARDING_FIELD_BACKUP_OUTPUT_DIR,
    ONBOARDING_FIELD_PAGE_SIZE,
    ONBOARDING_FIELD_PAYLOAD_CODEC,
    ONBOARDING_FIELD_QR_CHUNK_SIZE,
    ONBOARDING_FIELD_QR_ERROR_CORRECTION,
    ONBOARDING_FIELD_QR_PAYLOAD_CODEC,
    ONBOARDING_FIELD_SHARDING,
    ONBOARDING_FIELD_TEMPLATE_DESIGN,
    ONBOARDING_FIELDS,
    apply_first_run_defaults,
    clear_first_run_onboarding_marker,
    first_run_onboarding_configured_fields,
    first_run_onboarding_marker_path,
    first_run_onboarding_needed,
    init_user_config,
    list_template_designs,
    mark_first_run_onboarding_complete,
    resolve_api_defaults_config_path,
    resolve_config_path,
    resolve_config_snapshot_path,
    resolve_template_design_path,
    resolve_writable_config_path,
    user_config_needs_init,
)
from ethernity.config.load import (
    apply_template_design,
    build_qr_config,
    load_app_config,
    load_cli_defaults,
)
from ethernity.config.paths import (
    DEFAULT_KIT_TEMPLATE_PATH,
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_STYLE,
)
from ethernity.config.types import (
    AppConfig,
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    PageSize,
    PayloadCodec,
    QrErrorCorrection,
    QrPayloadCodec,
    RecoverDefaults,
    RuntimeDefaults,
    SigningKeyMode,
    UiDefaults,
)

__all__ = [
    "AppConfig",
    "ApiConfigSnapshot",
    "BackupDefaults",
    "CliDefaults",
    "ConfigPatchError",
    "DebugDefaults",
    "PageSize",
    "PayloadCodec",
    "QrErrorCorrection",
    "QrPayloadCodec",
    "RecoverDefaults",
    "RuntimeDefaults",
    "SigningKeyMode",
    "UiDefaults",
    "DEFAULT_KIT_TEMPLATE_PATH",
    "DEFAULT_PAPER_SIZE",
    "DEFAULT_RECOVERY_TEMPLATE_PATH",
    "DEFAULT_SHARD_TEMPLATE_PATH",
    "DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH",
    "DEFAULT_TEMPLATE_PATH",
    "DEFAULT_TEMPLATE_STYLE",
    "resolve_api_defaults_config_path",
    "resolve_config_snapshot_path",
    "resolve_config_path",
    "resolve_template_design_path",
    "resolve_writable_config_path",
    "ONBOARDING_FIELDS",
    "ONBOARDING_FIELD_BACKUP_OUTPUT_DIR",
    "ONBOARDING_FIELD_PAGE_SIZE",
    "ONBOARDING_FIELD_PAYLOAD_CODEC",
    "ONBOARDING_FIELD_QR_CHUNK_SIZE",
    "ONBOARDING_FIELD_QR_ERROR_CORRECTION",
    "ONBOARDING_FIELD_QR_PAYLOAD_CODEC",
    "ONBOARDING_FIELD_SHARDING",
    "ONBOARDING_FIELD_TEMPLATE_DESIGN",
    "apply_first_run_defaults",
    "clear_first_run_onboarding_marker",
    "first_run_onboarding_configured_fields",
    "first_run_onboarding_marker_path",
    "first_run_onboarding_needed",
    "init_user_config",
    "list_template_designs",
    "mark_first_run_onboarding_complete",
    "user_config_needs_init",
    "apply_api_config_patch",
    "apply_template_design",
    "build_qr_config",
    "get_api_config_snapshot",
    "load_app_config",
    "load_cli_defaults",
]
