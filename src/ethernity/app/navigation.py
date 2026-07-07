from __future__ import annotations

from textual.content import Content
from textual.widgets.option_list import Option

from ethernity.app.app_types import ActiveTask
from ethernity.version import get_ethernity_version


def nav_options() -> tuple[Option, ...]:
    return (
        _nav_header("Backup"),
        _nav_item("1", "Create backup", "backup"),
        _nav_header("Recovery"),
        _nav_item("2", "Restore files", "restore"),
        _nav_header("Maintenance"),
        _nav_item("3", "Add files to backup", "add_files"),
        _nav_item("4", "Rebuild backup", "rebuild"),
        _nav_item("5", "Create replacement recovery sheets", "replace_recovery_docs"),
        _nav_header("Tools"),
        _nav_item("6", "Create recovery kit PDF", "kit"),
        _nav_item("7", "Setup check", "doctor"),
        _nav_item("8", "Settings", "settings"),
    )


def workspace_focus_selector(task: ActiveTask) -> str:
    selectors: dict[ActiveTask, str] = {
        "backup": "#workspace-backup-files",
        "restore": "#workspace-restore-source",
        "add_files": "#workspace-add-files-backup",
        "rebuild": "#workspace-rebuild-source",
        "replace_recovery_docs": "#workspace-replace-source",
        "kit": "#workspace-kit-variant-select",
        "doctor": "#doctor-checks",
        "settings": "#setting-control-render_style",
    }
    return selectors[task]


def blocker_focus_selector(task: ActiveTask, section: str | None) -> str:
    selectors: dict[tuple[ActiveTask, str], str] = {
        ("backup", "files"): "#workspace-backup-files",
        ("backup", "output"): "#workspace-backup-output",
        ("backup", "recovery"): "#workspace-backup-recovery-method",
        ("backup", "advanced"): "#workspace-backup-passphrase",
        ("restore", "source"): "#workspace-restore-source",
        ("restore", "unlock"): "#workspace-restore-unlock",
        ("restore", "target"): "#workspace-restore-target-method",
        ("restore", "output"): "#workspace-restore-output",
        ("add_files", "backup"): "#workspace-add-files-backup",
        ("add_files", "source"): "#workspace-add-files-source",
        ("add_files", "files"): "#workspace-add-files-files",
        ("add_files", "unlock"): "#workspace-add-files-unlock",
        ("add_files", "output"): "#workspace-add-files-backup",
        ("add_files", "advanced"): "#workspace-add-files-base-dir",
        ("rebuild", "source"): "#workspace-rebuild-source",
        ("rebuild", "unlock"): "#workspace-rebuild-unlock",
        ("rebuild", "freshness"): "#workspace-rebuild-freshness",
        ("rebuild", "output"): "#workspace-rebuild-output",
        ("rebuild", "layout"): "#workspace-rebuild-paper",
        ("rebuild", "advanced"): "#rebuild-advanced-toggle",
        ("replace_recovery_docs", "source"): "#workspace-replace-source",
        ("replace_recovery_docs", "unlock"): "#workspace-replace-unlock",
        ("replace_recovery_docs", "freshness"): "#workspace-replace-freshness",
        ("replace_recovery_docs", "output"): "#workspace-replace-output",
        ("replace_recovery_docs", "recovery"): "#workspace-replace-recovery-method",
        ("replace_recovery_docs", "signature"): "#workspace-replace-signing-key-select",
        ("kit", "output"): "#workspace-kit-output",
        ("kit", "layout"): "#workspace-kit-paper",
        ("kit", "variant"): "#workspace-kit-variant-select",
        ("doctor", "checks"): "#doctor-checks",
    }
    if section is not None and (task, section) in selectors:
        return selectors[(task, section)]
    return workspace_focus_selector(task)


def app_version_label() -> str:
    version = get_ethernity_version()
    return f"v{version}" if version else "dev"


def _nav_header(label: str) -> Option:
    return Option(
        Content.assemble(" ", (label.upper(), "$text-primary bold")),
        disabled=True,
    )


def _nav_item(number: str, label: str, option_id: ActiveTask) -> Option:
    return Option(
        Content.assemble(" ", (number, "$text-warning bold"), "  ", label),
        id=option_id,
    )
