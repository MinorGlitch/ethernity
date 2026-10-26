"""Check animated native icons on the OS event loop, without replacing the backend."""

from __future__ import annotations

import asyncio
import contextlib

import pystray

from ethernity.app.desktop_session import DesktopStatus
from ethernity.app.desktop_tray import DesktopTray


class AnimationCheck(DesktopTray):
    async def serve(self) -> None:
        animation = asyncio.create_task(self.animate())
        try:
            self.update(DesktopStatus("Creating PDFs", True))
            async with asyncio.timeout(5):
                while self.icon.icon is self.idle_icon:
                    await asyncio.sleep(0.01)
                first = self.icon.icon
                while self.icon.icon is first:
                    await asyncio.sleep(0.01)
            assert self.icon.visible
            assert self.icon.title == "Ethernity - Creating PDFs"
            assert self.icon.menu is not None
            assert [
                item.text for item in self.icon.menu.items if item is not pystray.Menu.SEPARATOR
            ] == [
                "Creating PDFs",
                "Open Ethernity",
                "Quit Ethernity",
            ]
            self.update(DesktopStatus("Backup complete"))
            async with asyncio.timeout(5):
                while self.icon.icon is not self.idle_icon:
                    await asyncio.sleep(0.01)
            # Already queued frames must not restart motion once the task is done.
            await asyncio.sleep(0.25)
            assert self.icon.icon is self.idle_icon
            assert not self.activity.is_set()
        finally:
            animation.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await animation


AnimationCheck().run()
