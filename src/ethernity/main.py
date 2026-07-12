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
from collections.abc import Sequence

from ethernity.app.bootstrap import run_app
from ethernity.run.cli import cli as run_cli
from ethernity.version import get_ethernity_version

ROOT_HELP = """Usage: ethernity [run] [OPTIONS] COMMAND [ARGS]...

Launch the Ethernity terminal app when run without arguments.

Commands:
  run      Run scriptable Ethernity tasks.

Examples:
  ethernity
  ethernity run backup --input secrets.txt --output-dir backup-out --preview
  ethernity run restore --scan scans --output recovered --preview
  ethernity run add-files --backup-folder backup-out --input new-file.txt --preview
  ethernity run rebuild --backup-folder backup-out --output-dir rebuilt --preview
  ethernity run replace-recovery-docs --scan scans --passphrase '...' \\
    --allow-stale-head --output-dir replacement-docs --preview
  ethernity run print-kit --output recovery_kit_qr.pdf --preview
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        run_app()
        return 0

    command = args[0]
    if command in {"-h", "--help"}:
        print(ROOT_HELP)
        return 0

    if command == "--version":
        version = get_ethernity_version() or "unknown"
        print(f"ethernity {version}")
        return 0

    if command == "run":
        run_cli.main(args=list(args[1:]), prog_name="ethernity run", standalone_mode=True)
        return 0

    print(f"Error: unknown command '{command}'. Run `ethernity --help`.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
