"""Local browser launcher for the existing Textual application."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import socket
import sys
import webbrowser
from collections.abc import Awaitable, Callable
from pathlib import Path

import psutil
from aiohttp import web
from textual_serve.app_service import AppService
from textual_serve.download_manager import DownloadManager
from textual_serve.server import Server

from ethernity.app.desktop_session import DesktopStatus

if sys.platform == "win32":
    from subprocess import CREATE_NO_WINDOW
else:
    CREATE_NO_WINDOW = 0

HOST = "127.0.0.1"
TEMPLATES = Path(__file__).with_suffix("")
ICON_PATH = Path(__file__).parents[1] / "resources" / "icons" / "app.png"
STOP_TIMEOUT = 3


def app_command() -> list[str]:
    """Relaunch this installation, including standalone PyInstaller builds."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        if executable.stem == "ethernity-desktop":
            return [str(executable.with_name("ethernity" + executable.suffix))]
        return [sys.executable]
    return [sys.executable, "-m", "ethernity"]


class LocalAppService(AppService):
    """Use Textual's protocol with an owned child process and no command shell."""

    def __init__(
        self,
        command: str,
        *,
        write_bytes: Callable[[bytes], Awaitable[None]],
        write_str: Callable[[str], Awaitable[None]],
        close: Callable[[], Awaitable[None]],
        download_manager: DownloadManager,
        desktop: bool = False,
        changed: Callable[[], None] = lambda: None,
        quit_requested: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(
            command,
            write_bytes=write_bytes,
            write_str=write_str,
            close=close,
            download_manager=download_manager,
        )
        self.desktop = desktop
        self.changed = changed
        self.quit_requested = quit_requested
        self.status = DesktopStatus()
        self.closed = asyncio.Event()

    def _build_environment(self, width: int = 80, height: int = 24) -> dict[str, str]:
        environment = super()._build_environment(width, height)
        if self.desktop:
            environment["TEXTUAL_DRIVER"] = "ethernity.app.desktop_session:DesktopDriver"
        return environment

    async def on_meta(self, data: bytes) -> None:
        message = json.loads(data)
        if self.desktop and message.get("type") == "ethernity.status":
            text, busy = message.get("text"), message.get("busy")
            if isinstance(text, str) and isinstance(busy, bool):
                self.status = DesktopStatus(text, busy)
                self.changed()
        elif self.desktop and message.get("type") == "ethernity.quit":
            self.quit_requested()
        else:
            await super().on_meta(data)

    async def finish(self) -> None:
        try:
            if self.desktop and self._task is not None:
                await self.send_meta({"type": "ethernity.shutdown"})
                # The UI exits only after its execution worker finishes. No deadline
                # here: a timeout must never terminate an in-progress file commit.
                await self._task
        finally:
            try:
                await self.stop()
            finally:
                self.closed.set()

    async def _open_app_process(
        self, width: int = 80, height: int = 24
    ) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            *app_command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_environment(width, height),
            creationflags=CREATE_NO_WINDOW,
        )
        self._process = process
        assert process.stdin is not None
        self._stdin = process.stdin
        return process

    async def stop(self) -> None:
        process = self._process
        children: list[psutil.Process] = []
        if process is not None and process.returncode is None:
            # Capture ownership before quit can make a launcher exit and orphan its child.
            with contextlib.suppress(psutil.NoSuchProcess):
                children = psutil.Process(process.pid).children(recursive=True)
        try:
            await asyncio.wait_for(super().stop(), timeout=STOP_TIMEOUT)
        except (TimeoutError, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            await _stop_children(children)
            if process is not None:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
                self._process = None


async def _stop_children(children: list[psutil.Process]) -> None:
    if not children:
        return
    # Stop descendants first so waiting launchers can reap them and exit normally.
    for child in reversed(children):
        with contextlib.suppress(psutil.NoSuchProcess):
            child.terminate()
    _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=STOP_TIMEOUT)
    for child in alive:
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    if alive:
        await asyncio.to_thread(psutil.wait_procs, alive, timeout=STOP_TIMEOUT)


class LocalServer(Server):
    """Keep the app on loopback and accept only the browser opened by this launch."""

    def __init__(
        self, port: int, *, on_status: Callable[[DesktopStatus], None] | None = None
    ) -> None:
        super().__init__(
            "ethernity",
            host=HOST,
            port=port,
            title="Ethernity",
            templates_path=TEMPLATES,
            statics_path=TEMPLATES / "static",
        )
        self.token = secrets.token_urlsafe(32)
        self.cookie_name = f"ethernity-{port}"
        self.websockets: set[web.WebSocketResponse] = set()
        self.services: set[LocalAppService] = set()
        self.finishing: set[asyncio.Task[None]] = set()
        self.on_status = on_status
        self.quit_requested = asyncio.Event()
        self.quitting = False
        self.last_status = DesktopStatus()

    def status_changed(self) -> None:
        if self.on_status is None:
            return
        active = [service.status for service in self.services if service.status.busy]
        if self.quitting:
            status = DesktopStatus(
                "Finishing tasks before quitting" if active else "Quitting", True
            )
        elif len(active) > 1:
            status = DesktopStatus(f"{len(active)} tasks running", True)
        elif active:
            status = active[0]
        else:
            status = self.last_status
        self.on_status(status)

    async def shutdown_desktop(self) -> None:
        self.quitting = True
        self.status_changed()
        services = tuple(self.services)
        await asyncio.gather(*(ws.close(code=1001) for ws in tuple(self.websockets)))
        await asyncio.gather(*(service.closed.wait() for service in services))

    @property
    def browser_url(self) -> str:
        return f"{self.public_url}/?token={self.token}"

    def _valid_token(self, candidate: str) -> bool:
        return secrets.compare_digest(candidate.encode("utf-8"), self.token.encode("ascii"))

    @web.middleware
    async def authorize(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.host != f"{HOST}:{self.port}":
            raise web.HTTPForbidden()
        origin = request.headers.get("Origin")
        if origin is not None and origin != self.public_url:
            raise web.HTTPForbidden()
        if request.path == "/ws" and origin != self.public_url:
            raise web.HTTPForbidden()

        token = request.query.get("token")
        if request.path == "/" and token is not None:
            if not self._valid_token(token):
                raise web.HTTPForbidden()
            response = web.Response(status=302, headers={"Location": "/"})
            response.set_cookie(self.cookie_name, self.token, httponly=True, samesite="Strict")
        else:
            cookie = request.cookies.get(self.cookie_name, "")
            if not self._valid_token(cookie):
                raise web.HTTPForbidden(text="Open the browser link printed by ethernity --web.")
            response = await handler(request)
        return response

    async def response_headers(self, request: web.Request, response: web.StreamResponse) -> None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            f"connect-src 'self' ws://{HOST}:{self.port}; "
            "frame-ancestors 'none'; base-uri 'none'"
        )

    async def _make_app(self) -> web.Application:
        app = await super()._make_app()
        app.router.add_get("/icon.png", self.handle_icon)
        app.middlewares.append(self.authorize)
        app.on_response_prepare.append(self.response_headers)
        return app

    async def handle_icon(self, _request: web.Request) -> web.FileResponse:
        return web.FileResponse(ICON_PATH)

    async def on_startup(self, app: web.Application) -> None:
        # Announce the URL only after the listening socket is ready.
        pass

    async def on_shutdown(self, app: web.Application) -> None:
        await asyncio.gather(*(ws.close(code=1001) for ws in tuple(self.websockets)))

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        if self.quitting:
            raise web.HTTPServiceUnavailable(text="Ethernity is quitting.")
        websocket = web.WebSocketResponse(heartbeat=15)
        try:
            width = max(20, min(500, int(request.query.get("width", "80"))))
            height = max(10, min(200, int(request.query.get("height", "24"))))
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid terminal size.") from error

        async def close() -> None:
            await websocket.close()

        async def write_bytes(data: bytes) -> None:
            if not websocket.closed:
                with contextlib.suppress(ConnectionResetError):
                    await websocket.send_bytes(data)

        async def write_str(data: str) -> None:
            if not websocket.closed:
                with contextlib.suppress(ConnectionResetError):
                    await websocket.send_str(data)

        def changed() -> None:
            self.last_status = service.status
            self.status_changed()

        service = LocalAppService(
            self.command,
            write_bytes=write_bytes,
            write_str=write_str,
            close=close,
            download_manager=self.download_manager,
            desktop=self.on_status is not None,
            changed=changed,
            quit_requested=self.quit_requested.set,
        )
        await websocket.prepare(request)
        if self.quitting:
            await websocket.close(code=1001)
            return websocket
        self.websockets.add(websocket)
        self.services.add(service)
        self.status_changed()
        try:
            await service.start(width, height)
            await self._process_messages(websocket, service)
        finally:
            # The server owns cleanup. A disconnected HTTP request may be cancelled,
            # but it must not cancel the process reader or interrupt an active commit.
            task = asyncio.create_task(self.finish_session(service, websocket))
            self.finishing.add(task)
            task.add_done_callback(self.finishing.discard)
            await asyncio.shield(task)
        return websocket

    async def finish_session(
        self, service: LocalAppService, websocket: web.WebSocketResponse
    ) -> None:
        try:
            await service.finish()
        finally:
            self.websockets.discard(websocket)
            self.services.discard(service)
            if service.status.busy:
                self.last_status = DesktopStatus("Task stopped unexpectedly")
            self.status_changed()


def run_browser(*, open_browser: bool = True) -> None:
    # Reserve an available port instead of racing another local server for a fixed one.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((HOST, 0))
        server = LocalServer(listener.getsockname()[1])

        def ready(_message: str) -> None:
            print(f"Ethernity is running locally at {server.browser_url}", flush=True)
            print("Keep this terminal open. Press Ctrl+C to stop browser mode.", flush=True)
            if open_browser:
                try:
                    opened = webbrowser.open(server.browser_url)
                except (webbrowser.Error, OSError):
                    opened = False
                if not opened:
                    print("Open the link above in your browser.", flush=True)

        web.run_app(
            server._make_app(),
            sock=listener,
            print=ready,
            access_log=None,
            shutdown_timeout=10,
        )
