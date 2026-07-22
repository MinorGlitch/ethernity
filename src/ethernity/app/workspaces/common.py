from __future__ import annotations

from collections.abc import Iterable

from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.widget import Widget
from textual.widgets import (
    Button,
    Collapsible,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    Rule,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from ethernity.app.widgets.collapsible import (
    collapsible_panel,
    sync_collapsible_panel,
)
from ethernity.app.widgets.static_text import update_static_text
from ethernity.crypto.passphrases import MNEMONIC_WORD_COUNTS
from ethernity.page_sizes import (
    is_registered_paper_size,
    paper_size_display_name,
    paper_size_names,
)
from ethernity.tasks.presentation.common import status_label
from ethernity.tasks.presentation.models import (
    TaskPresentation,
    WorkspaceAction,
    WorkspaceChoice,
    WorkspaceGroup,
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
RESTORE_RESOURCE_OPTIONS = (
    ("Standard bounded recovery", "bounded"),
    ("Resource-intensive compatibility recovery", "resource-intensive-compatibility"),
)
AUTH_MATERIAL_OPTIONS = (
    ("Loaded backup", "auto"),
    ("Signature text file", "text"),
    ("Signature payload file", "payloads"),
)
ADD_FILES_UNLOCK_POLICY_OPTIONS = (
    ("From settings", "default"),
    ("Self-contained update", "self-contained"),
    ("Reuse original recovery", "reuse-root"),
)
ADD_FILES_RECOVERY_OPTIONS = (
    ("From settings", "default"),
    ("Use original sheets", "original"),
    ("Custom quorum", "custom"),
)
ADD_FILES_SIGNING_KEY_OPTIONS = (
    ("From settings", "default"),
    ("No separate key sheets", "not-stored"),
    ("Separate key sheets", "sharded"),
    ("Custom quorum", "custom"),
)


class BaseWorkspace(Widget):
    task_key = ""
    advanced_panel_id: str | None = None
    _advanced_expanded = False

    def update_presentation(self, presentation: TaskPresentation) -> None:
        return

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible.id == self.advanced_panel_id:
            event.stop()
            self._advanced_expanded = True

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        if event.collapsible.id == self.advanced_panel_id:
            event.stop()
            self._advanced_expanded = False

    def sync_advanced_panel(self, title: str) -> None:
        if self.advanced_panel_id is None:
            return
        sync_collapsible_panel(
            self,
            self.advanced_panel_id,
            expanded=getattr(self, "_advanced_expanded", False),
            title=title,
        )

    def reveal_advanced_focus_target(self, selector: str) -> bool:
        """Expand the advanced panel when it owns the requested focus target."""
        if self.advanced_panel_id is None:
            return False
        try:
            panel = self.query_one(f"#{self.advanced_panel_id}", Collapsible)
            target = self.query_one(selector)
        except Exception:
            return False
        if target is not panel and panel not in target.ancestors:
            return False
        self._advanced_expanded = True
        panel.collapsed = False
        return True


class WorkspacePathList(OptionList):
    """Read-only path list without selection controls."""

    _workspace_items: tuple[tuple[str, str, str], ...] = ()

    def action_select(self) -> None:
        return


class WorkspaceRadioSet(RadioSet):
    """Native single-choice control that retains presentation choice keys."""

    def __init__(
        self,
        prefix: str,
        choices: Iterable[tuple[str, str]],
        *,
        id: str,
        classes: str | None = None,
    ) -> None:
        self._prefix = prefix
        self._empty_button = RadioButton(
            "",
            value=True,
            disabled=True,
            classes="workspace-choice-empty",
        )
        self._buttons = {
            key: RadioButton(
                Content.from_text(label, markup=False),
                id=self._button_id(key),
            )
            for key, label in choices
        }
        super().__init__(
            self._empty_button,
            *self._buttons.values(),
            id=id,
            classes=classes,
            compact=True,
        )

    @property
    def selected_key(self) -> str | None:
        return next((key for key, button in self._buttons.items() if button.value), None)

    def key_for_button(self, button: RadioButton) -> str | None:
        return next((key for key, candidate in self._buttons.items() if candidate is button), None)

    def sync_choices(self, choices: tuple[WorkspaceChoice, ...]) -> None:
        """Synchronize presentation state without emitting a user change message."""
        selected_key = next((choice.key for choice in choices if choice.selected), None)
        if tuple(self._buttons) != tuple(choice.key for choice in choices):
            raise ValueError("radio choice keys cannot change after composition")
        for choice in choices:
            button = self._buttons[choice.key]
            button.label = Content.from_text(choice.label, markup=False)
        target = self._empty_button if selected_key is None else self._buttons[selected_key]
        with self.prevent(RadioSet.Changed):
            target.value = True

    def _button_id(self, choice_key: str) -> str:
        return f"{self._prefix}-{choice_key}"


def advanced_panel(panel_id: str, title: str) -> Collapsible:
    return collapsible_panel(
        panel_id,
        title,
        classes="workspace-advanced-panel workspace-control",
        title_classes="workspace-advanced-panel-title workspace-control",
    )


def group_label(label: str) -> Widget:
    return Label(label, classes="workspace-group-title")


def status_note(note_id: str) -> Widget:
    return Static(
        "",
        id=note_id,
        classes="workspace-section-status workspace-status-ready",
        markup=False,
    )


def section() -> VerticalGroup:
    return VerticalGroup(
        Rule(classes="workspace-section-rule"),
        classes="workspace-section",
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


def button_row(*actions: WorkspaceAction, spaced_after: bool = False) -> Widget:
    row_classes = "workspace-button-row"
    if spaced_after:
        row_classes = f"{row_classes} workspace-button-row-spaced"
    return HorizontalGroup(*_spaced_buttons(actions), classes=row_classes)


def _spaced_buttons(actions: Iterable[WorkspaceAction]) -> list[Widget]:
    widgets: list[Widget] = []
    for index, action in enumerate(actions):
        if index > 0:
            widgets.append(Static("", classes="workspace-button-gap"))
        widgets.append(
            Button(action.label, id=action.key, compact=True, classes="workspace-control")
        )
    return widgets


def choice_group(prefix: str, choices: Iterable[tuple[str, str]]) -> WorkspaceRadioSet:
    return WorkspaceRadioSet(
        prefix,
        choices,
        id=f"{prefix}-method",
        classes="workspace-choice-set workspace-control",
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
        Static("", id=value_id, classes="workspace-field-value", markup=False),
        Static("", classes="action-button-gap"),
        Button(action.label, id=action.key, compact=True, classes="workspace-control"),
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
            [(_enum_display_label(option), option) for option in options],
            id=select_id,
            allow_blank=False,
            compact=True,
            classes="workspace-select workspace-control",
        ),
        id=row_id,
        classes="workspace-field-row workspace-select-row",
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
) -> Widget:
    return HorizontalGroup(
        Label(label, classes="workspace-field-label"),
        Select(
            list(options),
            id=select_id,
            allow_blank=allow_blank,
            compact=True,
            classes="workspace-select workspace-control",
        ),
        id=row_id,
        classes="workspace-field-row workspace-select-row",
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
        Static("", id=value_id, classes="workspace-field-value", markup=False),
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
    choices: tuple[WorkspaceChoice, ...],
) -> None:
    widget.query_one(f"#{prefix}-method", WorkspaceRadioSet).sync_choices(choices)


def selected_choice(choices: tuple[WorkspaceChoice, ...]) -> str:
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
