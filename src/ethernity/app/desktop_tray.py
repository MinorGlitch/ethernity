"""Native desktop controls; the browser server runs on its own asyncio loop."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
import webbrowser
from collections.abc import Callable

from aiohttp import web
from PIL import Image

from ethernity.app.browser import HOST, ICON_PATH, LocalServer
from ethernity.app.desktop_session import DesktopStatus

if sys.platform in {"darwin", "win32"}:
    import pystray
if sys.platform == "darwin":
    from PyObjCTools.AppHelper import callAfter


def _native_call(callback: Callable[[], None]) -> None:
    if sys.platform == "darwin":
        callAfter(callback)
    else:
        callback()


class DesktopTray:
    def __init__(self) -> None:
        if sys.platform not in {"darwin", "win32"}:
            raise RuntimeError("The desktop launcher supports Windows and macOS.")
        self.status = DesktopStatus("Starting")
        self.server: LocalServer | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.error: Exception | None = None
        with Image.open(ICON_PATH) as source:
            self.idle_icon = source.copy()
        with Image.open(ICON_PATH.with_name("activity.png")) as source:
            size = source.height
            self.frames = tuple(
                source.crop((x, 0, x + size, size)) for x in range(0, source.width, size)
            )
        self.activity = asyncio.Event()
        self.icon = pystray.Icon(
            "Ethernity",
            self.idle_icon,
            "Ethernity - Starting",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: self.status.text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Open Ethernity",
                    self.open_browser,
                    default=True,
                    enabled=lambda _item: self.server is not None and not self.server.quitting,
                ),
                pystray.MenuItem(
                    "Quit Ethernity",
                    self.quit,
                    enabled=lambda _item: self.server is not None and not self.server.quitting,
                ),
            ),
        )

    def update(self, status: DesktopStatus) -> None:
        if status == self.status:
            return
        self.status = status
        if status.busy:
            self.activity.set()
        else:
            self.activity.clear()

        def apply() -> None:
            self.icon.title = f"Ethernity - {self.status.text}"
            if not self.status.busy:
                self.icon.icon = self.idle_icon
            self.icon.update_menu()

        _native_call(apply)

    async def animate(self) -> None:
        frame = 0
        while True:
            await self.activity.wait()
            image = self.frames[frame % len(self.frames)]

            def draw(image: Image.Image = image) -> None:
                self.icon.icon = image if self.status.busy else self.idle_icon

            _native_call(draw)
            frame += 1
            await asyncio.sleep(0.08)

    def open_browser(self) -> None:
        if self.loop is not None and self.server is not None:
            asyncio.run_coroutine_threadsafe(self._open_browser(), self.loop)

    async def _open_browser(self) -> None:
        server = self.server
        if server is None or server.quitting:
            return
        try:
            opened = await asyncio.to_thread(webbrowser.open, server.browser_url)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            self.update(DesktopStatus("Could not open browser. Check your default browser."))

    def quit(self) -> None:
        if self.loop is not None and self.server is not None:
            self.loop.call_soon_threadsafe(self.server.quit_requested.set)

    async def serve(self) -> None:
        self.loop = asyncio.get_running_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((HOST, 0))
            server = LocalServer(listener.getsockname()[1], on_status=self.update)
            runner = web.AppRunner(await server._make_app(), access_log=None)
            animation = asyncio.create_task(self.animate())
            try:
                await runner.setup()
                await web.SockSite(runner, listener).start()
                self.server = server
                self.update(DesktopStatus())
                await self._open_browser()
                await server.quit_requested.wait()
                await server.shutdown_desktop()
            finally:
                animation.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await animation
                self.server = None
                await runner.cleanup()
                self.loop = None

    def run(self) -> None:
        def setup(_icon: object) -> None:
            _native_call(lambda: setattr(self.icon, "visible", True))
            try:
                asyncio.run(self.serve())
            except Exception as error:
                self.error = error
            finally:
                _native_call(self.icon.stop)

        self.icon.run(setup=setup)
        if self.error is not None:
            raise RuntimeError(f"Ethernity could not run: {self.error}") from self.error


def run_desktop() -> None:
    DesktopTray().run()
