from __future__ import annotations

from textual.widgets import Static

__all__ = ["update_static_text"]


def update_static_text(static: Static, content: str) -> None:
    """Update a Static widget only when its rendered text changed."""

    if str(static.content) != content:
        static.update(content)
