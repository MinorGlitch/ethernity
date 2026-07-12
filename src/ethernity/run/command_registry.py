from __future__ import annotations

from click import Command

from ethernity.run.commands.add_files import add_files
from ethernity.run.commands.backup import backup
from ethernity.run.commands.kit import print_kit
from ethernity.run.commands.rebuild import rebuild
from ethernity.run.commands.replace_recovery_docs import replace_recovery_docs
from ethernity.run.commands.restore import restore

RUN_COMMANDS: tuple[Command, ...] = (
    backup,
    restore,
    add_files,
    rebuild,
    replace_recovery_docs,
    print_kit,
)
