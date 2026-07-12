"""Non-functional Restore prototype used to settle the visual contract."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Static

from tests.visual.presentation_states import RestorePresentationFixture, StepFixture

_STEP_MARKERS = {
    "locked": "[ ]",
    "available": "[ ]",
    "current": "[>]",
    "complete": "[x]",
    "warning": "[!]",
    "error": "[!]",
}


class PrototypeStep(Widget):
    """One responsive step summary with a non-color status marker."""

    def __init__(self, number: int, fixture: StepFixture) -> None:
        super().__init__(classes=f"prototype-step status-{fixture.status}")
        self.number = number
        self.fixture = fixture

    def compose(self) -> ComposeResult:
        yield Static(
            _STEP_MARKERS[self.fixture.status],
            classes="step-marker",
            markup=False,
        )
        with Vertical(classes="step-copy"):
            yield Static(f"{self.number}. {self.fixture.title}", classes="step-title", markup=False)
            yield Static(self.fixture.summary, classes="step-summary", markup=False)


class RestorePrototypeApp(App[None]):
    """Static design prototype; buttons intentionally perform no workflow mutations."""

    TITLE = "Ethernity Restore prototype"
    AUTO_FOCUS = None
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (96, "-standard"), (136, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (28, "-regular-height"), (40, "-tall")]

    CSS = """
    Screen {
        align: center top;
        background: #101416;
        color: #f1eee6;
    }

    #app-frame {
        width: 100%;
        max-width: 140;
        height: 100%;
        background: #101416;
    }

    #topbar {
        width: 1fr;
        height: 2;
        padding: 0 2;
        background: #1b2224;
        border-bottom: solid #374347;
    }

    #brand {
        width: 22;
        content-align: left middle;
        color: #f1eee6;
        text-style: bold;
    }

    #topbar-context {
        width: 1fr;
        content-align: center middle;
        color: #9da8a7;
        text-align: center;
    }

    #topbar-status {
        width: 24;
        content-align: right middle;
        color: #69c1b5;
        text-align: right;
    }

    #task-header {
        width: 1fr;
        height: 3;
        padding: 1 2;
    }

    #task-title {
        width: 1fr;
        text-style: bold;
    }

    #task-progress {
        width: 28;
        color: #9da8a7;
        text-align: right;
    }

    #workflow-body {
        width: 1fr;
        height: 1fr;
        margin: 0 2;
        border-top: solid #374347;
        border-bottom: solid #374347;
    }

    #step-stack {
        width: 37;
        height: 1fr;
        padding: 1 1 0 0;
        background: #14191b;
        border-right: solid #374347;
        overflow-y: auto;
    }

    .prototype-step {
        layout: horizontal;
        width: 1fr;
        height: 3;
        padding: 0 1;
        color: #9da8a7;
    }

    .step-marker {
        width: 4;
        height: 1;
        color: #7f8b8c;
    }

    .step-copy {
        width: 1fr;
        height: 2;
    }

    .step-title {
        width: 1fr;
        height: 1;
        text-style: bold;
    }

    .step-summary {
        width: 1fr;
        height: 1;
        color: #7f8b8c;
        text-overflow: ellipsis;
    }

    .prototype-step.status-current {
        background: #20292b;
        color: #f1eee6;
        border-left: thick #69c1b5;
    }

    .prototype-step.status-current .step-marker,
    .prototype-step.status-complete .step-marker {
        color: #69c1b5;
    }

    .prototype-step.status-warning .step-marker {
        color: #dfb45f;
    }

    .prototype-step.status-error .step-marker {
        color: #e27373;
    }

    .prototype-step.status-locked {
        color: #667173;
    }

    #current-step {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        background: #1a2022;
        overflow-y: auto;
    }

    #detail-heading {
        width: 1fr;
        height: 2;
        color: #f1eee6;
        text-style: bold;
    }

    .detail-line {
        width: 1fr;
        height: auto;
        min-height: 1;
        margin-bottom: 1;
        color: #d7d5ce;
    }

    .detail-line.secondary {
        color: #9da8a7;
    }

    .choice-actions {
        width: 1fr;
        height: 1;
        margin-top: 1;
    }

    .choice-actions Button,
    #change-unlock {
        width: auto;
        min-width: 16;
        max-width: 30;
        height: 1;
        margin-right: 1;
        padding: 0 1;
        border: none;
        background: #293235;
        color: #f1eee6;
    }

    .choice-actions Button:focus,
    #change-unlock:focus {
        background: #69c1b5;
        color: #0c1515;
        text-style: bold;
    }

    #change-unlock {
        margin-top: 1;
    }

    .notice {
        width: 1fr;
        height: auto;
        min-height: 2;
        margin-top: 1;
        padding: 0 1;
        border-left: thick #607174;
        color: #c8ccca;
        background: #202729;
    }

    .notice-warning {
        border-left: thick #dfb45f;
        color: #f0d69e;
    }

    .notice-error {
        border-left: thick #e27373;
        color: #f2b0b0;
    }

    .notice-success {
        border-left: thick #78b985;
        color: #b9dfc0;
    }

    #action-bar {
        width: 1fr;
        height: 3;
        padding: 1 2;
        background: #101416;
    }

    #action-note {
        width: 1fr;
        color: #9da8a7;
    }

    #primary-action {
        width: auto;
        min-width: 18;
        max-width: 40;
        height: 1;
        padding: 0 2;
        border: none;
        background: #69c1b5;
        color: #0c1515;
        text-style: bold;
    }

    #primary-action:focus {
        background: #9bd7cf;
    }

    #primary-action:disabled {
        background: #293235;
        color: #727d7e;
        text-style: none;
    }

    #shortcut-footer {
        width: 1fr;
        height: 1;
        padding: 0 2;
        background: #090c0d;
        color: #7f8b8c;
    }

    Screen.-narrow #app-frame {
        max-width: 100%;
    }

    Screen.-narrow #topbar,
    Screen.-narrow #task-header,
    Screen.-narrow #action-bar,
    Screen.-narrow #shortcut-footer {
        padding-left: 1;
        padding-right: 1;
    }

    Screen.-narrow #topbar-context {
        display: none;
    }

    Screen.-narrow #brand {
        width: 16;
    }

    Screen.-narrow #topbar-status {
        width: 1fr;
    }

    Screen.-narrow #task-progress {
        width: 22;
    }

    Screen.-narrow #workflow-body {
        layout: vertical;
        margin-left: 1;
        margin-right: 1;
    }

    Screen.-narrow #step-stack {
        width: 1fr;
        height: 5;
        padding: 0;
        border-right: none;
        border-bottom: solid #374347;
        overflow-y: hidden;
    }

    Screen.-narrow .prototype-step {
        height: 1;
        padding: 0 1;
    }

    Screen.-narrow .step-copy {
        height: 1;
    }

    Screen.-narrow .step-summary {
        display: none;
    }

    Screen.-narrow #current-step {
        padding: 1;
    }

    Screen.-narrow #detail-heading {
        height: 1;
        margin-bottom: 1;
    }

    Screen.-narrow .detail-line {
        margin-bottom: 0;
    }

    Screen.-narrow .choice-actions {
        layout: vertical;
        height: 3;
        margin-top: 1;
    }

    Screen.-narrow .choice-actions Button {
        width: 1fr;
        max-width: 100%;
        margin-right: 0;
    }

    Screen.-narrow .notice {
        min-height: 1;
        margin-top: 1;
    }

    Screen.-narrow #action-note {
        display: none;
    }

    Screen.-narrow #primary-action {
        width: 1fr;
        max-width: 100%;
    }

    Screen.-short #task-header,
    Screen.-short #action-bar {
        height: 2;
        padding-top: 0;
        padding-bottom: 1;
    }
    """

    def __init__(self, fixture: RestorePresentationFixture) -> None:
        super().__init__()
        self.fixture = fixture

    def compose(self) -> ComposeResult:
        with Vertical(id="app-frame"):
            with Horizontal(id="topbar"):
                yield Static("ETHERNITY", id="brand", markup=False)
                yield Static("Offline recovery", id="topbar-context", markup=False)
                yield Static(self.fixture.status_label, id="topbar-status", markup=False)

            with Horizontal(id="task-header"):
                yield Static("Restore backup", id="task-title", markup=False)
                yield Static(self.fixture.progress, id="task-progress", markup=False)

            with Horizontal(id="workflow-body"):
                with VerticalScroll(id="step-stack"):
                    for number, step in enumerate(self.fixture.steps, start=1):
                        yield PrototypeStep(number, step)

                with VerticalScroll(id="current-step"):
                    yield from self._compose_detail()

            with Horizontal(id="action-bar"):
                yield Static(self._action_note(), id="action-note", markup=False)
                yield Button(
                    self.fixture.primary_label,
                    id="primary-action",
                    disabled=not self.fixture.primary_enabled,
                )

            yield Static(
                "Tab  Move focus    Enter  Select    ?  Help    Ctrl+Q  Quit",
                id="shortcut-footer",
                markup=False,
            )

    def _compose_detail(self) -> ComposeResult:
        yield Static(self.fixture.heading, id="detail-heading", markup=False)

        if self.fixture.key in {"empty", "error"}:
            for index, line in enumerate(self.fixture.body):
                classes = "detail-line secondary" if index == 0 else "detail-line"
                yield Static(line, classes=classes, markup=False)
            if self.fixture.notice:
                yield self._notice()
            yield Horizontal(
                Button("Browse pages...", id="source-pages"),
                Button("Paste text...", id="source-text"),
                Button("Payload file...", id="source-payload"),
                classes="choice-actions",
            )
            return

        if self.fixture.key == "partial":
            for index, line in enumerate(self.fixture.body):
                classes = "detail-line" if index < 3 else "detail-line secondary"
                yield Static(line, classes=classes, markup=False)
            yield Button("Change method...", id="change-unlock")
            return

        for line in self.fixture.body:
            yield Static(line, classes="detail-line", markup=False)
        if self.fixture.notice:
            yield self._notice()

    def _notice(self) -> Static:
        return Static(
            self.fixture.notice or "",
            classes=f"notice notice-{self.fixture.notice_tone}",
            markup=False,
        )

    def _action_note(self) -> str:
        if self.fixture.view == "running":
            return "Inputs are locked while files are being written."
        if self.fixture.view == "result":
            return "Source and destination choices are retained until this result is closed."
        if self.fixture.primary_enabled:
            return "Nothing is written until you confirm the final review."
        return "Complete the current step to continue."

    def on_mount(self) -> None:
        if self.fixture.focus_id is None:
            return
        control = self.query_one(f"#{self.fixture.focus_id}", Button)
        if not control.disabled:
            control.focus()
