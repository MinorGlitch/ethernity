"""Isolated controls with the production styles, themes, and breakpoints."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Footer

from ethernity.app.application import ETHERNITY_DARK_THEME, ETHERNITY_LIGHT_THEME, EthernityApp
from ethernity.app.styling import StyledApp


class WidgetApp(StyledApp):
    HORIZONTAL_BREAKPOINTS = EthernityApp.HORIZONTAL_BREAKPOINTS
    VERTICAL_BREAKPOINTS = EthernityApp.VERTICAL_BREAKPOINTS

    def __init__(self, *widgets: Widget, theme: str = "ethernity-dark") -> None:
        super().__init__()
        self.register_theme(ETHERNITY_DARK_THEME)
        self.register_theme(ETHERNITY_LIGHT_THEME)
        self.theme = theme
        self._test_widgets = widgets

    def compose(self) -> ComposeResult:
        yield from self._test_widgets
        yield Footer()
