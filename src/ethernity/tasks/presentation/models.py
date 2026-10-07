from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from ethernity.crypto.sharding import MAX_SHARES
from ethernity.tasks.models import TaskIssue
from ethernity.tasks.source_types import SourceDescription
from ethernity.tasks.task_types import TaskKey

StepState = Literal["available", "current", "complete"]
StepSeverity = Literal["none", "warning", "error"]
NoticeTone = Literal["info", "warning", "error", "success"]


@dataclass(frozen=True)
class WorkspaceAction:
    key: str
    label: str
    enabled: bool = True
    visible: bool = True
    requires_selection: bool = False


@dataclass(frozen=True, slots=True)
class ChoicePresentation:
    """One option in a single-choice control."""

    key: str
    label: str
    selected: bool = False
    enabled: bool = True
    description: str = ""


@dataclass(frozen=True)
class WorkspaceValue:
    key: str
    label: str
    value: str
    status: str = "ready"
    control_value: str | None = None


@dataclass(frozen=True)
class WorkspaceGroup:
    key: str
    title: str
    kind: str
    values: tuple[WorkspaceValue, ...] = ()
    choices: tuple[ChoicePresentation, ...] = ()
    actions: tuple[WorkspaceAction, ...] = ()
    empty_label: str = ""
    status: str = "ready"
    status_summary: str = ""


@dataclass(frozen=True, slots=True)
class InlineNoticePresentation:
    """A concise message owned by exactly one visible workspace region."""

    message: str
    tone: NoticeTone = "info"


@dataclass(frozen=True, slots=True)
class SourceAssessmentPresentation(SourceDescription):
    """Source details supplied by the task layer."""

    document_summary: str = ""
    unlock_summary: str = ""
    has_updates: bool = False


@dataclass(frozen=True, slots=True)
class PathItemPresentation:
    key: str
    label: str
    display_path: str
    selected: bool = False


@dataclass(frozen=True, slots=True)
class SourceBodyPresentation:
    kind: Literal["source"] = field(init=False, default="source")
    primary_action: WorkspaceAction | None = None
    secondary_actions: tuple[WorkspaceAction, ...] = ()
    assessment: SourceAssessmentPresentation | None = None
    loading: bool = False
    notice: InlineNoticePresentation | None = None

    def __post_init__(self) -> None:
        actions = (
            (self.primary_action,) if self.primary_action is not None else ()
        ) + self.secondary_actions
        keys = tuple(action.key for action in actions)
        if len(keys) != len(set(keys)):
            raise ValueError("source action keys must be unique")


@dataclass(frozen=True, slots=True)
class UnlockBodyPresentation:
    kind: Literal["unlock"] = field(init=False, default="unlock")
    methods: tuple[ChoicePresentation, ...] = ()
    method_action: WorkspaceAction | None = None
    input_summary: str = ""
    passphrase_set: bool = False
    notice: InlineNoticePresentation | None = None

    def __post_init__(self) -> None:
        _require_at_most_one_selected(self.methods, owner="unlock methods")


@dataclass(frozen=True, slots=True)
class PathSelectionBodyPresentation:
    kind: Literal["path_selection"] = field(init=False, default="path_selection")
    items: tuple[PathItemPresentation, ...] = ()
    empty_label: str = "Nothing selected"
    count_summary: str = ""
    actions: tuple[WorkspaceAction, ...] = ()
    notice: InlineNoticePresentation | None = None


@dataclass(frozen=True, slots=True)
class DestinationBodyPresentation:
    kind: Literal["destination"] = field(init=False, default="destination")
    label: str = "Destination"
    display_path: str = ""
    empty_label: str = "Not selected"
    action: WorkspaceAction | None = None
    notice: InlineNoticePresentation | None = None


@dataclass(frozen=True, slots=True)
class QuorumCopyPresentation:
    item_singular: str = "sheet"
    item_plural: str = "sheets"
    action_phrase: str = "restore"

    def describe(self, threshold: int, count: int) -> str:
        item = self.item_singular if count == 1 else self.item_plural
        return f"Create {count} {item}; any {threshold} can {self.action_phrase}"


@dataclass(frozen=True, slots=True)
class QuorumBodyPresentation:
    kind: Literal["quorum"] = field(init=False, default="quorum")
    threshold: int | None = None
    count: int | None = None
    minimum: int = 1
    maximum: int = MAX_SHARES
    threshold_label: str = "Required"
    count_label: str = "Total"
    copy: QuorumCopyPresentation = field(default_factory=QuorumCopyPresentation)
    notice: InlineNoticePresentation | None = None
    visible: bool = True

    def __post_init__(self) -> None:
        if self.minimum < 1 or self.maximum < self.minimum:
            raise ValueError("quorum bounds must be positive and ordered")
        for value in (self.threshold, self.count):
            if value is not None and not self.minimum <= value <= self.maximum:
                raise ValueError("quorum values must be within the configured bounds")


@dataclass(frozen=True, slots=True)
class SelectOptionPresentation:
    """One literal label/value pair in a native Select control."""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class SelectFieldPresentation:
    """A keyed Select field whose option structure is stable after composition."""

    key: str
    label: str
    options: tuple[SelectOptionPresentation, ...]
    value: str | None = None
    enabled: bool = True
    visible: bool = True
    allow_blank: bool = True
    prompt: str = "Select"
    description: str = ""

    def __post_init__(self) -> None:
        option_keys = tuple(option.key for option in self.options)
        if len(option_keys) != len(set(option_keys)):
            raise ValueError(f"select field {self.key!r} option keys must be unique")
        if not self.options and not self.allow_blank:
            raise ValueError(f"select field {self.key!r} requires at least one option")
        if self.value is None and not self.allow_blank:
            raise ValueError(f"select field {self.key!r} requires a selected value")
        if self.value is not None and self.value not in option_keys:
            raise ValueError(f"select field {self.key!r} value must identify an option")


@dataclass(frozen=True, slots=True)
class OptionsBodyPresentation:
    """Typed fallback for compact, non-dependent options within a workflow step."""

    kind: Literal["options"] = field(init=False, default="options")
    values: tuple[WorkspaceValue, ...] = ()
    choices: tuple[ChoicePresentation, ...] = ()
    selects: tuple[SelectFieldPresentation, ...] = ()
    actions: tuple[WorkspaceAction, ...] = ()
    notice: InlineNoticePresentation | None = None

    def __post_init__(self) -> None:
        _require_at_most_one_selected(self.choices, owner="options")
        select_keys = tuple(select.key for select in self.selects)
        if len(select_keys) != len(set(select_keys)):
            raise ValueError("option select keys must be unique")


ControlBodyPresentation: TypeAlias = (
    SourceBodyPresentation
    | UnlockBodyPresentation
    | PathSelectionBodyPresentation
    | DestinationBodyPresentation
    | QuorumBodyPresentation
    | OptionsBodyPresentation
)


@dataclass(frozen=True, slots=True)
class CompositeBodyPartPresentation:
    """One group of controls within a workflow step."""

    key: str
    body: ControlBodyPresentation
    title: str


@dataclass(frozen=True, slots=True)
class CompositeBodyPresentation:
    """A workflow step containing multiple groups of controls."""

    kind: Literal["composite"] = field(init=False, default="composite")
    parts: tuple[CompositeBodyPartPresentation, ...] = ()

    def __post_init__(self) -> None:
        part_keys = tuple(part.key for part in self.parts)
        if not part_keys:
            raise ValueError("a composite body must contain at least one part")
        if len(part_keys) != len(set(part_keys)):
            raise ValueError("composite body part keys must be unique")


StepBodyPresentation: TypeAlias = ControlBodyPresentation | CompositeBodyPresentation


@dataclass(frozen=True, slots=True)
class StepPresentation:
    key: str
    title: str
    state: StepState
    summary: str
    body: StepBodyPresentation
    issue: InlineNoticePresentation | None = None
    severity: StepSeverity = "none"
    visible: bool = True


@dataclass(frozen=True)
class SummaryPresentation:
    title: str
    items: tuple[WorkspaceValue, ...]
    blockers: tuple[TaskIssue, ...]
    warnings: tuple[TaskIssue, ...]


@dataclass(frozen=True, slots=True)
class WorkflowPresentation:
    """The steps, current selection, and review summary for a guided task."""

    task_key: TaskKey
    title: str
    active_step: str
    steps: tuple[StepPresentation, ...]
    primary_action: WorkspaceAction
    review_summary: SummaryPresentation

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("a guided workflow must contain at least one step")
        step_keys = tuple(step.key for step in self.steps)
        if len(step_keys) != len(set(step_keys)):
            raise ValueError("guided workflow step keys must be unique")
        if self.active_step not in step_keys:
            raise ValueError("active_step must identify a workflow step")
        current_steps = tuple(step.key for step in self.steps if step.state == "current")
        if current_steps != (self.active_step,):
            raise ValueError("exactly active_step must have the current state")

    @property
    def active_step_number(self) -> int:
        return next(
            index for index, step in enumerate(self.steps, start=1) if step.key == self.active_step
        )

    @property
    def progress_label(self) -> str:
        return f"Step {self.active_step_number} of {len(self.steps)}"


@dataclass(frozen=True)
class TaskPresentation:
    task_key: TaskKey
    title: str
    ready_count: int
    total_count: int
    workspace_groups: tuple[WorkspaceGroup, ...]
    summary: SummaryPresentation
    primary_action: WorkspaceAction
    diagnostics_available: bool
    validation_ready: bool
    workflow: WorkflowPresentation | None = None

    @property
    def readiness_label(self) -> str:
        if self.validation_ready:
            return "Ready to review"
        if self.ready_count >= self.total_count:
            return "Needs attention"
        return f"{self.ready_count} of {self.total_count} ready"


def _require_at_most_one_selected(
    choices: tuple[ChoicePresentation, ...],
    *,
    owner: str,
) -> None:
    keys = tuple(choice.key for choice in choices)
    if len(keys) != len(set(keys)):
        raise ValueError(f"{owner} keys must be unique")
    if sum(choice.selected for choice in choices) > 1:
        raise ValueError(f"{owner} may select at most one choice")


@dataclass(frozen=True, slots=True)
class ReviewDetail:
    """One grouped review row, optionally linked to its editor."""

    label: str
    value: str
    section: str | None = None
    group: Literal["choices", "output"] = "choices"
