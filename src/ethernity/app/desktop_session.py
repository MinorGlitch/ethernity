"""Desktop activity and shutdown carried over Textual's existing process pipe."""

from __future__ import annotations

from dataclasses import dataclass

from textual.drivers.web_driver import WebDriver
from textual.message import Message


@dataclass(frozen=True)
class DesktopStatus:
    text: str = "Ready"
    busy: bool = False


class DesktopShutdownRequested(Message):
    """Finish any active write, then close this browser session."""


class DesktopDriver(WebDriver):
    def on_meta(self, packet_type: str, payload: dict[str, object]) -> None:
        if packet_type == "ethernity.shutdown":
            self._app.post_message(DesktopShutdownRequested())
        else:
            super().on_meta(packet_type, payload)

    def publish_status(self, text: str, *, busy: bool) -> None:
        self.write_meta({"type": "ethernity.status", "text": text, "busy": busy})

    def request_quit(self) -> None:
        self.write_meta({"type": "ethernity.quit"})
