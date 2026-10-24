"""Synthetic scroll content for the real browser protocol regression test."""

from textual.widgets import Static, TextArea

from ethernity.app.application import EthernityApp
from ethernity.app.screens.paste_text import PasteTextScreen


class ScrollTestApp(EthernityApp):
    def on_mount(self) -> None:
        self.call_after_refresh(self.open_editor)

    async def open_editor(self) -> None:
        screen = PasteTextScreen(
            title="SCROLL=0",
            prompt="Synthetic text",
            value="\n".join(f"Line {i}" for i in range(300)),
        )
        await self.push_screen(screen)
        field = screen.query_one(TextArea)
        title = screen.query_one("#paste-text-title", Static)
        self.watch(field, "scroll_y", lambda value: title.update(f"SCROLL={value:.0f}"))


if __name__ == "__main__":
    ScrollTestApp().run()
