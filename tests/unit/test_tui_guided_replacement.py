from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Button, Input, RadioSet

from ethernity.app.application import EthernityApp
from ethernity.app.widgets.guided_workflow import InlineNotice, QuorumEditor
from ethernity.app.workflow_presenter import build_guided_workflow
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.presentation.models import (
    CompositeBodyPresentation,
    OptionsBodyPresentation,
    QuorumBodyPresentation,
    SummaryPresentation,
)
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState


def test_replacement_recovery_default_is_visible_and_custom_quorum_stays_collapsed() -> None:
    state = ReplaceRecoveryDocsTaskState()
    ui_state = WorkflowUiState.start("source", "unlock", "recovery", "output")
    workflow = build_guided_workflow(
        task="replace_recovery_docs",
        state=state,
        validation=state.validate_task(),
        ui_state=ui_state,
        review_summary=_empty_summary(),
        review_label="Review replacement sheets",
    )

    assert workflow is not None
    recovery = workflow.steps[2].body
    assert isinstance(recovery, CompositeBodyPresentation)
    quorum = recovery.parts[1].body
    assert isinstance(quorum, QuorumBodyPresentation)
    assert not quorum.visible
    modes = recovery.parts[0].body
    assert isinstance(modes, OptionsBodyPresentation)
    choices = modes.choices
    assert any(choice.key == "recommended" and choice.selected for choice in choices)


def test_replacement_custom_quorum_updates_live_and_can_return_to_recommended() -> None:
    async def run() -> None:
        app = EthernityApp(
            replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                source_paths=[Path("scan.pdf")],
                allow_stale_head=True,
                passphrase="secret",
                output_dir=Path("replacement"),
            )
        )
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("5")
            await pilot.click("#canvas-primary")
            await pilot.pause()
            await pilot.click("#canvas-primary")
            await pilot.pause()

            modes = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-mode-choices",
                RadioSet,
            )
            modes.focus()
            await pilot.press("right", "space")
            await pilot.pause()

            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum",
                QuorumEditor,
            )
            assert quorum.display
            quorum.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum-count",
                Input,
            ).value = "5"
            await pilot.pause()
            quorum.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum-threshold",
                Input,
            ).value = "3"
            await pilot.pause()

            assert app.replace_recovery_docs_state.recovery_threshold == 3
            assert app.replace_recovery_docs_state.recovery_document_count == 5

            modes.focus()
            await pilot.press("left", "space")
            await pilot.pause()

            assert app.replace_recovery_docs_state.recovery_threshold == 2
            assert app.replace_recovery_docs_state.recovery_document_count == 3
            assert not quorum.display

    asyncio.run(run())


def test_replacement_invalid_quorum_draft_blocks_progress_and_stays_visible_at_80x24() -> None:
    async def run() -> None:
        app = EthernityApp(
            replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                source_paths=[Path("scan.pdf")],
                allow_stale_head=True,
                passphrase="secret",
                output_dir=Path("replacement"),
            )
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("5")
            await pilot.click("#canvas-primary")
            await pilot.pause()
            await pilot.click("#canvas-primary")
            await pilot.pause()

            modes = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-mode-choices",
                RadioSet,
            )
            modes.focus()
            await pilot.press("right", "space")
            await pilot.pause()

            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum",
                QuorumEditor,
            )
            threshold = quorum.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum-threshold",
                Input,
            )
            count = quorum.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum-count",
                Input,
            )
            notice = quorum.query_one(InlineNotice)
            primary = app.query_one("#canvas-primary", Button)
            action_bar = app.query_one("#task-action-bar")
            ui_state = app.workflow_ui_states["replace_recovery_docs"]

            threshold.focus()
            threshold.value = ""
            await pilot.pause()

            assert ui_state.has_invalid_draft("recovery")
            assert ui_state.draft_values["recovery"] == {"threshold": "", "count": "3"}
            assert "Enter both" in str(notice.content)
            assert primary.disabled
            assert app.replace_recovery_docs_state.recovery_threshold == 2
            assert app.replace_recovery_docs_state.recovery_document_count == 3

            threshold.value = "6"
            await pilot.pause()

            assert ui_state.draft_values["recovery"] == {"threshold": "6", "count": "3"}
            assert "cannot exceed" in str(notice.content)
            assert primary.disabled
            assert app.replace_recovery_docs_state.recovery_threshold == 2
            assert app.replace_recovery_docs_state.recovery_document_count == 3
            assert threshold.region.bottom <= action_bar.region.y
            assert notice.region.bottom <= action_bar.region.y

            await app.action_primary()
            await pilot.pause()

            assert ui_state.active_step == "recovery"

            count.value = "7"
            await pilot.pause()

            assert not ui_state.has_invalid_draft("recovery")
            assert not primary.disabled
            assert app.replace_recovery_docs_state.recovery_threshold == 6
            assert app.replace_recovery_docs_state.recovery_document_count == 7

            await pilot.click("#canvas-primary")
            await pilot.pause()

            assert ui_state.active_step == "output"

    asyncio.run(run())


def test_replacement_guided_inputs_use_workspace_traversal_and_keep_radio_arrows() -> None:
    async def run() -> None:
        app = EthernityApp(
            replace_recovery_docs_state=ReplaceRecoveryDocsTaskState(
                source_paths=[Path("scan.pdf")],
                allow_stale_head=True,
                passphrase="secret",
                output_dir=Path("replacement"),
            )
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("5")
            await pilot.click("#canvas-primary")
            await pilot.click("#canvas-primary")
            await pilot.pause()

            modes = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-mode-choices",
                RadioSet,
            )
            modes.focus()
            await pilot.press("right")
            await pilot.pause()
            assert app.screen.focused is modes

            await pilot.press("space")
            await pilot.pause()
            quorum = app.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum",
                QuorumEditor,
            )
            threshold = quorum.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum-threshold",
                Input,
            )
            count = quorum.query_one(
                "#workflow-replace_recovery_docs-recovery-body-quorum-count",
                Input,
            )

            threshold.focus()
            await pilot.press("j")
            await pilot.pause()
            assert app.screen.focused is count

            await pilot.press("k")
            await pilot.pause()
            assert app.screen.focused is threshold

    asyncio.run(run())


def test_replacement_quorum_domain_update_avoids_invalid_intermediate_state() -> None:
    state = ReplaceRecoveryDocsTaskState(recovery_threshold=4, recovery_document_count=6)

    state.set_recovery_quorum(2, 3)

    assert state.recovery_threshold == 2
    assert state.recovery_document_count == 3


def _empty_summary() -> SummaryPresentation:
    return SummaryPresentation(title="", items=(), blockers=(), warnings=())
