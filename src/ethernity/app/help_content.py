from __future__ import annotations

from dataclasses import replace

from ethernity.app.app_types import ActiveTask
from ethernity.app.screens.help import HelpContent, HelpMode, HelpSection, HelpShortcut
from ethernity.app.workflow_registry import workflow_definition

COMMON_SHORTCUTS = (
    HelpShortcut(("Esc",), "Close"),
    HelpShortcut(("Tab", "Shift+Tab"), "Focus"),
    HelpShortcut(("j", "k"), "Navigate"),
    HelpShortcut(("h", "l"), "Switch pane"),
    HelpShortcut(("Ctrl+R",), "Review"),
    HelpShortcut(("Ctrl+P",), "Actions"),
)
SETTINGS_SHORTCUTS = (
    HelpShortcut(("Esc",), "Close"),
    HelpShortcut(("Tab", "Shift+Tab"), "Focus"),
    HelpShortcut(("j", "k"), "Navigate"),
    HelpShortcut(("h", "l"), "Switch pane"),
    HelpShortcut(("Ctrl+P",), "Actions"),
)


def _section(title: str, body: str, *notes: str) -> HelpSection:
    return HelpSection(title=title, body=body, notes=notes)


HELP_MODES: tuple[HelpMode, ...] = (
    HelpMode(
        key="backup",
        summary="Encrypt files and folders into printable backup documents.",
        sections=(
            _section(
                "Before you start",
                (
                    "Choose at least one file or folder and a recovery method. Set an output "
                    "folder only for a custom location. Leave Base folder automatic unless "
                    "printed paths need a fixed root."
                ),
            ),
            _section(
                "Result",
                (
                    "Without an output folder, Ethernity creates a folder named for the backup ID "
                    "in the current folder. Review shows the inputs, destination, and whether "
                    "files at that destination may be replaced."
                ),
                "Recommended recovery creates three sheets; any two can restore.",
            ),
            _section(
                "Protect the set",
                (
                    "Store recovery sheets in separate places. Treat a single recovery phrase "
                    "like a password."
                ),
                "Scan at least one printed QR code before relying on the set.",
                (
                    "Higher QR density may reduce page count, but it can make scanning less "
                    "reliable."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="restore",
        summary=(
            "Recover files from a backup folder, scanned pages, recovery text, or exported "
            "backup payloads."
        ),
        sections=(
            _section(
                "Before you start",
                (
                    "Load the backup documents, choose a passphrase, recovery sheets, or recovery "
                    "payload files to unlock it, then choose a destination."
                ),
            ),
            _section(
                "Result",
                (
                    "Ethernity writes recovered files to the destination and creates the folder "
                    "when needed. Use an empty folder to avoid file conflicts."
                ),
            ),
            _section(
                "Trust and version",
                (
                    "Latest means the newest valid update in the documents you loaded. Ethernity "
                    "cannot check for newer copies elsewhere."
                ),
                (
                    "For mixed-version scans, enter the fingerprint printed on the version you "
                    "trust as latest."
                ),
                (
                    "Keep signature verification on unless you are restoring legacy unsigned "
                    "backups. Treat recovery sheets and recovery payload files as secrets. "
                    "If unlocking exceeds the normal work limit, the result shows estimated memory "
                    "and offers Retry with higher limits for that attempt."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="add_files",
        summary="Add or replace paths in an existing backup by creating an update.",
        sections=(
            _section(
                "Before you start",
                (
                    "Load backup documents from PDFs, scans, images, recovery text, or exported "
                    "payloads. Unlock the backup and choose the files or folders to add."
                ),
            ),
            _section(
                "Result",
                ("Ethernity writes two update documents to a separate output folder."),
                (
                    "A selected path replaces the current content at that path. Omitted paths "
                    "remain unchanged."
                ),
                (
                    "Optional new recovery sheets are created by Replace Recovery Docs after the "
                    "update is created and saved separately. They unlock the original backup "
                    "and any available update."
                ),
            ),
            _section(
                "Limits and trust",
                (
                    "Add Files cannot delete or rename paths. To do either, restore the files you "
                    "want, create a new backup, and retire the old backup set. An update must "
                    "leave the complete current contents small enough to Rebuild."
                ),
                (
                    "Check a trusted latest fingerprint, or explicitly accept the newest loaded "
                    "version. Updates started separately from the same version create conflicting "
                    "histories that Ethernity cannot merge."
                ),
                (
                    "The original backup documents plus a passphrase or enough recovery sheets "
                    "authorizes an update. Signing-key sheets recover the signing key; they are "
                    "not another approval."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="rebuild",
        summary="Turn a backup history into a fresh standalone set of printable documents.",
        sections=(
            _section(
                "Before you start",
                (
                    "Load a backup folder or scanned pages, choose an unlock method, and select an "
                    "output folder. Confirm you loaded the latest version or enter the fingerprint "
                    "printed on the version you trust as latest."
                ),
            ),
            _section(
                "Result",
                (
                    "Ethernity writes a standalone backup set to the output folder and leaves the "
                    "source untouched. Rebuild does not add or remove backed-up files."
                ),
                (
                    "The rebuilt set gets new recovery sheets. It keeps "
                    "the passphrase and any embedded signing key. Sealed backups receive a new "
                    "signing key."
                ),
                "Verify the rebuilt backup and sheets before retiring the original documents.",
            ),
            _section(
                "Credentials and source",
                ("Create a new backup when you need a new passphrase or signing key."),
                "Latest means the newest valid update in the documents you loaded.",
                (
                    "Higher QR density may reduce page count, but it can make scanning less "
                    "reliable."
                ),
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
                    "Load backup documents, unlock it with a passphrase, current recovery sheets, "
                    "or recovery payload files, then choose an output folder. For scans, confirm "
                    "you loaded the latest version or enter the fingerprint printed on the version "
                    "you trust as latest."
                ),
                (
                    "Load signing-key payload files only when you are replacing signing-key "
                    "recovery sheets."
                ),
            ),
            _section(
                "Result",
                (
                    "Ethernity writes new recovery-sheet PDFs to the output folder. It leaves the "
                    "backup documents and backed-up files unchanged. New sheets unlock the "
                    "original backup and any available update, even if a later update is lost."
                ),
            ),
            _section(
                "Retire old sheets safely",
                (
                    "Print and verify the new sheets before retiring the old set. Old sheets "
                    "remain sensitive until you destroy or secure them."
                ),
                ("Signing-key sheets recover the signing key; they do not add a second approval."),
                (
                    "Replacement documents remain signed even without separate signing-key "
                    "recovery sheets."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="kit",
        summary="Create a printable PDF that carries Ethernity's offline recovery tools.",
        sections=(
            _section(
                "Choose the PDF",
                (
                    "Choose a file path, paper size, and print design. Lean uses fewer pages and "
                    "manual QR entry; Scanner includes camera scanning."
                ),
            ),
            _section(
                "Result",
                (
                    "Ethernity writes one PDF containing offline restore tools. The PDF is not a "
                    "backup and does not replace backup documents or recovery sheets."
                ),
            ),
            _section(
                "Print and scan",
                "Print at actual size on the paper size selected in the workflow.",
                (
                    "Use automatic QR density unless you have tested a custom value. Custom "
                    "density changes page count and scanning reliability."
                ),
            ),
        ),
        shortcuts=COMMON_SHORTCUTS,
    ),
    HelpMode(
        key="settings",
        summary="Set defaults for future workflows. Changes save immediately.",
        sections=(
            _section(
                "Saved defaults",
                (
                    "Workflows can override a saved default without changing the value in the "
                    "settings file."
                ),
                (
                    "Reset section restores defaults in the current category. "
                    "Reset all settings restores every saved default."
                ),
            ),
            _section(
                "Path defaults",
                (
                    "With automatic backup output, Create backup uses a folder named for the "
                    "backup ID. Leave the input base folder automatic unless printed paths need a "
                    "fixed root."
                ),
            ),
            _section(
                "Risky defaults",
                (
                    "Update chunk sizes must match the existing backup chain. A mismatch can "
                    "prevent Ethernity from applying the update."
                ),
                (
                    "Higher QR density may reduce page count, but it can make scanning less "
                    "reliable."
                ),
                "Use raw QR encoding unless a scanner requires Base64.",
            ),
        ),
        shortcuts=SETTINGS_SHORTCUTS,
    ),
)


def build_help_content(*, task: ActiveTask) -> HelpContent:
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
                    "the form; inside lists and radio groups they move between choices.",
                    "Enter or Space opens a dropdown. Up/Down highlights an option; Enter "
                    "applies it. Escape cancels. Tab or Shift+Tab closes it and moves to the "
                    "next or previous control without changing its value.",
                    "While typing in a text field or searching an open dropdown, letters "
                    "stay in that control. Ctrl+B returns to the top navigation.",
                ),
            ),
        ),
    )
