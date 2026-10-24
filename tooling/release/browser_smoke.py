"""Check browser assets and a real Textual session in an installed application."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import psutil


async def expect_screen(websocket: aiohttp.ClientWebSocketResponse, text: str) -> None:
    received = ""
    async with asyncio.timeout(60):
        async for message in websocket:
            if message.type == aiohttp.WSMsgType.BINARY:
                received += message.data.decode("utf-8", errors="replace")
                if text in received:
                    return
    raise RuntimeError(f"Browser session ended before showing {text!r}.")


async def check_session(url: str, process_id: int) -> None:
    address = urlsplit(url)
    origin = f"{address.scheme}://{address.netloc}"
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=aiohttp.ClientTimeout(total=30)
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = await response.text()
        if "<title>Ethernity</title>" not in html or "https://" in html:
            raise RuntimeError("Browser page is missing or uses external resources.")
        for asset in ("/static/app.js", "/static/app.css"):
            response = await client.get(origin + asset)
            response.raise_for_status()
            if len(await response.read()) < 100:
                raise RuntimeError(f"Missing browser asset: {asset}")
        # Open and disconnect twice to check that each tab owns a fresh app process.
        server = psutil.Process(process_id)
        for _ in range(2):
            # Windows virtualenv and frozen launchers may already own an interpreter child.
            existing = set(server.children(recursive=True))
            async with client.ws_connect(origin + "/ws?width=112&height=36", origin=origin) as ws:
                await expect_screen(ws, "Choose files")
                children = [
                    child for child in server.children(recursive=True) if child not in existing
                ]
                if not children:
                    raise RuntimeError("Browser mode did not launch a Textual process.")
                await ws.send_json(["stdin", "\r"])
                await expect_screen(ws, "Backup files")
            _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=10)
            if alive:
                raise RuntimeError(f"Closing the browser tab left app processes running: {alive!r}")


async def check_browser(command: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="ethernity-web-") as directory:
        env = dict(os.environ, XDG_CONFIG_HOME=directory)
        env.pop("TEXTUAL_DRIVER", None)
        process = await asyncio.create_subprocess_exec(
            *command,
            "--web",
            "--no-open",
            cwd=directory,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert process.stdout is not None
            async with asyncio.timeout(60):
                while line := await process.stdout.readline():
                    match = re.search(r"http://127\.0\.0\.1:\d+/\?token=\S+", line.decode())
                    if match:
                        url = match[0]
                        break
                else:
                    raise RuntimeError("Browser server exited before printing its local URL.")
            await check_session(url, process.pid)
        finally:
            children = (
                psutil.Process(process.pid).children(recursive=True)
                if process.returncode is None
                else []
            )
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
            # A launcher may exit before its interpreter, which still holds stdout open.
            for child in children:
                with contextlib.suppress(psutil.NoSuchProcess):
                    child.terminate()
            _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=5)
            for child in alive:
                with contextlib.suppress(psutil.NoSuchProcess):
                    child.kill()
            if alive:
                await asyncio.to_thread(psutil.wait_procs, alive, timeout=5)
            try:
                await asyncio.wait_for(process.communicate(), timeout=15)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.communicate()


def smoke_browser(binary: str) -> None:
    asyncio.run(check_browser([str(Path(binary).resolve())]))
