"""Reusable controls and presentation updates for task workspaces."""

from __future__ import annotations

from collections.abc import Iterable

from textual.containers import VerticalGroup
from textual.widget import Widget
from textual.widgets import (
    Button,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from ethernity.app.widgets.form import FormRow, FormSection, FormSelect
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    KeyedRadioSet,
    WorkspaceActionGroup,
)
from ethernity.app.widgets.workflow.steps import WorkflowStep
from ethernity.crypto.passphrases import MNEMONIC_WORD_COUNTS
from ethernity.page_sizes import (
    is_registered_paper_size,
    paper_size_display_name,
    paper_size_names,
)
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    InlineNoticePresentation,
    TaskPresentation,
    WorkspaceAction,
    WorkspaceGroup,
)
from ethernity.tasks.presentation.presentation_values import status_label

QR_DENSITY_HELP = (
    "Higher QR density saves pages but can make codes harder to scan. "
    "Leave blank to use the default."
)

DESIGN_OPTIONS = ("archive", "forge", "ledger", "maritime", "sentinel")
PAPER_OPTIONS = paper_size_names()
KIT_VARIANTS = ("lean", "scanner")
BACKUP_PASSPHRASE_WORD_OPTIONS = (
    ("From settings", "default"),
    *((f"{count} words", str(count)) for count in MNEMONIC_WORD_COUNTS),
)
BACKUP_SIGNING_KEY_OPTIONS = (
    ("Embedded in backup", "embedded"),
    ("Separate key sheets", "sharded"),
)
SIGNING_KEY_RECOVERY_OPTIONS = (
    ("No separate key sheets", "off"),
    ("Match recovery-sheet quorum", "same"),
    ("Custom quorum", "custom"),
    ("Replace existing key sheets", "replace"),
)
PASSPHRASE_RECOVERY_OPTIONS = (
    ("Create new", "create"),
    ("Replace existing", "replace"),
    ("Skip", "off"),
)
RESTORE_AUTH_OPTIONS = (
    ("Trusted signatures required", "require-signed"),
    ("Allow unsigned legacy backups", "allow-unsigned"),
)
SIGNATURE_SOURCE_OPTIONS = (
    ("Loaded backup", "auto"),
    ("Signature text file", "text"),
    ("Signature payload file", "payloads"),
)


class BaseWorkspace(Widget):
    task_key = ""
    step_sections: dict[str, tuple[str, ...]] = {}

    def update_presentation(self, presentation: TaskPresentation) -> None:
        return

    def sync_values(self, source: WorkspaceGroup, bindings: dict[str, str]) -> None:
        for key, selector in bindings.items():
            update_static_text(self.query_one(selector, Static), value(source, key))

    def sync_selects(self, source: WorkspaceGroup, bindings: dict[str, str]) -> None:
        for key, selector in bindings.items():
            set_select(self.query_one(selector, Select), control_value(source, key))

    def show_step(self, key: str) -> None:
        """Select form sections without changing task values or validation."""
        visible = self.step_sections.get(key, ())
        for section_id in {item for items in self.step_sections.values() for item in items}:
            self.query_one(f"#{section_id}").display = section_id in visible
        first = True
        for section_widget in self.query(FormSection):
            if section_widget.display and all(
                parent.display for parent in section_widget.ancestors
            ):
                section_widget.set_class(first, "first-section")
                first = False

    def step_for_target(self, selector: str) -> str | None:
        target = self.query_one(selector)
        for key, section_ids in self.step_sections.items():
            for section_id in section_ids:
                section_widget = self.query_one(f"#{section_id}")
                if target is section_widget or section_widget in target.ancestors:
                    return key
        return next(
            (parent.step_key for parent in target.ancestors if isinstance(parent, WorkflowStep)),
            None,
        )


class WorkspacePathList(OptionList):
    """Read-only path list without selection controls."""

    _workspace_items: tuple[tuple[str, str, str], ...] = ()

    def action_select(self) -> None:
        return


def status_note(note_id: str) -> Widget:
    return Static(
        "",
        id=note_id,
        classes="workspace-section-status workspace-status-ready",
        markup=False,
    )


def path_selection_list(list_id: str) -> Widget:
    return VerticalGroup(
        WorkspacePathList(
            id=list_id,
            classes="workspace-path-selection-list",
            markup=False,
            compact=True,
        ),
        Static(
            "",
            id=f"{list_id}-empty",
            classes="workspace-empty-state",
            markup=False,
        ),
        classes="workspace-path-list",
    )


def button_row(*actions: WorkspaceAction) -> Widget:
    return WorkspaceActionGroup(actions)


def choice_group(prefix: str, choices: Iterable[tuple[str, str]]) -> KeyedRadioSet:
    return KeyedRadioSet(
        tuple(ChoicePresentation(key, label) for key, label in choices),
        id=f"{prefix}-method",
        classes="workspace-choice-set workspace-control",
        button_id_prefix=prefix,
        empty_classes="workspace-choice-empty",
        routes_to_app=True,
    )


def field_row(
    label: str,
    value_id: str,
    action: WorkspaceAction,
    *,
    row_id: str | None = None,
    tooltip: str | None = None,
) -> Widget:
    return FormRow(
        label,
        Static("", id=value_id, classes="field-text form-value", markup=False),
        Button(
            "Change...", id=action.key, classes="workspace-control", tooltip=tooltip or action.label
        ),
        id=row_id,
    )


def select_row(
    label: str,
    select_id: str,
    options: Iterable[str],
    *,
    row_id: str | None = None,
) -> Widget:
    return FormRow(
        label,
        FormSelect(
            [(_enum_display_label(option), option) for option in options],
            id=select_id,
            allow_blank=False,
            classes="workspace-control",
        ),
        id=row_id,
    )


def _enum_display_label(value: str) -> str:
    """Turn stable enum keys into labels without changing their submitted values."""
    if is_registered_paper_size(value):
        return paper_size_display_name(value)
    return value.replace("_", " ").replace("-", " ").title()


def labeled_select_row(
    label: str,
    select_id: str,
    options: Iterable[tuple[str, str]],
    *,
    row_id: str | None = None,
    allow_blank: bool = False,
    tooltip: str | None = None,
) -> Widget:
    return FormRow(
        label,
        FormSelect(
            list(options),
            id=select_id,
            allow_blank=allow_blank,
            classes="workspace-control",
            tooltip=tooltip,
        ),
        id=row_id,
    )


def group(presentation: TaskPresentation, key: str) -> WorkspaceGroup:
    return next(group for group in presentation.workspace_groups if group.key == key)


def first_value(group: WorkspaceGroup) -> str:
    return group.values[0].value if group.values else group.empty_label


def value(group: WorkspaceGroup, key: str) -> str:
    item_value = next((item.value for item in group.values if item.key == key), "")
    return item_value or group.empty_label


def control_value(group: WorkspaceGroup, key: str) -> str:
    """Return the machine-readable value for a workspace control."""
    item = next((item for item in group.values if item.key == key), None)
    if item is None:
        return ""
    return item.control_value if item.control_value is not None else item.value


def update_path_selection_list(path_list: WorkspacePathList, group: WorkspaceGroup) -> None:
    empty = _empty_state_for_path_list(path_list)
    if not group.values:
        path_list.display = False
        if path_list._workspace_items:
            path_list.clear_options()
            path_list._workspace_items = ()
        if empty is not None:
            empty.display = bool(group.empty_label)
            if group.empty_label:
                empty.update(group.empty_label)
        return
    path_list.display = True
    if empty is not None:
        empty.display = False
    items = tuple((item.key, item.label, item.value) for item in group.values)
    if path_list._workspace_items == items:
        return
    path_list.set_options(
        [Option(f"{item.label}: {item.value}", id=item.key) for item in group.values]
    )
    path_list._workspace_items = items


def update_choice_list(
    widget: Widget,
    prefix: str,
    choices: tuple[ChoicePresentation, ...],
) -> None:
    widget.query_one(f"#{prefix}-method", KeyedRadioSet).sync_choices(choices)


def selected_choice(choices: tuple[ChoicePresentation, ...]) -> str:
    for choice in choices:
        if choice.selected:
            return choice.key
    return ""


def set_select(select: Select, value: str) -> None:
    with select.prevent(Select.Changed):
        if value:
            select.value = value
        else:
            select.clear()


def update_buttons(widget: Widget, actions: tuple[WorkspaceAction, ...]) -> None:
    for action in actions:
        button = widget.query_one(f"#{action.key}", Button)
        button.display = action.visible
        button.disabled = not action.enabled


def update_status_note(widget: Widget, note_id: str, group: WorkspaceGroup) -> None:
    note = widget.query_one(f"#{note_id}", Static)
    update_static_text(note, _status_note_text(group))
    for status in ("ready", "missing", "optional", "warning", "blocked"):
        note.set_class(group.status == status, f"workspace-status-{status}")


def update_issue_note(
    widget: Widget, note_id: str, presentation: TaskPresentation, *codes: str
) -> None:
    """Place existing validation messages beside the fields they describe."""
    issues = tuple(
        issue
        for issue in (*presentation.summary.blockers, *presentation.summary.warnings)
        if issue.code in codes
    )
    notice = (
        InlineNoticePresentation(
            " ".join(issue.message for issue in issues),
            tone="error" if any(issue.severity == "error" for issue in issues) else "warning",
        )
        if issues
        else None
    )
    widget.query_one(f"#{note_id}", InlineNotice).sync_presentation(notice)


def _status_note_text(group: WorkspaceGroup) -> str:
    label = status_label(group.status)
    summary = group.status_summary or group.empty_label
    if group.status == "ready":
        return summary if group.kind in {"paths", "checklist"} else ""
    if group.status == "optional":
        return summary if group.kind in {"paths", "checklist"} else "Optional"
    return f"{label}: {summary}" if summary else label


def _empty_state_for_path_list(path_list: WorkspacePathList) -> Static | None:
    if path_list.id is None or path_list.parent is None:
        return None
    try:
        return path_list.parent.query_one(f"#{path_list.id}-empty", Static)
    except Exception:
        return None
