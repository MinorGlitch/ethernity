#!/usr/bin/env python3
from __future__ import annotations

import sys

from ..core.types import RecoverArgs
from .recover_flow import run_recover_plan
from .recover_plan import plan_from_args
from .recover_wizard import run_recover_wizard as _run_recover_wizard


def run_recover_command(args: RecoverArgs) -> int:
    plan = plan_from_args(args)
    return run_recover_plan(plan, quiet=args.quiet)


def run_recover_wizard(args: RecoverArgs) -> int:
    return _run_recover_wizard(args)


def _should_use_wizard_for_recover(args: RecoverArgs) -> bool:
    if args.fallback_file or args.payloads_file or args.scan:
        return False
    if args.shard_fallback_file or args.shard_payloads_file:
        return False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return True
