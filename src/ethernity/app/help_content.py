from __future__ import annotations

from ethernity.app.app_types import ActiveTask
from ethernity.app.screens.help import HelpContent, HelpMode

HELP_MODES: tuple[HelpMode, ...] = (
    HelpMode(
        key="backup",
        label="Create backup",
        description="Make a new printable paper backup from files and folders.",
        use_when="You are starting a new backup set.",
        avoid_when="You already have a backup and only want to add files or reprint it.",
        needs=("Files to back up", "Output folder", "Recovery method"),
    ),
    HelpMode(
        key="restore",
        label="Restore files",
        description="Recover original files from backup papers, scans, or a backup folder.",
        use_when="You need the data back.",
        avoid_when="You only want to print a fresh copy of backup documents.",
        needs=("Backup to restore", "Passphrase or recovery sheets", "Restore destination"),
    ),
    HelpMode(
        key="add_files",
        label="Add files to backup",
        description="Append new files to an existing generated backup folder.",
        use_when="The old backup is valid and you only want to add more data.",
        avoid_when="You want to recreate the same backup without adding new files.",
        needs=("Existing backup", "Files to add", "Passphrase or recovery sheets"),
    ),
    HelpMode(
        key="rebuild",
        label="Rebuild backup",
        description="Create a clean new printable set from an existing backup state.",
        use_when="Papers were lost, layout changed, or you want a fresh printed copy.",
        avoid_when="You want to add new source files to the backup.",
        needs=("Backup folder or scans", "Passphrase or recovery sheets", "Output folder"),
    ),
    HelpMode(
        key="replace_recovery_docs",
        label="Create replacement recovery sheets",
        description="Make a new recovery-sheet set without changing the backed-up files.",
        use_when="Recovery papers are exposed, lost, or need a new threshold/count.",
        avoid_when="You need to restore files or change the backed-up file set.",
        needs=("Newest backup source", "Passphrase or current recovery sheets", "Output folder"),
    ),
    HelpMode(
        key="kit",
        label="Create recovery kit PDF",
        description="Print blank/offline recovery material for collecting backup data later.",
        use_when="You need a paper capture kit before using the full backup flow.",
        avoid_when="You already have files ready and want to create the actual backup.",
        needs=("Kit type", "PDF path", "Paper size and print design"),
    ),
    HelpMode(
        key="doctor",
        label="Setup check",
        description="Check local tools, renderer support, config paths, and runtime health.",
        use_when="Something fails or you want to confirm the machine is ready.",
        avoid_when="You expect it to create, restore, or modify backup documents.",
        needs=("No backup input", "A final review before running checks"),
    ),
    HelpMode(
        key="settings",
        label="Settings",
        description="Change saved defaults for paper size, design, output folders, and limits.",
        use_when="You want future runs to start with different defaults.",
        avoid_when="You only want to change one value for the current workflow.",
        needs=("Setting category", "New default value", "Changes save automatically"),
    ),
)


def build_help_content(*, task: ActiveTask) -> HelpContent:
    mode = next(mode for mode in HELP_MODES if mode.key == task)
    return HelpContent(
        title=f"{mode.label} help",
        intro="What this mode is for.",
        mode=mode,
    )
