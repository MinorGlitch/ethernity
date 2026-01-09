#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from ..api import console
from .recover_flow import run_recover_command


def run_recover_wizard(args: argparse.Namespace) -> int:
    quiet = bool(getattr(args, "quiet", False))
    if not quiet:
        console.print("[title]Ethernity recovery wizard[/title]")
        console.print("[subtitle]Interactive recovery of backup documents.[/subtitle]")
    return run_recover_command(args)


def _should_use_wizard_for_recover(args: argparse.Namespace) -> bool:
    if args.fallback_file or args.frames_file or args.scan:
        return False
    if getattr(args, "shard_fallback_file", []) or getattr(args, "shard_frames_file", []):
        return False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return True
