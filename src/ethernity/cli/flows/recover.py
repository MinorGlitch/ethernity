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

import sys

from ..core.types import RecoverArgs
from .recover_flow import run_recover_plan
from .recover_plan import plan_from_args
from .recover_wizard import run_recover_wizard as _run_recover_wizard


def run_recover_command(args: RecoverArgs, *, debug: bool = False) -> int:
    plan = plan_from_args(args)
    return run_recover_plan(plan, quiet=args.quiet, debug=debug)


def run_recover_wizard(args: RecoverArgs, *, debug: bool = False) -> int:
    return _run_recover_wizard(args, debug=debug)


def _should_use_wizard_for_recover(args: RecoverArgs) -> bool:
    if args.fallback_file or args.payloads_file or args.scan:
        return False
    if args.shard_fallback_file or args.shard_payloads_file:
        return False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return True
