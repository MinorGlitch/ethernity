from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button, OptionList, Static

from ethernity.app.application import EthernityApp
from ethernity.app.screens import task_result
from ethernity.tasks.models import TaskExecutionResult, TaskResultDetail
from tests.support.pilot import wait_for_condition


@pytest.mark.parametrize(
    "size,theme",
    [((160, 60), "dark"), ((120, 32), "light"), ((80, 24), "dark"), ((60, 20), "light")],
)
def test_completion_layout_keeps_actions_reachable_and_original_paths(
    size: tuple[int, int], theme: str, monkeypatch
) -> None:
    folder = Path("/archive/family-records/long-folder-name/backup-12345678")
    paths = (folder / "backup.pdf", folder / "sheets" / "recovery.pdf")
    copied: list[str] = []
    opened: list[object] = []
    monkeypatch.setattr(task_result, "open_documents", opened.append)
    monkeypatch.setattr(task_result, "open_folder", opened.append)
    result = TaskExecutionResult(
        status="succeeded",
        message="Backup created.",
        output_paths=paths,
        recovery_check_paths=paths,
        details=(
            TaskResultDetail(key="doc_hash", label="Fingerprint", value="ab" * 32),
            TaskResultDetail(key="printed_pages", label="PDF pages", value=5),
        ),
    )

    async def run() -> None:
        app = EthernityApp()
        app.theme = f"ethernity-{theme}"
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        screen = task_result.TaskResultScreen(
            task="backup", title="Create backup", result=result, context_actions_enabled=True
        )
        async with app.run_test(size=size) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            body = screen.query_one("#result-body", VerticalScroll)
            footer = screen.query_one("#result-actions")
            assert screen.query_one("#result-modal").region.width <= 100
            assert body.region.bottom <= footer.region.y < footer.region.bottom < size[1]
            assert body.max_scroll_x == 0
            assert sum(str(node.content) == str(folder) for node in screen.query(Static)) == 1
            path_list = screen.query_one("#result-output-paths", OptionList)
            assert [str(path_list.get_option_at_index(i).prompt) for i in range(2)] == [
                "backup.pdf",
                str(Path("sheets") / "recovery.pdf"),
            ]

            buttons = set(screen.query(Button).results(Button))
            visited = set()
            for _ in range(len(screen.focus_chain) + 1):
                await pilot.press("tab")
                button = screen.focused
                if button not in buttons:
                    continue
                visited.add(button)
                owner = footer if button.id == "result-close" else body
                await wait_for_condition(
                    pilot,
                    lambda owner=owner, button=button: owner.region.contains_region(button.region),
                    f"{button.id} to scroll into view",
                )
                assert owner.region.x <= button.region.x < button.region.right <= owner.region.right
                assert (
                    owner.region.y <= button.region.y < button.region.bottom <= owner.region.bottom
                )
                assert button.region.height == screen.query_one("#result-close").region.height
            assert visited == buttons

            for button_id in ("copy-paths", "open-folder", "open-documents"):
                screen.query_one(f"#result-{button_id}", Button).press()
                await pilot.pause()
            assert (copied, opened) == (["\n".join(str(path) for path in paths)], [folder, paths])

            screen.set_context_action_running("test_recovery")
            await pilot.pause()
            checks = screen.query_one("#result-document-checks", Static)
            assert body.region.y <= checks.region.y < checks.region.bottom <= body.region.bottom
            assert screen.query_one("#result-test-recovery", Button).disabled
            screen.show_context_action_result(
                "test_recovery", "Generated PDFs passed.", success=True
            )
            await pilot.pause()
            assert checks.has_class("success")
            assert body.region.y <= checks.region.y < checks.region.bottom <= body.region.bottom
            assert not screen.query_one("#result-test-recovery", Button).disabled

    asyncio.run(run())
