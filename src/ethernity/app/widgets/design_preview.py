"""Open a sample PDF without blocking the form or reading selected files."""

from __future__ import annotations

import asyncio

from textual.widgets import Button

from ethernity.app.output_paths import open_documents
from ethernity.core.app_paths import user_cache_dir_path
from ethernity.page_sizes import resolve_paper_size
from ethernity.tasks.design_preview import create_design_preview


class DesignPreview(Button):
    def __init__(self, *, id: str) -> None:
        super().__init__("Preview design", id=id, tooltip="Open a sample PDF in your PDF viewer")
        self._design = "sentinel"
        self._paper = "A4"

    def set_layout(self, design: str, paper: str) -> None:
        self._design, self._paper = design, paper

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self:
            event.stop()
            self.disabled = True
            self.run_worker(self._open_preview(), name="design-preview", exclusive=True)

    async def _open_preview(self) -> None:
        design, paper = self._design, resolve_paper_size(self._paper)
        try:
            path = await asyncio.to_thread(
                create_design_preview, design, paper, user_cache_dir_path() / "design-previews"
            )
            if (
                self.is_attached
                and self.is_on_screen
                and self.visible
                and all(node.display for node in self.ancestors_with_self)
            ):
                open_documents((path,))
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(f"Could not open design preview: {error}", severity="error")
        finally:
            if self.is_attached:
                self.disabled = False
