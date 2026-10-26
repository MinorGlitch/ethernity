"""Opening a sample is asynchronous and scoped to its visible control."""

import asyncio
from pathlib import Path
from threading import Event

import pytest
from textual.app import App, ComposeResult

from ethernity.app.widgets import design_preview
from tests.support.app import run_app_test
from tests.support.pilot import wait_for_condition


class PreviewApp(App[None]):
    def compose(self) -> ComposeResult:
        yield design_preview.DesignPreview(id="preview")


@pytest.mark.parametrize("hide_before_ready", [False, True])
def test_preview_opens_selected_sample_only_while_visible(monkeypatch, hide_before_ready) -> None:
    started, release = Event(), Event()
    captured, opened = [], []

    def render(design, paper, directory):
        captured.append((design, paper.name))
        started.set()
        assert release.wait(10)
        return Path("sample.pdf")

    monkeypatch.setattr(design_preview, "create_design_preview", render)
    monkeypatch.setattr(design_preview, "open_documents", opened.append)

    async def run() -> None:
        app = PreviewApp()
        async with run_app_test(app) as pilot:
            button = app.query_one(design_preview.DesignPreview)
            button.set_layout("ledger", "LETTER")
            try:
                await pilot.click(button)
                await wait_for_condition(pilot, started.is_set, "preview render to start")
                assert button.disabled
                assert captured == [("ledger", "LETTER")]
                button.display = not hide_before_ready
            finally:
                release.set()
            await wait_for_condition(pilot, lambda: not button.disabled, "preview to finish")
            assert opened == ([] if hide_before_ready else [(Path("sample.pdf"),)])

    asyncio.run(run())


def test_preview_error_leaves_button_usable(monkeypatch) -> None:
    def render(*args):
        raise OSError("Sample is unavailable")

    monkeypatch.setattr(design_preview, "create_design_preview", render)

    async def run() -> None:
        app = PreviewApp()
        async with run_app_test(app) as pilot:
            button = app.query_one(design_preview.DesignPreview)
            await pilot.click(button)
            await app.workers.wait_for_complete()
            assert not button.disabled
            assert any("Sample is unavailable" in n.message for n in app._notifications)

    asyncio.run(run())
