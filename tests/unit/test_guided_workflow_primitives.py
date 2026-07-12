from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from textual import on
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Input, RadioButton, RadioSet, Select, SelectionList, Static

from ethernity.app.widgets.guided_workflow import (
    CompositeStepBody,
    DestinationEditor,
    InlineNotice,
    OptionsEditor,
    PathSelectionEditor,
    QuorumEditor,
    SourceChooser,
    UnlockEditor,
    WorkflowStepHeader,
    WorkflowStepStack,
)
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    CompositeBodyPartPresentation,
    CompositeBodyPresentation,
    DestinationBodyPresentation,
    InlineNoticePresentation,
    OptionsBodyPresentation,
    PathItemPresentation,
    PathSelectionBodyPresentation,
    QuorumBodyPresentation,
    SelectFieldPresentation,
    SelectOptionPresentation,
    SourceAssessmentPresentation,
    SourceBodyPresentation,
    StepPresentation,
    SummaryPresentation,
    UnlockBodyPresentation,
    WorkflowPresentation,
    WorkspaceAction,
    WorkspaceValue,
)


class PrimitiveHarness(App[None]):
    def __init__(self, widget: Widget) -> None:
        super().__init__()
        self.widget = widget
        self.source_methods: list[str] = []
        self.unlock_methods: list[str] = []
        self.unlock_actions: list[str] = []
        self.step_requests: list[str] = []
        self.quorum_values: list[tuple[int | None, int | None]] = []
        self.destination_actions: list[str] = []
        self.path_actions: list[str] = []
        self.option_selects: list[tuple[str, str | None]] = []
        self.option_actions: list[str] = []

    def compose(self) -> ComposeResult:
        yield self.widget

    @on(SourceChooser.MethodChanged)
    def record_source_method(self, event: SourceChooser.MethodChanged) -> None:
        self.source_methods.append(event.method_key)

    @on(UnlockEditor.MethodChanged)
    def record_unlock_method(self, event: UnlockEditor.MethodChanged) -> None:
        self.unlock_methods.append(event.method_key)

    @on(UnlockEditor.ActionRequested)
    def record_unlock_action(self, event: UnlockEditor.ActionRequested) -> None:
        self.unlock_actions.append(event.action.key)

    @on(WorkflowStepStack.StepRequested)
    def record_step_request(self, event: WorkflowStepStack.StepRequested) -> None:
        self.step_requests.append(event.step_key)

    @on(QuorumEditor.Changed)
    def record_quorum(self, event: QuorumEditor.Changed) -> None:
        self.quorum_values.append((event.threshold, event.count))

    @on(DestinationEditor.ActionRequested)
    def record_destination_action(self, event: DestinationEditor.ActionRequested) -> None:
        self.destination_actions.append(event.action.key)

    @on(PathSelectionEditor.ActionRequested)
    def record_path_action(self, event: PathSelectionEditor.ActionRequested) -> None:
        self.path_actions.append(event.action.key)

    @on(OptionsEditor.SelectChanged)
    def record_option_select(self, event: OptionsEditor.SelectChanged) -> None:
        self.option_selects.append((event.select_key, event.value))

    @on(OptionsEditor.ActionRequested)
    def record_option_action(self, event: OptionsEditor.ActionRequested) -> None:
        self.option_actions.append(event.action.key)


def test_workflow_presentation_enforces_typed_step_invariants() -> None:
    with pytest.raises(ValueError, match="at most one"):
        SourceBodyPresentation(
            methods=(
                ChoicePresentation("scans", "Scanned pages", selected=True),
                ChoicePresentation("text", "Recovery text", selected=True),
            )
        )

    workflow = _workflow(
        active_step="unlock",
        steps=(
            StepPresentation(
                "source",
                "Backup source",
                "complete",
                "4 scanned pages",
                _source_body(selected="scans"),
            ),
            StepPresentation(
                "unlock",
                "Unlock backup",
                "current",
                "Passphrase required",
                UnlockBodyPresentation(),
                InlineNoticePresentation("Enter the backup passphrase.", tone="error"),
                "error",
            ),
        ),
    )

    assert workflow.progress_label == "Step 2 of 2"

    with pytest.raises(ValueError, match="exactly active_step"):
        replace(
            workflow,
            steps=(workflow.steps[0], replace(workflow.steps[1], state="locked")),
        )
    with pytest.raises(ValueError, match="exactly active_step"):
        replace(
            workflow,
            steps=(replace(workflow.steps[0], state="current"), workflow.steps[1]),
        )


def test_select_and_composite_presentations_enforce_keyed_structure() -> None:
    paper = SelectFieldPresentation(
        "workspace-rebuild-paper",
        "Paper size",
        (
            SelectOptionPresentation("A4", "A4"),
            SelectOptionPresentation("LETTER", "Letter"),
        ),
        value="A4",
        allow_blank=False,
    )

    with pytest.raises(ValueError, match="value must identify an option"):
        replace(paper, value="LEGAL")
    with pytest.raises(ValueError, match="option keys must be unique"):
        replace(
            paper,
            options=(
                SelectOptionPresentation("A4", "First"),
                SelectOptionPresentation("A4", "Second"),
            ),
        )
    with pytest.raises(ValueError, match="option select keys must be unique"):
        OptionsBodyPresentation(selects=(paper, paper))
    with pytest.raises(ValueError, match="requires a selected value"):
        replace(paper, value=None)

    source = CompositeBodyPartPresentation("source", _source_body())
    with pytest.raises(ValueError, match="part keys must be unique"):
        CompositeBodyPresentation(parts=(source, source))
    with pytest.raises(ValueError, match="at least one part"):
        CompositeBodyPresentation()


def test_workflow_ui_state_keeps_interaction_lifecycle_out_of_task_models() -> None:
    state = WorkflowUiState.start("source", "unlock", "destination")

    state.activate("unlock")
    state.touch("unlock.method", "unlock.passphrase")
    state.mark_review_attempted()
    state.advanced_expanded = True
    state.set_invalid_draft(
        "unlock",
        {"threshold": "6", "count": "3"},
        message="Required sheets cannot exceed the total sheet count.",
    )

    assert state.active_step == "unlock"
    assert state.is_touched("unlock.passphrase")
    assert state.attempted_review
    assert state.advanced_expanded
    assert state.has_invalid_draft()
    assert state.has_invalid_draft("unlock")
    assert state.draft_values["unlock"] == {"threshold": "6", "count": "3"}
    assert state.draft_error("unlock") == ("Required sheets cannot exceed the total sheet count.")

    state.clear_draft("unlock")

    assert not state.has_invalid_draft()
    assert state.draft_error("unlock") is None

    state.set_invalid_draft("unlock", {"threshold": ""}, message="Enter a threshold.")

    state.reset_interaction()

    assert not state.touched_fields
    assert not state.attempted_review
    assert not state.has_invalid_draft()
    with pytest.raises(KeyError, match="unknown workflow step"):
        state.activate("missing")


def test_source_chooser_uses_native_radio_set_and_can_return_to_no_selection() -> None:
    async def run() -> None:
        body = _source_body()
        chooser = SourceChooser(body, id="source")
        app = PrimitiveHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            radio = chooser.query_one(RadioSet)
            assert chooser.selected_method is None

            radio.focus()
            await pilot.press("space")
            await pilot.pause()

            assert chooser.selected_method == "scans"
            assert app.source_methods == ["scans"]

            chooser.sync_presentation(body)
            await pilot.pause()

            assert chooser.selected_method is None
            assert app.source_methods == ["scans"]

    asyncio.run(run())


def test_source_chooser_change_returns_to_all_methods_without_dispatching_old_action() -> None:
    async def run() -> None:
        body = SourceBodyPresentation(
            methods=_source_body(selected="scans").methods,
            assessment=SourceAssessmentPresentation(
                source_kind="scanned_pages",
                source_label="Scanned pages",
                material_summary="4 pages",
            ),
            change_action=WorkspaceAction("change-source", "Change source..."),
        )
        chooser = SourceChooser(body, id="source")
        app = PrimitiveHarness(chooser)
        async with app.run_test(size=(80, 24)) as pilot:
            methods = chooser.query_one(RadioSet)
            assessment = chooser.query_one(".guided-summary")

            assert not methods.display
            assert assessment.display

            await pilot.click("#source-change")
            await pilot.pause()

            assert methods.display
            assert not assessment.display
            assert chooser.selected_method is None
            assert app.source_methods == []

            radio_buttons = list(methods.query(RadioButton))
            radio_buttons[2].value = True
            await pilot.pause()

            assert app.source_methods == ["text"]
            assert not methods.display
            assert assessment.display

    asyncio.run(run())


def test_source_chooser_loading_state_explains_what_is_happening() -> None:
    async def run() -> None:
        chooser = SourceChooser(replace(_source_body(), loading=True), id="source")
        app = PrimitiveHarness(chooser)
        async with app.run_test(size=(80, 24)):
            loading = chooser.query_one(".guided-loading")
            label = chooser.query_one(".guided-loading-label", Static)

            assert loading.display
            assert str(label.content) == "Inspecting backup source..."
            assert not chooser.query_one(RadioSet).display

    asyncio.run(run())


def test_step_stack_expands_only_active_step_and_reports_keyboard_requests() -> None:
    async def run() -> None:
        workflow = _workflow(
            active_step="source",
            steps=(
                StepPresentation(
                    "source",
                    "Backup source",
                    "current",
                    "Choose a source",
                    _source_body(),
                ),
                StepPresentation(
                    "unlock",
                    "Unlock backup",
                    "locked",
                    "Waiting for source",
                    UnlockBodyPresentation(),
                ),
                StepPresentation(
                    "destination",
                    "Destination",
                    "locked",
                    "Waiting for unlock",
                    DestinationBodyPresentation(),
                ),
            ),
        )
        stack = WorkflowStepStack(workflow, id="steps")
        app = PrimitiveHarness(stack)
        async with app.run_test(size=(80, 24)) as pilot:
            headers = list(stack.query(WorkflowStepHeader))
            bodies = list(stack.query(".guided-step-body"))

            assert [body.display for body in bodies] == [True, False, False]
            assert headers[1].disabled
            assert headers[0].region.height == 2
            assert headers[1].region.height == 1
            assert not headers[1].query_one(".workflow-step-summary", Static).display

            headers[0].focus()
            await pilot.press("enter")
            await pilot.pause()

            assert app.step_requests == ["source"]

            updated = replace(
                workflow,
                active_step="unlock",
                steps=(
                    replace(workflow.steps[0], state="complete", summary="4 scanned pages"),
                    replace(
                        workflow.steps[1],
                        state="current",
                        summary="Passphrase required",
                        issue=InlineNoticePresentation(
                            "Enter the backup passphrase.",
                            tone="error",
                        ),
                        severity="error",
                    ),
                    workflow.steps[2],
                ),
            )
            stack.sync_presentation(updated)
            stack.focus_active()
            await pilot.pause()

            assert [body.display for body in bodies] == [False, True, False]
            assert headers[1].has_class("step-current")
            assert headers[1].has_class("step-error")
            assert str(headers[1].query_one(".workflow-step-status", Static).content) == (
                "Current / Error"
            )
            assert app.focused is headers[1]
            assert all(body.region.bottom <= 24 for body in bodies if body.display)

    asyncio.run(run())


def test_step_header_keeps_progress_and_severity_visible_without_wrapping() -> None:
    async def run() -> None:
        header = WorkflowStepHeader(
            StepPresentation(
                "source",
                "Existing backup",
                "current",
                "A very long source path that must not turn into a paragraph at narrow widths",
                _source_body(),
                severity="warning",
            ),
            1,
        )
        app = PrimitiveHarness(header)
        async with app.run_test(size=(40, 8)):
            marker = header.query_one(".workflow-step-marker", Static)
            number = header.query_one(".workflow-step-number", Static)
            title = header.query_one(".workflow-step-title", Static)
            summary = header.query_one(".workflow-step-summary", Static)
            status = header.query_one(".workflow-step-status", Static)

            assert str(marker.content) == "[>]"
            assert str(number.content) == "1"
            assert str(title.content) == "Existing backup"
            assert str(status.content) == "Current / Warning"
            assert header.has_class("step-current")
            assert header.has_class("step-warning")
            assert summary.region.height == 1
            assert summary.render_line(0).text.rstrip().endswith("\u2026")

    asyncio.run(run())


def test_unlock_editor_uses_native_radio_behavior_and_typed_local_action() -> None:
    async def run() -> None:
        editor = UnlockEditor(
            UnlockBodyPresentation(
                methods=(
                    ChoicePresentation("passphrase", "Passphrase", selected=True),
                    ChoicePresentation("sheets", "Recovery sheets"),
                    ChoicePresentation("payloads", "Recovery payload files"),
                ),
                contextual_action=WorkspaceAction("enter-unlock", "Enter passphrase..."),
                material_summary="Passphrase set",
            ),
            id="unlock",
        )
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            radio = editor.query_one(RadioSet)
            radio.focus()

            await pilot.press("right", "space")
            await pilot.pause()

            assert editor.selected_method == "sheets"
            assert app.unlock_methods == ["sheets"]

            await pilot.click("#unlock-action")
            await pilot.pause()

            assert app.unlock_actions == ["enter-unlock"]

    asyncio.run(run())


def test_quorum_editor_has_live_sentence_and_specific_inline_error() -> None:
    async def run() -> None:
        editor = QuorumEditor(
            QuorumBodyPresentation(threshold=3, count=5),
            id="quorum",
        )
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            summary = editor.query_one(".guided-summary", Static)
            notice = editor.query_one(InlineNotice)
            threshold = editor.query_one("#quorum-threshold", Input)
            count = editor.query_one("#quorum-count", Input)

            assert str(summary.content) == "Create 5 sheets; any 3 can restore"
            assert not notice.display

            threshold.value = "6"
            await pilot.pause()

            assert str(summary.content) == "Choose a valid quorum"
            assert "cannot exceed" in str(notice.content)
            assert notice.has_class("notice-error")

            count.value = "7"
            await pilot.pause()

            assert str(summary.content) == "Create 7 sheets; any 6 can restore"
            assert not notice.display
            assert app.quorum_values[-1] == (6, 7)
            assert editor.region.bottom <= 24

    asyncio.run(run())


def test_options_editor_uses_native_keyed_selects_and_suppresses_sync_messages() -> None:
    async def run() -> None:
        paper = SelectFieldPresentation(
            "workspace-rebuild-paper",
            "Paper [size]",
            (
                SelectOptionPresentation("A4", "[bold]A4[/bold]"),
                SelectOptionPresentation("LETTER", "Letter"),
            ),
            value="A4",
            allow_blank=False,
        )
        body = OptionsBodyPresentation(
            values=(
                WorkspaceValue("empty", "Empty", ""),
                WorkspaceValue("layout", "Layout", "[bold]A4[/bold]"),
            ),
            selects=(paper,),
            actions=(WorkspaceAction("hidden-action", "Hidden", visible=False),),
        )
        editor = OptionsEditor(body, id="options")
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            select = editor.query_one("#workspace-rebuild-paper", Select)
            values = list(editor.query(".guided-detail"))

            assert select.value == "A4"
            assert not values[0].display
            assert "[bold]A4[/bold]" in str(values[1].content)
            assert not editor.query_one(".guided-actions").display
            assert "[bold]A4[/bold]" in str(select._options[0][0])
            assert "[bold]A4[/bold]" in str(
                select.query_one("SelectCurrent > #label", Static).content
            )

            select.value = "LETTER"
            await pilot.pause()

            assert app.option_selects == [("workspace-rebuild-paper", "LETTER")]

            updated = replace(
                body,
                selects=(
                    replace(
                        paper,
                        value="A4",
                        options=(
                            SelectOptionPresentation("A4", "A4 updated"),
                            SelectOptionPresentation("LETTER", "Letter updated"),
                        ),
                    ),
                ),
            )
            editor.sync_presentation(updated)
            await pilot.pause()

            assert select.value == "A4"
            assert app.option_selects == [("workspace-rebuild-paper", "LETTER")]
            assert "A4 updated" in str(select._options[0][0])
            assert "A4 updated" in str(select.query_one("SelectCurrent > #label", Static).content)

            with pytest.raises(ValueError, match="choice keys cannot change"):
                editor.sync_presentation(
                    replace(
                        updated,
                        selects=(
                            replace(
                                updated.selects[0],
                                options=(SelectOptionPresentation("LEGAL", "Legal"),),
                                value="LEGAL",
                            ),
                        ),
                    )
                )

    asyncio.run(run())


def test_optional_options_part_hides_empty_chrome_but_keeps_structural_controls() -> None:
    async def run() -> None:
        empty = OptionsBodyPresentation(
            values=(WorkspaceValue("trust", "Trust", ""),),
            actions=(WorkspaceAction("accept", "Use these scans", visible=False),),
        )
        editor = OptionsEditor(empty, id="trust")
        app = PrimitiveHarness(editor)
        async with app.run_test(size=(80, 24)) as pilot:
            assert not editor.display
            assert not editor.query_one(".guided-detail").display
            assert not editor.query_one(".guided-actions").display

            editor.sync_presentation(
                replace(
                    empty,
                    values=(WorkspaceValue("trust", "Trust", "Confirmation required"),),
                    actions=(WorkspaceAction("accept", "Use these scans"),),
                )
            )
            await pilot.pause()

            assert editor.display
            assert editor.query_one(".guided-detail").display
            assert editor.query_one(".guided-actions").display

            await pilot.click("#accept")
            await pilot.pause()

            assert app.option_actions == ["accept"]

    asyncio.run(run())


def test_composite_step_body_keeps_keyed_parts_mounted_and_enforces_kinds() -> None:
    async def run() -> None:
        trust = OptionsBodyPresentation(
            actions=(WorkspaceAction("accept", "Use these scans", visible=False),)
        )
        body = CompositeBodyPresentation(
            parts=(
                CompositeBodyPartPresentation("source", _source_body()),
                CompositeBodyPartPresentation("trust", trust),
            )
        )
        composite = CompositeStepBody(body, id="combined")
        app = PrimitiveHarness(composite)
        async with app.run_test(size=(80, 24)) as pilot:
            source = composite.query_one("#combined-source", SourceChooser)
            trust_editor = composite.query_one("#combined-trust", OptionsEditor)

            assert source.display
            assert not trust_editor.display
            assert composite.region.bottom <= 24

            updated = replace(
                body,
                parts=(
                    body.parts[0],
                    replace(
                        body.parts[1],
                        body=replace(
                            trust,
                            actions=(WorkspaceAction("accept", "Use these scans"),),
                        ),
                    ),
                ),
            )
            composite.sync_presentation(updated)
            await pilot.pause()

            assert trust_editor.display

            with pytest.raises(ValueError, match="part keys cannot change"):
                composite.sync_presentation(
                    replace(
                        updated,
                        parts=(updated.parts[0], replace(updated.parts[1], key="freshness")),
                    )
                )
            with pytest.raises(ValueError, match="part kinds cannot change"):
                composite.sync_presentation(
                    replace(
                        updated,
                        parts=(
                            updated.parts[0],
                            replace(updated.parts[1], body=DestinationBodyPresentation()),
                        ),
                    )
                )

    asyncio.run(run())


def test_path_and_destination_summaries_render_dynamic_text_literally() -> None:
    async def run() -> None:
        paths = PathSelectionEditor(
            PathSelectionBodyPresentation(
                items=(
                    PathItemPresentation(
                        "one",
                        "archive.txt",
                        "[red]/tmp/archive.txt[/red]",
                        selected=True,
                    ),
                ),
                count_summary="1 file selected",
                actions=(WorkspaceAction("remove", "Remove selected"),),
            ),
            id="paths",
        )
        path_app = PrimitiveHarness(paths)
        async with path_app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            selection = paths.query_one(SelectionList)
            assert paths.selected_keys == ("one",)
            assert "[red]/tmp/archive.txt[/red]" in str(selection.get_option_at_index(0).prompt)

            await pilot.click("#remove")
            await pilot.pause()

            assert path_app.path_actions == ["remove"]

        destination = DestinationEditor(
            DestinationBodyPresentation(
                display_path="[red]/tmp/Recovered[/red]",
                action=WorkspaceAction("browse", "Browse..."),
                notice=InlineNoticePresentation(
                    "Destination contains 2 items; matching names may be replaced.",
                    tone="warning",
                ),
            ),
            id="destination",
        )
        destination_app = PrimitiveHarness(destination)
        async with destination_app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            value = destination.query_one(".guided-field-value", Static)
            notice = destination.query_one(InlineNotice)

            assert str(value.content) == "[red]/tmp/Recovered[/red]"
            assert "matching names may be replaced" in str(notice.content)

            await pilot.click("#destination-action")
            await pilot.pause()

            assert destination_app.destination_actions == ["browse"]

    asyncio.run(run())


def _source_body(selected: str | None = None) -> SourceBodyPresentation:
    return SourceBodyPresentation(
        methods=(
            ChoicePresentation("scans", "Scanned pages", selected=selected == "scans"),
            ChoicePresentation("text", "Paste recovery text", selected=selected == "text"),
            ChoicePresentation("payloads", "Payload files", selected=selected == "payloads"),
        )
    )


def _workflow(
    *,
    active_step: str,
    steps: tuple[StepPresentation, ...],
) -> WorkflowPresentation:
    return WorkflowPresentation(
        task_key="restore",
        title="Restore files",
        active_step=active_step,
        steps=steps,
        primary_action=WorkspaceAction("continue", "Continue"),
        review_summary=SummaryPresentation(
            title="Review restore",
            items=(),
            blockers=(),
            warnings=(),
        ),
    )
