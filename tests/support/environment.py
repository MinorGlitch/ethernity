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

import os
from pathlib import Path

__all__ = ["home_environment"]


def home_environment(home: Path) -> dict[str, str]:
    """Build cross-platform home-directory environment overrides for a test."""
    environment = {"HOME": str(home), "USERPROFILE": str(home)}
    drive, tail = os.path.splitdrive(str(home))
    if drive:
        environment["HOMEDRIVE"] = drive
        environment["HOMEPATH"] = tail or "\\"
    return environment
