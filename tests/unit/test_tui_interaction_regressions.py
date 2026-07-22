from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Label,
    MarkdownViewer,
    OptionList,
    RadioButton,
    RichLog,
    Select,
    SelectionList,
    Static,
    TabbedContent,
)

from ethernity.app.application import EthernityApp
from ethernity.app.bindings import APP_BINDINGS
from ethernity.app.help_content import build_help_content
from ethernity.app.screens.diagnostics import DiagnosticsScreen
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen
from ethernity.app.screens.help import HelpScreen, _help_markdown
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.workspaces.common import WorkspacePathList, WorkspaceRadioSet
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import (
    PreviewItem,
    TaskDiagnosticBlock,
    TaskDiagnostics,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskResultDetail,
    TaskSection,
    TaskValidation,
)
from ethernity.tasks.presentation.models import WorkspaceChoice


def test_editor_and_diagnostics_actions_use_concrete_labels() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            editor = EditFieldScreen(title="Passphrase", prompt="Enter a passphrase")
            await app.push_screen(editor)
            await pilot.pause()
            assert str(editor.query_one("#edit-field-save", Button).label) == "Apply"
            editor.dismiss(None)
            await pilot.pause()

            paste = PasteTextScreen(title="Recovery text", prompt="Paste recovery text")
            await app.push_screen(paste)
            await pilot.pause()
            assert str(paste.query_one("#paste-text-save", Button).label) == "Use text"
            paste.dismiss(None)
            await pilot.pause()

            diagnostics = DiagnosticsScreen(
                TaskDiagnostics(
                    title="Backup diagnostics",
                    blocks=(
                        TaskDiagnosticBlock(
                            title="Backup",
                            content="redacted",
                            sensitive_content="secret",
                        ),
                    ),
                )
            )
            await app.push_screen(diagnostics)
            await pilot.pause()
            assert str(diagnostics.query_one("#diagnostics-reveal-label", Label).content) == (
                "Show sensitive values"
            )

    asyncio.run(run())


def test_save_file_picker_requires_a_file_name_and_rejects_paths(tmp_path: Path) -> None:
    async def run() -> None:
        for size in ((60, 20), (80, 24)):
            app = EthernityApp()
            async with app.run_test(size=size) as pilot:
                picker = FilePickerScreen(
                    title="Save PDF",
                    prompt="Choose a PDF file.",
                    root=tmp_path,
                    mode=FilePickerMode.SAVE_FILE,
                )
                await app.push_screen(picker)
                await pilot.pause()

                choose = picker.query_one("#file-picker-choose", Button)
                error = picker.query_one("#file-picker-error", Static)
                assert choose.disabled
                assert str(error.content) == "Enter a file name."

                name = picker.query_one("#file-picker-name", Input)
                name.value = "nested/kit.pdf"
                await pilot.pause()

                body = picker.query_one("#file-picker-body")
                actions = picker.query_one("#file-picker-actions")
                assert choose.disabled
                assert str(error.content) == "Enter only a name. Remove any folder path."
                assert name.region.bottom <= error.region.y
                assert error.region.bottom <= body.region.bottom
                assert body.region.bottom <= actions.region.y
                assert actions.region.bottom <= size[1]

    asyncio.run(run())


def test_required_kit_save_file_picker_has_no_clear_noop() -> None:
    async def run() -> None:
        app = EthernityApp(kit_state=PrintKitTaskState(output_path=Path("kit.pdf")))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("6")
            await app.action_edit_output()
            await pilot.pause()

            assert isinstance(app.screen, FilePickerScreen)
            assert not list(app.screen.query("#file-picker-clear"))

    asyncio.run(run())


def test_open_file_picker_remove_action_updates_count_and_empty_feedback(tmp_path: Path) -> None:
    selected_path = tmp_path / "selected.txt"
    selected_path.write_text("fixture", encoding="utf-8")

    async def run() -> None:
        app = EthernityApp()
        picker = FilePickerScreen(
            title="Choose files",
            prompt="Select source files.",
            root=tmp_path,
            mode=FilePickerMode.OPEN_FILES,
            selected_paths=(selected_path,),
        )
        async with app.run_test(size=(120, 32)) as pilot:
            await app.push_screen(picker)
            await pilot.pause()

            remove = picker.query_one("#file-picker-remove", Button)
            assert remove.display
            assert str(picker.query_one("#file-picker-selected-title", Static).content) == (
                "1 selected"
            )

            await pilot.click("#file-picker-remove")
            await pilot.pause()

            assert not remove.display
            assert picker.query_one("#file-picker-choose", Button).disabled
            assert str(picker.query_one("#file-picker-error", Static).content) == (
                "Select at least one file."
            )

    asyncio.run(run())


def test_open_files_picker_has_no_folder_action(tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Choose files",
                prompt="Choose files only.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_FILES,
            )
            await app.push_screen(picker)
            await pilot.pause()

            assert not list(picker.query("#file-picker-current"))
            assert picker.query_one("#file-picker-actions").region.bottom <= 24

    asyncio.run(run())


def test_open_paths_picker_actions_fit_at_60_columns(tmp_path: Path) -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(60, 20)) as pilot:
            picker = FilePickerScreen(
                title="Choose paths",
                prompt="Choose files or folders.",
                root=tmp_path,
                mode=FilePickerMode.OPEN_PATHS,
            )
            await app.push_screen(picker)
            await pilot.pause()

            distinguishing_name = "recovery-material-final.pdf"
            picker.set_selected_paths((tmp_path / "a-very-long-folder-name" / distinguishing_name,))
            await pilot.pause()

            use_folder = picker.query_one("#file-picker-current", Button)
            location_row = picker.query_one("#file-picker-location-row")
            tree = picker.query_one("#file-picker-tree")
            body = picker.query_one("#file-picker-body")
            actions = picker.query_one("#file-picker-actions")
            selected = picker.query_one("#file-picker-selected", SelectionList)
            assert str(use_folder.label) == "Add folder"
            assert len(str(use_folder.label)) <= use_folder.region.width
            assert str(selected.get_option_at_index(0).prompt).startswith(distinguishing_name)
            assert distinguishing_name[:10] in selected.render_line(0).text
            assert location_row.region.bottom <= tree.region.y
            assert tree.content_region.height >= 3
            assert tree.region.bottom <= body.region.bottom
            assert body.region.bottom <= actions.region.y
            assert actions.region.bottom <= 20

    asyncio.run(run())


def test_save_file_picker_revalidates_when_base_folder_changes(tmp_path: Path) -> None:
    async def run() -> None:
        conflict_base = tmp_path / "conflict"
        conflict_base.mkdir()
        (conflict_base / "kit.pdf").mkdir()
        clear_base = tmp_path / "clear"
        clear_base.mkdir()

        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            picker = FilePickerScreen(
                title="Save PDF",
                prompt="Choose a PDF file.",
                root=conflict_base,
                mode=FilePickerMode.SAVE_FILE,
                save_name="kit.pdf",
            )
            await app.push_screen(picker)
            await pilot.pause()

            choose = picker.query_one("#file-picker-choose", Button)
            error = picker.query_one("#file-picker-error", Static)
            assert choose.disabled
            assert str(error.content) == (
                "That name belongs to an existing folder. Enter a file name."
            )

            picker.action_go_up()
            await pilot.pause()
            assert not choose.disabled
            assert str(error.content) == ""

            picker.set_selected_paths((conflict_base,))
            await pilot.pause()
            assert choose.disabled
            assert str(error.content) == (
                "That name belongs to an existing folder. Enter a file name."
            )

            picker.set_selected_paths((clear_base,))
            await pilot.pause()
            assert not choose.disabled
            assert str(error.content) == ""

    asyncio.run(run())


def test_print_kit_rejects_missing_or_non_pdf_output_paths(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-folder"
    parent_file.write_text("occupied", encoding="utf-8")
    cases = (
        (Path(""), "KIT_OUTPUT_REQUIRED"),
        (tmp_path, "KIT_OUTPUT_IS_DIRECTORY"),
        (tmp_path / "kit.txt", "KIT_OUTPUT_PDF_REQUIRED"),
        (parent_file / "kit.pdf", "KIT_OUTPUT_PARENT_INVALID"),
    )

    for output_path, expected_code in cases:
        state = PrintKitTaskState(output_path=output_path)

        validation = state.validate_task()

        assert not validation.ready
        assert [issue.code for issue in validation.issues] == [expected_code]
        assert validation.sections[0].status == "blocked"


def test_destructive_clear_has_no_bare_key_binding() -> None:
    assert all(getattr(binding, "key", None) != "c" for binding in APP_BINDINGS)


def test_escape_closes_navigation_drawer_without_affecting_closed_shell() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.click("#nav-strip")
            await pilot.pause()
            assert app._nav_drawer_open

            await pilot.press("escape")
            await pilot.pause()
            assert not app._nav_drawer_open

            await pilot.press("escape")
            await pilot.pause()
            assert app.is_running
            assert app.active_task == "backup"

    asyncio.run(run())


def test_action_bar_uses_screen_breakpoints_after_resize() -> None:
    async def run() -> None:
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[Path("secrets.txt")],
                output_dir=Path("backup-out"),
            )
        )
        async with app.run_test(size=(120, 30)) as pilot:
            action_row = app.query_one("#canvas-action-row")
            primary = app.query_one("#canvas-primary", Button)
            full_label = str(primary.label)
            assert app.screen.has_class("-ethernity-standard")
            assert full_label.startswith("Review")

            await pilot.resize_terminal(80, 24)
            await pilot.pause()

            assert app.screen.has_class("-ethernity-narrow")
            assert app.screen.has_class("-ethernity-short")
            assert str(primary.label) == full_label
            assert primary.region.right == action_row.region.right
            assert primary.region.width >= action_row.region.width - 19

            await pilot.resize_terminal(120, 30)
            await pilot.pause()

            assert app.screen.has_class("-ethernity-standard")
            assert str(primary.label) == full_label

    asyncio.run(run())


def test_settings_advanced_tab_exposes_direct_traversable_controls() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("7")
            await pilot.pause()
            app.query_one("#settings-tabs", TabbedContent).active = "settings-pane-advanced"
            await pilot.pause()

            assert not list(app.query("#settings-advanced-panel"))
            control = app.query_one("#setting-control-qr_error", Select)
            assert control.has_class("settings-control")

            control.focus()
            await pilot.pause()
            assert app.screen.focused is control

    asyncio.run(run())


def test_workspace_radio_set_synchronizes_through_native_adapter() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            choice_set = app.query_one(
                "#workspace-backup-recovery-method",
                WorkspaceRadioSet,
            )
            choices = (
                WorkspaceChoice("recommended_shards", "Recommended", False),
                WorkspaceChoice("single_phrase", "Single phrase", True),
                WorkspaceChoice("custom_shards", "Custom", False),
            )

            choice_set.sync_choices(choices)
            await pilot.pause()

            assert choice_set.selected_key == "single_phrase"
            assert choice_set.query_one(
                "#workspace-backup-recovery-single_phrase",
                RadioButton,
            ).value

            choice_set.sync_choices(
                tuple(WorkspaceChoice(choice.key, choice.label, False) for choice in choices)
            )
            await pilot.pause()

            assert choice_set.selected_key is None

    asyncio.run(run())


def test_workspace_radio_set_accepts_keyboard_selection() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            choice_set = app.query_one(
                "#workspace-backup-recovery-method",
                WorkspaceRadioSet,
            )
            choice_set.focus()

            await pilot.press("down", "down", "space")
            await pilot.pause()

            assert app.backup_state.recovery_method == "custom_shards"
            assert choice_set.selected_key == "custom_shards"

    asyncio.run(run())


def test_workspace_path_lists_are_read_only_and_render_markup_literally() -> None:
    async def run() -> None:
        input_path = Path("[red]secret [docs](target.md)\n## injected.txt")
        output_path = Path("[red]output [docs](target.md)")
        app = EthernityApp(
            backup_state=BackupTaskState(
                input_paths=[input_path],
                output_dir=output_path,
            )
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()

            path_list = app.query_one("#backup-files-list", WorkspacePathList)
            prompt = str(path_list.get_option_at_index(0).prompt)
            rendered_paths = "\n".join(path_list.render_line(index).text for index in range(3))
            assert str(input_path) in prompt
            assert "[red]secret [docs](target.md)" in rendered_paths
            assert "## injected.txt" in rendered_paths
            assert not list(path_list.query("SelectionListItem"))

            output = app.query_one("#backup-output-value", Static)
            assert str(output.content) == str(output_path)
            assert "[red]output [docs](target.md)" in output.render_line(0).text

    asyncio.run(run())


def test_review_renders_every_dynamic_field_as_literal_text() -> None:
    def dangerous(marker: str) -> str:
        return f"[red]{marker}[/red] [link-{marker}](target.md)\n## injected-{marker}"

    read_path = Path(dangerous("read-path"))
    output_path = Path(dangerous("output-path"))
    validation = TaskValidation(
        sections=(
            TaskSection(
                key="input",
                title=dangerous("section-title"),
                status="ready",
                summary=dangerous("section-summary"),
            ),
        ),
        issues=(TaskIssue(code="CHECK", message=dangerous("issue"), severity="warning"),),
    )
    preview = TaskPreview(
        title=dangerous("preview-title"),
        items=(
            PreviewItem(
                label=dangerous("item-label"),
                detail=dangerous("item-detail"),
            ),
        ),
    )
    plan = TaskExecutionPlan(
        summary=dangerous("plan-summary"),
        read_paths=(read_path,),
        output_paths=(output_path,),
        safety_notes=(dangerous("safety-note"),),
        trust_notes=(dangerous("trust-note"),),
        recovery_notes=(dangerous("recovery-note"),),
    )
    screen = ReviewTaskScreen(
        title=dangerous("screen-title"),
        validation=validation,
        preview=preview,
        plan=plan,
        execute_label=dangerous("execute-label"),
    )
    expected_markers = (
        "issue",
        "plan-summary",
        "read-path",
        "output-path",
        "safety-note",
        "trust-note",
        "recovery-note",
        "preview-title",
        "item-label",
        "item-detail",
        "execute-label",
    )

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            rendered_blocks = "\n".join(str(block.content) for block in screen.query(Static))
            rendered_blocks += f"\n{screen.query_one('#review-execute', Button).label}"
            for marker in expected_markers:
                expected = {
                    "read-path": str(read_path),
                    "output-path": str(output_path),
                }.get(marker, dangerous(marker))
                assert expected in rendered_blocks

            issue = screen.query_one(".review-notice", Static)
            issue_lines = "\n".join(
                issue.render_line(index).text for index in range(issue.region.height)
            )
            assert "[red]issue[/red]" in issue_lines
            assert "## injected-issue" in issue_lines
            assert not list(screen.query(MarkdownViewer))

    asyncio.run(run())


def test_result_renders_messages_and_newline_paths_without_markup() -> None:
    dangerous = "[red]literal[/red] [docs](target.md)"
    output_path = Path(f"{dangerous}\n## injected.pdf")
    screen = TaskResultScreen(
        task="backup",
        title=dangerous,
        result=TaskExecutionResult(
            ok=False,
            message=dangerous,
            output_paths=(output_path,),
        ),
        recoverable_errors=(TaskIssue(code="FIX", message=dangerous),),
    )

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            title = screen.query_one("#result-title", Static)
            status = screen.query_one("#result-status", Static)
            assert title.render_line(0).text == "Backup failed"
            assert dangerous in status.render_line(0).text

            path_list = screen.query_one("#result-output-paths", OptionList)
            assert path_list.option_count == 1
            assert str(path_list.get_option_at_index(0).prompt) == str(output_path)
            rendered_path = "\n".join(
                path_list.render_line(index).text for index in range(path_list.region.height)
            )
            assert str(output_path).splitlines()[0] in rendered_path
            assert "## injected.pdf" in rendered_path

            issue_line = next(
                line
                for line in screen.query(".result-summary-line").results(Static)
                if str(line.content) == dangerous
            )
            assert dangerous in issue_line.render_line(0).text

    asyncio.run(run())


def test_help_avoids_duplicate_intro_and_focuses_scroll_content() -> None:
    async def run() -> None:
        content = build_help_content(task="restore")
        markdown = _help_markdown(content)
        assert content.title == "Restore files"
        assert content.mode.summary not in markdown
        assert "## Restore files" not in markdown
        assert markdown.count("### ") == 3
        assert "Keyboard" not in markdown

        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            screen = HelpScreen(content)
            await app.push_screen(screen)
            await pilot.pause()

            viewer = screen.query_one("#help-body", MarkdownViewer)
            shortcuts = screen.query_one("#help-shortcuts", Static)
            assert screen.focused is viewer.document
            assert "Tab/Shift+Tab: Focus" in str(shortcuts.content)
            assert "h/l: Switch pane" in str(shortcuts.content)
            assert "Ctrl+P: Actions" in str(shortcuts.content)
            assert screen.query_one("#help-actions").region.bottom <= 24

    asyncio.run(run())


def test_review_is_structured_and_scrollable_at_80_columns() -> None:
    async def run() -> None:
        validation = TaskValidation(
            sections=(
                TaskSection(
                    key="input",
                    title="Input",
                    status="ready",
                    summary="One source",
                ),
            )
        )
        preview = TaskPreview(
            title="Preview",
            items=(PreviewItem(label="Output", detail="kit.pdf"),),
        )
        plan = TaskExecutionPlan(
            summary="Create output",
            output_paths=(Path("kit.pdf"),),
            safety_notes=("- Existing output may be replaced.",),
        )
        screen = ReviewTaskScreen(
            title="Create recovery kit PDF",
            validation=validation,
            preview=preview,
            plan=plan,
            execute_label="Create PDF",
        )
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            assert not list(screen.query(MarkdownViewer))
            assert screen.focused is screen.query_one("#review-execute", Button)
            detail_lines = [
                str(line.content) for line in screen.query(".review-detail-line").results(Static)
            ]
            assert "Existing output may be replaced." in detail_lines
            assert "- Existing output may be replaced." not in detail_lines
            assert screen.query_one("#review-actions").region.bottom <= 24
            header_lines = [
                str(line.content)
                for line in screen.query_one("#review-header").query(Static).results(Static)
            ]
            assert header_lines == ["Create recovery kit PDF"]

    asyncio.run(run())


def test_review_readiness_never_contradicts_validation_errors() -> None:
    invalid_validation = TaskValidation(
        sections=(
            TaskSection(
                key="input",
                title="Input",
                status="ready",
                summary="Looks complete",
            ),
        ),
        issues=(
            TaskIssue(
                code="INPUT_INVALID",
                message="Input is invalid.",
                section="input",
            ),
        ),
    )
    screen = ReviewTaskScreen(
        title="Review",
        validation=invalid_validation,
        preview=TaskPreview(title="Preview"),
        plan=TaskExecutionPlan(summary="Run", writes_files=False),
        execute_label="Run",
    )

    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            assert not list(screen.query("#review-status"))
            assert screen.query_one("#review-execute", Button).disabled
            assert "Input is invalid." in "\n".join(
                str(line.content) for line in screen.query(".review-notice").results(Static)
            )

    asyncio.run(run())


def test_review_header_and_actions_fit_at_60_by_20() -> None:
    async def run() -> None:
        screen = ReviewTaskScreen(
            title="Create replacement recovery sheets",
            validation=TaskValidation(
                sections=(
                    TaskSection(
                        key="output",
                        title="Output",
                        status="ready",
                        summary="Ready",
                    ),
                )
            ),
            preview=TaskPreview(title="Preview"),
            plan=TaskExecutionPlan(summary="Create sheets"),
            execute_label="Create sheets",
        )
        app = EthernityApp()
        async with app.run_test(size=(60, 20)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            title = screen.query_one("#review-title", Static)
            assert len(str(title.content)) <= title.region.width
            assert not list(screen.query("#review-status"))
            assert screen.query_one("#review-actions").region.bottom <= 20

    asyncio.run(run())


def test_large_result_keeps_actions_visible_at_80_by_24(tmp_path: Path) -> None:
    async def run() -> None:
        result = TaskExecutionResult(
            ok=True,
            message="Backup complete.",
            output_paths=tuple(tmp_path / f"backup-{index}.pdf" for index in range(20)),
        )
        screen = TaskResultScreen(task="backup", title="Create a backup", result=result)
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            modal = screen.query_one("#result-modal")
            body = screen.query_one("#result-body")
            actions = screen.query_one("#result-actions")
            assert modal.region.height <= 24
            assert body.region.bottom <= actions.region.y
            assert actions.region.bottom <= 24

    asyncio.run(run())


def test_add_files_result_shows_version_history_and_storage_guidance(monkeypatch) -> None:
    copied_fingerprints: list[str] = []

    def fake_copy_to_clipboard(self: EthernityApp, text: str) -> None:
        copied_fingerprints.append(text)

    monkeypatch.setattr(EthernityApp, "copy_to_clipboard", fake_copy_to_clipboard)

    async def run() -> None:
        fingerprint = "ab" * 32
        screen = TaskResultScreen(
            task="add_files",
            title="Add files",
            result=TaskExecutionResult(
                ok=True,
                message="Update complete.",
                details=(
                    TaskResultDetail(
                        key="doc_hash",
                        label="New full fingerprint",
                        value=fingerprint,
                    ),
                ),
                next_steps=("Keep the original backup and every earlier update with this update.",),
            ),
        )
        app = EthernityApp()
        async with app.run_test(size=(90, 28)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            metadata = "\n".join(
                str(line.content)
                for line in screen.query("#result-metadata .result-summary-line").results(Static)
            )
            summary = "\n".join(
                str(line.content)
                for line in screen.query("#result-next-steps .result-summary-line").results(Static)
            )
            assert "New full fingerprint" in metadata
            assert fingerprint in metadata
            assert "Keep the original backup and every earlier update" in summary
            copy_button = screen.query_one("#result-copy-fingerprint", Button)
            assert str(copy_button.label) == "Copy fingerprint"

            await pilot.click("#result-copy-fingerprint")
            await pilot.pause()

            assert copied_fingerprints == [fingerprint]

    asyncio.run(run())


def test_result_fingerprint_action_requires_a_full_document_hash() -> None:
    invalid_hash = TaskResultScreen(
        task="add_files",
        title="Add files",
        result=TaskExecutionResult(
            ok=True,
            message="Update complete.",
            details=(TaskResultDetail(key="doc_hash", label="Fingerprint", value="ab" * 31),),
        ),
    )
    document_id = TaskResultScreen(
        task="add_files",
        title="Add files",
        result=TaskExecutionResult(
            ok=True,
            message="Update complete.",
            details=(TaskResultDetail(key="doc_id", label="Document ID", value="ab" * 32),),
        ),
    )
    failed_update = TaskResultScreen(
        task="add_files",
        title="Add files",
        result=TaskExecutionResult(
            ok=False,
            message="Update failed.",
            details=(TaskResultDetail(key="doc_hash", label="Fingerprint", value="ab" * 32),),
        ),
    )

    assert invalid_hash._document_fingerprint() is None
    assert document_id._document_fingerprint() is None
    assert failed_update._document_fingerprint() is None


def test_failure_result_leads_with_actionable_error_and_partial_write_location(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        partial_path = tmp_path / "recovered" / "partial.txt"
        screen = TaskResultScreen(
            task="restore",
            title="Restore files",
            result=TaskExecutionResult(
                ok=False,
                message="Worker exited with status 1.",
                output_paths=(partial_path,),
            ),
            error="Verify the scanned pages before restoring again.",
            error_detail="Signature verification failed for scanned page 4.",
            recoverable_errors=(
                TaskIssue(
                    code="AUTH_REQUIRED",
                    message="Choose the expected trust source.",
                    section="authentication",
                ),
            ),
        )
        app = EthernityApp()
        async with app.run_test(size=(120, 32)) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            assert str(screen.query_one("#result-status", Static).content) == (
                "Verify the scanned pages before restoring again."
            )
            assert str(screen.query_one("#result-output-title", Static).content) == (
                "Partial files may remain"
            )
            assert str(partial_path.parent) in str(
                screen.query_one("#result-partial-warning", Static).content
            )
            return_action = screen.query_one("#result-return", Button)
            assert str(return_action.label) == "Edit signature check"
            assert screen.focused is return_action

            details = screen.query_one("#result-details-panel", Collapsible)
            assert details.collapsed
            details.collapsed = False
            await pilot.pause()
            assert "Signature verification failed for scanned page 4." in "\n".join(
                line.text for line in screen.query_one("#result-log", RichLog).lines
            )

    asyncio.run(run())


def test_result_variants_keep_content_and_actions_visible_at_small_sizes(
    tmp_path: Path,
) -> None:
    async def check_screen(
        screen: TaskResultScreen,
        size: tuple[int, int],
        *,
        partial_path: Path | None = None,
    ) -> None:
        app = EthernityApp()
        async with app.run_test(size=size) as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            body = screen.query_one("#result-body")
            actions = screen.query_one("#result-actions")
            title = screen.query_one("#result-title", Static)
            assert body.region.bottom <= actions.region.y
            assert actions.region.bottom <= size[1]
            assert len(str(title.content)) <= title.region.width * title.region.height
            statuses = list(screen.query("#result-status").results(Static))
            assert bool(statuses) is not screen._is_success()
            if statuses:
                status = statuses[0]
                assert len(str(status.content)) <= status.region.width * status.region.height
            if partial_path is not None:
                assert "Partial files may remain" == str(
                    screen.query_one("#result-output-title", Static).content
                )
                assert str(partial_path.parent) in str(
                    screen.query_one("#result-partial-warning", Static).content
                )
                path_list = screen.query_one("#result-output-paths", OptionList)
                assert str(path_list.get_option_at_index(0).prompt) == str(partial_path)

    for size in ((80, 24), (60, 20)):
        asyncio.run(
            check_screen(
                TaskResultScreen(
                    task="kit",
                    title="Create recovery kit PDF",
                    result=TaskExecutionResult(ok=True, message="Complete.", output_paths=()),
                ),
                size,
            )
        )
        asyncio.run(
            check_screen(
                TaskResultScreen(
                    task="replace_recovery_docs",
                    title="Create replacement recovery sheets after validating loaded backup",
                    error="The replacement write could not be completed safely.",
                    recoverable_errors=tuple(
                        TaskIssue(
                            code=f"FIX_{index}",
                            message=f"Correct recovery input {index} before retrying.",
                        )
                        for index in range(8)
                    ),
                ),
                size,
            )
        )

        partial_path = tmp_path / "partial-sheet.pdf"
        partial_screen = TaskResultScreen(
            task="replace_recovery_docs",
            title="Create replacement recovery sheets",
            result=TaskExecutionResult(
                ok=False,
                message="Stopped after reporting partial output.",
                output_paths=(partial_path,),
            ),
        )
        asyncio.run(
            check_screen(
                partial_screen,
                size,
                partial_path=partial_path,
            )
        )


def test_restore_expert_controls_live_in_advanced_disclosure() -> None:
    async def run() -> None:
        app = EthernityApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("2")
            await pilot.pause()

            panel = app.query_one("#restore-advanced-panel", Collapsible)
            assert panel.collapsed
            assert "Trusted signatures required" in panel.title
            assert panel.query_one("#workspace-restore-expected-head", Button)
            assert panel.query_one("#workspace-restore-auth-policy")
            assert not list(panel.query("#workspace-restore-payloads"))
            assert not list(panel.query("#workspace-restore-target-fingerprint"))
            assert app.query_one("#workflow-restore-source-body-methods") not in panel.query("*")
            assert app.query_one(
                "#workflow-restore-destination-body-action",
                Button,
            ) not in panel.query(Button)

    asyncio.run(run())
