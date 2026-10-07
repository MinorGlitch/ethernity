"""Shared stylesheet setup, including Textual's lazily created scrollbars."""

from pathlib import Path

from textual.app import App
from textual.scrollbar import ScrollBar
from textual.widget import Widget


class StyledApp(App[None]):
    """Apply the same control skins to mounted widgets and native scrollbars."""

    CSS_PATH = [
        Path(__file__).with_name(name) for name in ("theme.tcss", "workbench.tcss", "dialogs.tcss")
    ]

    def _start_widget(self, parent: Widget, widget: Widget) -> None:
        # Native scrollbars use this path instead of normal widget registration,
        # which applies the stylesheet. Keep that framework integration here.
        super()._start_widget(parent, widget)
        if isinstance(widget, ScrollBar):
            widget.add_class("-ethernity-vertical" if widget.vertical else "-ethernity-horizontal")
            self.stylesheet.apply(widget)
