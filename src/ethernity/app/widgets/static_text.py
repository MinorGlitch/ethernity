from __future__ import annotations

from pathlib import Path

from textual.content import Content
from textual.widgets import Static

from ethernity.tasks.file_summary import display_path

__all__ = ["PathLabel", "update_static_text"]


def update_static_text(static: Static, content: str) -> None:
    """Update a Static widget only when its rendered text changed."""

    if str(static.content) != content:
        static.update(content)


class PathLabel(Static):
    """Keep the filename visible as the field changes width; expose the full path on hover."""

    def set_path(self, path: str, summary: str) -> None:
        self.tooltip = path or None
        update_static_text(self, summary)

    def render(self) -> Content:
        text = str(self.content)
        width = self.content_size.width
        if 0 < width < len(text):
            path = str(self.tooltip or text)
            text = display_path(path, max_chars=width)
            filename = Path(path).name
            if filename and len(filename) <= width and not text.endswith(filename):
                text = f".../{filename}" if len(filename) + 4 <= width else filename
        return Content.from_text(text, markup=False)
