#!/usr/bin/env python3
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

from __future__ import annotations

from ..crypto import (
    decrypt_bytes as decrypt_bytes,
    encrypt_bytes_with_passphrase as encrypt_bytes_with_passphrase,
)
from .app import app as app, main as main
from .constants import (
    AUTH_FALLBACK_LABEL as AUTH_FALLBACK_LABEL,
    MAIN_FALLBACK_LABEL as MAIN_FALLBACK_LABEL,
)
from .core.types import InputFile as InputFile
from .flows.backup import (
    BackupResult as BackupResult,
    run_backup as run_backup,
    run_backup_command as run_backup_command,
    run_wizard as run_wizard,
)
from .flows.recover import (
    run_recover_command as run_recover_command,
    run_recover_wizard as run_recover_wizard,
)

__all__ = [
    "AUTH_FALLBACK_LABEL",
    "BackupResult",
    "InputFile",
    "MAIN_FALLBACK_LABEL",
    "app",
    "decrypt_bytes",
    "encrypt_bytes_with_passphrase",
    "main",
    "run_backup",
    "run_backup_command",
    "run_recover_command",
    "run_recover_wizard",
    "run_wizard",
]
