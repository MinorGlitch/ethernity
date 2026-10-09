from __future__ import annotations

from typing import Any, Self

from textual.widget import Widget
from textual.widgets import Collapsible

ADVANCED_COLLAPSED_SYMBOL = "+"
ADVANCED_EXPANDED_SYMBOL = "-"
COLLAPSIBLE_TITLE_SELECTOR = "CollapsibleTitle"


class AppCollapsible(Collapsible):
    """Project-styled collapsible that focuses its actual toggle control."""

    def __init__(
        self,
        *children: Widget,
        title_classes: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(*children, **kwargs)
        self._title_classes = tuple(title_classes.split())
        self._label = self.title
        self._summary = ""

    def set_heading(self, label: str, summary: str = "") -> None:
        self._label = label
        self._summary = summary
        self._refresh_heading()

    def _refresh_heading(self) -> None:
        self.title = (
            f"{self._label} - {self._summary}" if self.collapsed and self._summary else self._label
        )

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            self._refresh_heading()

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        if event.collapsible is self:
            self._refresh_heading()

    def on_mount(self) -> None:
        title = next(iter(self.query(COLLAPSIBLE_TITLE_SELECTOR)), None)
        if title is not None:
            title.add_class(*self._title_classes)

    def focus(self, scroll_visible: bool = True) -> Self:
        title = next(iter(self.query(COLLAPSIBLE_TITLE_SELECTOR)), None)
        if title is None:
            return super().focus(scroll_visible=scroll_visible)
        title.focus(scroll_visible=scroll_visible)
        return self


def collapsible_panel(
    panel_id: str,
    title: str,
    *,
    classes: str,
    title_classes: str,
) -> AppCollapsible:
    return AppCollapsible(
        id=panel_id,
        title=title,
        collapsed=True,
        collapsed_symbol=ADVANCED_COLLAPSED_SYMBOL,
        expanded_symbol=ADVANCED_EXPANDED_SYMBOL,
        classes=classes,
        title_classes=title_classes,
    )


def sync_collapsible_panel(
    widget: Widget,
    panel_id: str,
    *,
    expanded: bool,
    title: str,
    summary: str = "",
) -> None:
    panel = widget.query_one(f"#{panel_id}", AppCollapsible)
    panel.set_heading(title, summary)
    collapsed = not expanded
    if panel.collapsed == collapsed:
        return
    with panel.prevent(Collapsible.Collapsed, Collapsible.Expanded):
        panel.collapsed = collapsed
    panel.set_heading(title, summary)
