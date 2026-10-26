from __future__ import annotations

from dataclasses import replace

from ethernity.app.screens.help import HelpContent, HelpMode, HelpSection, HelpShortcut
from ethernity.app.workflow_registry import workflow_definition
from ethernity.tasks.task_types import TaskKey

COMMON_SHORTCUTS = (
    HelpShortcut(("Esc",), "Close"),
    HelpShortcut(("Tab", "Shift+Tab"), "Focus"),
    HelpShortcut(("j", "k"), "Navigate"),
    HelpShortcut(("h", "l"), "Switch pane"),
    HelpShortcut(("Ctrl+R",), "Review"),
    HelpShortcut(("Ctrl+P",), "Actions"),
    HelpShortcut(("Ctrl+B",), "Navigation"),
    HelpShortcut(("?",), "Help"),
    HelpShortcut(("q",), "Quit"),
)
SETTINGS_SHORTCUTS = (
    HelpShortcut(("Esc",), "Close"),
    HelpShortcut(("Tab", "Shift+Tab"), "Focus"),
    HelpShortcut(("j", "k"), "Navigate"),
    HelpShortcut(("h", "l"), "Switch pane"),
    HelpShortcut(("Ctrl+P",), "Actions"),
    HelpShortcut(("Ctrl+B",), "Navigation"),
    HelpShortcut(("?",), "Help"),
    HelpShortcut(("q",), "Quit"),
)


def _section(title: str, body: str, *notes: str) -> HelpSection:
    return HelpSection(title=title, body=body, notes=notes)


HELP_MODES: tuple[HelpMode, ...] = (
    HelpMode(
        key="backup",
        summary="Encrypt files and print them as a paper backup.",
        sections=(
            _section(
                "Before you start",
                (
                    "Choose files, a recovery method, and a print layout. "
                    "Folders include all their contents."
                ),
            ),
            _section(
                "Result",
                (
                    "Each backup gets a new folder inside the destination. "
                    "If none is selected, it uses the current folder."
                ),
                "Recommended recovery creates three sheets; any two can restore.",
            ),
            _section(
                "Printing and storage",
                (
                    "Keep recovery sheets apart from the backup pages and from each other. "
                    "Keep a single recovery phrase private, like a password."
                ),
                "Test recovery from scans of the printed pages before storing them.",
                ("Higher QR density uses fewer pages but can make codes harder to scan."),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="restore",
        summary=("Recover files from backup PDFs, scans, printed text, or exported data."),
        sections=(
            _section(
                "Before you start",
                (
                    "Load the backup and unlock it with a passphrase or recovery sheets. "
                    "Exported recovery data works too."
                ),
            ),
            _section(
                "Result",
                (
                    "Choose a new or empty folder for the restored files. "
                    "Existing files are never replaced."
                ),
            ),
            _section(
                "Choosing a version",
                (
                    "Newest loaded version uses the latest valid update you supplied. "
                    "Newer updates may exist elsewhere."
                ),
                (
                    "Check against a full fingerprint you saved separately. "
                    "After a backup or update, use Copy fingerprint and save it somewhere safe."
                ),
                (
                    "Allow unsigned backups only for older backups without signatures. "
                    "Keep recovery sheets and exported recovery data private."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="add_files",
        summary="Add or replace files without printing the whole backup again.",
        sections=(
            _section(
                "Before you start",
                ("Load and unlock the backup, then choose the files or folders to add."),
                (
                    "Cumulative updates need the original backup and the selected update. "
                    "Incremental updates also need every earlier update."
                ),
            ),
            _section(
                "Result",
                "Creates an update PDF and recovery guide in a new folder.",
                ("Files with matching backup paths are replaced. Other files stay unchanged."),
                (
                    "Optional new recovery sheets are saved separately. "
                    "They unlock the original backup and any available update."
                ),
            ),
            _section(
                "Limits",
                (
                    "To delete or rename files, restore them and create a new backup. "
                    "The total data after an update must still fit in a rebuilt backup."
                ),
                (
                    "Check a separately saved fingerprint, or accept that newer updates may be "
                    "missing. Separate updates from the same version conflict and cannot be merged."
                ),
                (
                    "Anyone with the original backup and its passphrase or enough recovery sheets "
                    "can create an update. Signing-key sheets do not add another approval step."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="rebuild",
        summary="Combine a backup and its updates into a new paper backup.",
        sections=(
            _section(
                "Before you start",
                (
                    "Load and unlock the backup, then choose a destination. Check a separately "
                    "saved fingerprint, or accept that newer updates may be missing."
                ),
            ),
            _section(
                "Result",
                (
                    "Creates a new backup folder with the same files and new recovery sheets. "
                    "The original documents stay unchanged."
                ),
                (
                    "The passphrase and any embedded signing key stay the same. "
                    "Backups without an embedded signing key get a new one."
                ),
                "Test recovery from the new printed pages before retiring the old ones.",
            ),
            _section(
                "Changing the backup",
                "Create a new backup to choose a new passphrase or signing key.",
                ("Higher QR density uses fewer pages but can make codes harder to scan."),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="replace_recovery_docs",
        summary="Create new recovery sheets without changing the files in the backup.",
        sections=(
            _section(
                "Before you start",
                (
                    "Load and unlock the backup, then choose a new folder. "
                    "For scanned pages, check a separately saved fingerprint or accept "
                    "that newer updates may be missing."
                ),
                ("To replace individual signing-key sheets, load their exported data."),
            ),
            _section(
                "Result",
                (
                    "Creates recovery-sheet PDFs without changing the backup. "
                    "New sheets unlock the original and any available update, "
                    "even if a later update is lost."
                ),
            ),
            _section(
                "Old sheets",
                (
                    "Test the new printed sheets before retiring the old ones. "
                    "Old sheets still work. Destroy them or keep them secure."
                ),
                "Signing-key sheets recover the key; they do not add another approval step.",
                ("Replacement documents are signed even without separate key sheets."),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="kit",
        summary="Print the offline recovery tool so it can be reconstructed later.",
        sections=(
            _section(
                "Kit type",
                (
                    '"Paste text" uses fewer '
                    'pages. "Paste text + scan QR codes" adds camera scanning.'
                ),
            ),
            _section(
                "Result",
                (
                    "Creates one PDF containing the recovery tool. "
                    "You still need your backup documents and passphrase or recovery sheets."
                ),
            ),
            _section(
                "Printing",
                "Print at actual size using the selected paper size.",
                ("Use automatic QR density unless you have tested another value."),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="settings",
        summary="Defaults for new tasks. Changes save immediately.",
        sections=(
            _section(
                "Saved defaults",
                ("You can change these choices for an individual task."),
                (
                    "Reset section restores the current category. "
                    "Reset all settings restores every default."
                ),
            ),
            _section(
                "Path defaults",
                (
                    "Each backup gets its own folder. Base folder sets the starting point "
                    "for stored file paths; Automatic uses the files' common parent folder."
                ),
            ),
            _section(
                "Advanced settings",
                ("Chunk sizes apply to the first update. Later updates keep the same sizes."),
                ("Higher QR density uses fewer pages but can make codes harder to scan."),
                "Use raw QR encoding unless a scanner requires Base64.",
            ),
        ),
        shortcuts=SETTINGS_SHORTCUTS,
    ),
)


def build_help_content(*, task: TaskKey) -> HelpContent:
    mode = next(mode for mode in HELP_MODES if mode.key == task)
    return HelpContent(
        title=workflow_definition(task).title,
        intro=mode.summary,
        mode=replace(
            mode,
            sections=(
                *mode.sections,
                _section(
                    "Keyboard navigation",
                    "Tab and Shift+Tab move between controls. Up/Down or j/k move through "
                    "the form or the choices in a list.",
                    "Enter or Space opens a dropdown. Up/Down highlights an option; Enter "
                    "applies it. Escape or Tab closes it without changing the value.",
                    "Letters type normally in text fields and dropdown search. "
                    "Ctrl+B opens navigation.",
                ),
            ),
        ),
    )
