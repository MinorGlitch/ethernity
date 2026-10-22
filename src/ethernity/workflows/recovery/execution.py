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

"""Recover decrypted files with the selected version and workflow errors."""

from __future__ import annotations

from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import ChainRecoveryResult
from ethernity.workflows.recovery.planning import RecoveryPlan
from ethernity.workflows.recovery.session import RecoverySession
from ethernity.workflows.shared.events import CommandError


def decrypt_manifest_extract_selection(
    plan: RecoveryPlan,
    *,
    debug: bool = False,
    session: RecoverySession | None = None,
) -> ChainRecoveryResult:
    """Decrypt a recovery plan and preserve any explicit replay-target metadata."""

    try:
        return (session or RecoverySession()).recover_chain(plan, debug=debug)
    except ExtensionRecoveryError as exc:
        raise CommandError(code=exc.code, message=str(exc), details=dict(exc.details)) from exc
