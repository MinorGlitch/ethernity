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

from ethernity.extensions import chain
from ethernity.extensions.build import VerifiedExtensionCandidate, build_extension
from ethernity.extensions.chain import (
    AuthenticatedExtensionChainLink as AuthenticatedExtensionChainLink,
    ExtensionReplayError as ExtensionReplayError,
    ReconstructedFile as ReconstructedFile,
    ValidatedChainState as ValidatedChainState,
    replay_authenticated_chain as replay_authenticated_chain,
)

__all__ = [
    *(name for name in chain.__all__ if name != "extract_root_files"),
    "VerifiedExtensionCandidate",
    "build_extension",
]
