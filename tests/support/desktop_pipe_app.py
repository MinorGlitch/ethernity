"""Exercise Textual's blocking Windows pipe reader on every test platform."""

from textual.drivers._input_reader_windows import InputReader

from ethernity.app.application import EthernityApp
from ethernity.app.desktop_session import DesktopDriver


class WindowsPipeDriver(DesktopDriver):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Use the real Windows reader: closing its event cannot interrupt os.read.
        self._input_reader = InputReader()


if __name__ == "__main__":
    app = EthernityApp()
    app.driver_class = WindowsPipeDriver
    app.run()
