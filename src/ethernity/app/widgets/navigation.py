from __future__ import annotations

from textual.containers import Grid
from textual.widgets import Button


class NavigationBar(Grid):
    """Wrap navigation into balanced rows without truncating button labels."""

    DEFAULT_CSS = """
    NavigationBar {
        height: auto;
        grid-rows: auto;
    }
    """

    def on_mount(self) -> None:
        self.reflow()

    def on_resize(self) -> None:
        self.reflow()

    def reflow(self) -> None:
        buttons = [child for child in self.children if isinstance(child, Button) and child.display]
        available = self.content_size.width
        if not buttons or available <= 0:
            return
        widths = [
            button.get_content_width(self.content_size, self.screen.size)
            + button.styles.gutter.width
            + button.styles.margin.width
            for button in buttons
        ]
        for rows in range(1, len(buttons) + 1):
            columns = (len(buttons) + rows - 1) // rows
            column_widths = [max(widths[column::columns]) for column in range(columns)]
            if sum(column_widths) <= available or columns == 1:
                self.styles.grid_size_columns = columns
                self.styles.grid_columns = " ".join(str(width) for width in column_widths)
                break
