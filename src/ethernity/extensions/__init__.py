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

"""Public API for building and replaying authenticated extensions."""

from ethernity.extensions.build import VerifiedExtensionCandidate, build_extension
from ethernity.extensions.chain import (
    AuthenticatedExtensionChainLink,
    ExtensionReplayError,
    ReconstructedFile,
    ValidatedChainState,
    replay_authenticated_chain,
)

__all__ = [
    "AuthenticatedExtensionChainLink",
    "ExtensionReplayError",
    "ReconstructedFile",
    "ValidatedChainState",
    "VerifiedExtensionCandidate",
    "build_extension",
    "replay_authenticated_chain",
]
