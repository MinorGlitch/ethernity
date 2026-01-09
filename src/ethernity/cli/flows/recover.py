#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from .recover_flow import run_recover_plan
from .recover_plan import plan_from_args
from .recover_wizard import run_recover_wizard as _run_recover_wizard


def run_recover_command(args: argparse.Namespace) -> int:
    plan = plan_from_args(args)
    quiet = bool(getattr(args, "quiet", False))
    return run_recover_plan(plan, quiet=quiet)


def run_recover_wizard(args: argparse.Namespace) -> int:
    return _run_recover_wizard(args)


def _should_use_wizard_for_recover(args: argparse.Namespace) -> bool:
    if args.fallback_file or args.frames_file or args.scan:
        return False
    if getattr(args, "shard_fallback_file", []) or getattr(args, "shard_frames_file", []):
        return False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return True
