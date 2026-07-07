from __future__ import annotations

from collections.abc import Iterable

from textual.containers import HorizontalGroup, VerticalGroup
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, RadioButton, RadioSet, Select, Static

from ethernity.crypto.passphrases import MNEMONIC_WORD_COUNTS
from ethernity.tasks.presentation.models import (
    TaskPresentation,
    WorkspaceAction,
    WorkspaceChoice,
    WorkspaceGroup,
)

DESIGN_OPTIONS = ("archive", "forge", "ledger", "maritime", "sentinel")
PAPER_OPTIONS = ("A4", "LETTER")
KIT_VARIANTS = ("lean", "scanner")
BACKUP_PASSPHRASE_WORD_OPTIONS = (
    ("Default: saved setting", "default"),
    *((f"{count} words", str(count)) for count in MNEMONIC_WORD_COUNTS),
)
SIGNING_KEY_RECOVERY_OPTIONS = (
    ("Off - not signed", "off"),
    ("Same quorum", "same"),
    ("Custom quorum", "custom"),
    ("Replace existing", "replace"),
)
PASSPHRASE_RECOVERY_OPTIONS = (
    ("Create new", "create"),
    ("Replace existing", "replace"),
    ("Skip", "off"),
)
RESTORE_AUTH_OPTIONS = (
    ("Require trusted signature", "require-signed"),
    ("Allow unsigned legacy", "allow-unsigned"),
)
AUTH_MATERIAL_OPTIONS = (
    ("From loaded backup", "auto"),
    ("Trust text", "text"),
    ("Trust payload files", "payloads"),
)
ADD_FILES_UNLOCK_POLICY_OPTIONS = (
    ("Self-contained", "self-contained"),
    ("Reuse root", "reuse-root"),
)
ADD_FILES_RECOVERY_OPTIONS = (
    ("Using saved defaults", "default"),
    ("No new sheets", "none"),
    ("Custom quorum", "custom"),
)
ADD_FILES_SIGNING_KEY_OPTIONS = (
    ("Using saved default", "default"),
    ("Not stored", "not-stored"),
    ("Sharded", "sharded"),
    ("Custom key sheets", "custom"),
)


class BaseWorkspace(Widget):
    task_key = ""

    def update_presentation(self, presentation: TaskPresentation) -> None:
        return


def group_label(label: str) -> Widget:
    return Label(label, classes="workspace-group-title")


def status_note(note_id: str) -> Widget:
    return Static(
        "",
        id=note_id,
        classes="workspace-section-status workspace-status-ready",
    )


def section() -> VerticalGroup:
    return VerticalGroup(classes="workspace-section")


def path_table(table_id: str) -> Widget:
    return VerticalGroup(
        DataTable(id=table_id, classes="workspace-table workspace-control"),
        Static("", id=f"{table_id}-empty", classes="workspace-empty-state"),
        classes="workspace-path-list",
    )


def button_row(*actions: WorkspaceAction) -> Widget:
    return HorizontalGroup(
        *[
            Button(action.label, id=action.key, compact=True, classes="workspace-control")
            for action in actions
        ],
        classes="workspace-button-row",
    )


def field_row(
    label: str,
    value_id: str,
    action: WorkspaceAction,
    *,
    row_id: str | None = None,
) -> Widget:
    return HorizontalGroup(
        Label(label, classes="workspace-field-label"),
        Static("", id=value_id, classes="workspace-field-value"),
        Button(action.label, id=action.key, compact=True, classes="workspace-control"),
        id=row_id,
        classes="workspace-field-row",
    )


def value_row(
    label: str,
    value_id: str,
    *,
    row_id: str | None = None,
) -> Widget:
    return HorizontalGroup(
        Label(label, classes="workspace-field-label"),
        Static("", id=value_id, classes="workspace-field-value"),
        id=row_id,
        classes="workspace-field-row",
    )


def select_row(
    label: str,
    select_id: str,
    options: Iterable[str],
    *,
    row_id: str | None = None,
) -> Widget:
    return HorizontalGroup(
        Label(label, classes="workspace-field-label"),
        Select(
            [(option, option) for option in options],
            id=select_id,
            allow_blank=False,
            compact=True,
            classes="workspace-select workspace-control",
        ),
        id=row_id,
        classes="workspace-field-row",
    )


def labeled_select_row(
    label: str,
    select_id: str,
    options: Iterable[tuple[str, str]],
    *,
    row_id: str | None = None,
) -> Widget:
    return HorizontalGroup(
        Label(label, classes="workspace-field-label"),
        Select(
            list(options),
            id=select_id,
            allow_blank=False,
            compact=True,
            classes="workspace-select workspace-control",
        ),
        id=row_id,
        classes="workspace-field-row",
    )


def select_summary_row(
    label: str,
    select_id: str,
    options: Iterable[tuple[str, str]],
    value_id: str,
    *,
    row_id: str | None = None,
) -> Widget:
    return HorizontalGroup(
        Label(label, classes="workspace-field-label"),
        Select(
            list(options),
            id=select_id,
            allow_blank=False,
            compact=True,
            classes="workspace-select workspace-control",
        ),
        Static("", id=value_id, classes="workspace-field-value"),
        id=row_id,
        classes="workspace-field-row",
    )


def group(presentation: TaskPresentation, key: str) -> WorkspaceGroup:
    return next(group for group in presentation.workspace_groups if group.key == key)


def first_value(group: WorkspaceGroup) -> str:
    return group.values[0].value if group.values else group.empty_label


def value(group: WorkspaceGroup, key: str) -> str:
    item_value = next((item.value for item in group.values if item.key == key), "")
    return item_value or group.empty_label


def update_table(table: DataTable, group: WorkspaceGroup) -> None:
    table.clear(columns=True)
    table.cursor_type = "row"
    empty = _empty_state_for_table(table)
    if not group.values:
        table.display = False
        if empty is not None:
            empty.display = True
            empty.update(group.empty_label)
        return
    table.display = True
    if empty is not None:
        empty.display = False
    table.add_columns("Name", "Path")
    for item in group.values:
        table.add_row(item.label, item.value, key=item.key)


def update_radio(widget: Widget, prefix: str, choices: tuple[WorkspaceChoice, ...]) -> None:
    radio = widget.query_one(f"#{prefix}-method", RadioSet)
    with radio.prevent(RadioSet.Changed):
        selected_any = False
        for choice in choices:
            button = widget.query_one(f"#{prefix}-{choice.key}", RadioButton)
            button.value = choice.selected
            selected_any = selected_any or choice.selected
        if not selected_any and choices:
            widget.query_one(f"#{prefix}-{choices[0].key}", RadioButton).value = True


def selected_choice(choices: tuple[WorkspaceChoice, ...]) -> str:
    for choice in choices:
        if choice.selected:
            return choice.key
    return choices[0].key if choices else ""


def add_files_recovery_select_value(summary: str) -> str:
    lowered = summary.lower()
    if lowered.startswith("no "):
        return "none"
    if lowered.startswith("custom") or "recovery sheets; any" in lowered:
        return "custom"
    return "default"


def add_files_signing_key_select_value(summary: str) -> str:
    lowered = summary.lower()
    if lowered.startswith("not stored"):
        return "not-stored"
    if lowered.startswith("sharded,"):
        return "custom"
    if lowered.startswith("sharded"):
        return "sharded"
    return "default"


def auth_material_select_value(summary: str) -> str:
    lowered = summary.lower()
    if lowered.startswith("trust text"):
        return "text"
    if lowered.startswith("trust payload"):
        return "payloads"
    return "auto"


def replace_passphrase_recovery_select_value(summary: str) -> str:
    lowered = summary.lower()
    if lowered.startswith("do not"):
        return "off"
    if lowered.startswith("replace"):
        return "replace"
    return "create"


def set_select(select: Select, value: str) -> None:
    with select.prevent(Select.Changed):
        select.value = value


def update_buttons(widget: Widget, actions: tuple[WorkspaceAction, ...]) -> None:
    for action in actions:
        button = widget.query_one(f"#{action.key}", Button)
        button.disabled = not action.enabled


def update_status_note(widget: Widget, note_id: str, group: WorkspaceGroup) -> None:
    note = widget.query_one(f"#{note_id}", Static)
    summary = group.status_summary or group.empty_label
    note.update(
        f"{status_label(group.status)}: {summary}" if summary else status_label(group.status)
    )
    for status in ("ready", "missing", "warning", "blocked"):
        note.set_class(group.status == status, f"workspace-status-{status}")


def status_label(status: str) -> str:
    if status == "ready":
        return "Complete"
    if status == "warning":
        return "Warning"
    if status == "blocked":
        return "Invalid"
    return "Required"


def _empty_state_for_table(table: DataTable) -> Static | None:
    if table.id is None or table.parent is None:
        return None
    try:
        return table.parent.query_one(f"#{table.id}-empty", Static)
    except Exception:
        return None
