"""Local browser launcher for the existing Textual application."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import socket
import sys
import webbrowser
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiohttp import web
from textual_serve.app_service import AppService
from textual_serve.server import Server

HOST = "127.0.0.1"
TEMPLATES = Path(__file__).with_suffix("")
STOP_TIMEOUT = 3


def app_command() -> list[str]:
    """Relaunch this installation, including standalone PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "ethernity"]


class LocalAppService(AppService):
    """Use Textual's protocol with an owned child process and no command shell."""

    async def _open_app_process(
        self, width: int = 80, height: int = 24
    ) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            *app_command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_environment(width, height),
        )
        self._process = process
        assert process.stdin is not None
        self._stdin = process.stdin
        return process

    async def stop(self) -> None:
        try:
            await asyncio.wait_for(super().stop(), timeout=STOP_TIMEOUT)
        except (TimeoutError, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process = self._process
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


class LocalServer(Server):
    """Keep the app on loopback and accept only the browser opened by this launch."""

    def __init__(self, port: int) -> None:
        super().__init__(
            "ethernity", host=HOST, port=port, title="Ethernity", templates_path=TEMPLATES
        )
        self.token = secrets.token_urlsafe(32)
        self.cookie_name = f"ethernity-{port}"
        self.websockets: set[web.WebSocketResponse] = set()

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
        app.middlewares.append(self.authorize)
        app.on_response_prepare.append(self.response_headers)
        return app

    async def on_startup(self, app: web.Application) -> None:
        # Announce the URL only after the listening socket is ready.
        pass

    async def on_shutdown(self, app: web.Application) -> None:
        await asyncio.gather(*(ws.close(code=1001) for ws in tuple(self.websockets)))

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(heartbeat=15)
        try:
            width = max(20, min(500, int(request.query.get("width", "80"))))
            height = max(10, min(200, int(request.query.get("height", "24"))))
        except ValueError as error:
            raise web.HTTPBadRequest(text="Invalid terminal size.") from error

        async def close() -> None:
            await websocket.close()

        service = LocalAppService(
            self.command,
            write_bytes=websocket.send_bytes,
            write_str=websocket.send_str,
            close=close,
            download_manager=self.download_manager,
        )
        await websocket.prepare(request)
        self.websockets.add(websocket)
        try:
            await service.start(width, height)
            await self._process_messages(websocket, service)
        finally:
            await service.stop()
            self.websockets.discard(websocket)
        return websocket


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
