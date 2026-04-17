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

from typing import TYPE_CHECKING, Any

from ethernity.crypto import decrypt_bytes as decrypt_bytes, encrypt_bytes_with_passphrase

if TYPE_CHECKING:
    from ethernity.cli.bootstrap.app import app as app
    from ethernity.cli.features.backup.orchestrator import BackupResult as BackupResult
    from ethernity.cli.shared.types import InputFile as InputFile


def main() -> None:
    from ethernity.cli.bootstrap.app import main as app_main

    app_main()


def run_backup(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.backup.orchestrator import run_backup as impl

    return impl(*args, **kwargs)


def run_backup_command(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.backup.orchestrator import run_backup_command as impl

    return impl(*args, **kwargs)


def run_wizard(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.backup.orchestrator import run_wizard as impl

    return impl(*args, **kwargs)


def run_mint_command(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.mint.workflow import run_mint_command as impl

    return impl(*args, **kwargs)


def run_mint_wizard(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.mint.workflow import run_mint_wizard as impl

    return impl(*args, **kwargs)


def run_extend(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.extend.service import run_extend as impl

    return impl(*args, **kwargs)


def run_compact(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.compact.service import run_compact as impl

    return impl(*args, **kwargs)


def run_recover_command(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.recover.orchestrator import run_recover_command as impl

    return impl(*args, **kwargs)


def run_recover_wizard(*args: Any, **kwargs: Any) -> Any:
    from ethernity.cli.features.recover.orchestrator import run_recover_wizard as impl

    return impl(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "app":
        from ethernity.cli.bootstrap.app import app

        return app
    if name == "BackupResult":
        from ethernity.cli.features.backup.orchestrator import BackupResult

        return BackupResult
    if name == "InputFile":
        from ethernity.cli.shared.types import InputFile

        return InputFile
    if name == "AUTH_FALLBACK_LABEL":
        from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL

        return AUTH_FALLBACK_LABEL
    if name == "MAIN_FALLBACK_LABEL":
        from ethernity.cli.shared.constants import MAIN_FALLBACK_LABEL

        return MAIN_FALLBACK_LABEL
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    "run_compact",
    "run_extend",
    "run_mint_command",
    "run_mint_wizard",
    "run_recover_command",
    "run_recover_wizard",
    "run_wizard",
]
