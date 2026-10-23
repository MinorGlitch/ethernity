from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiohttp
import psutil
import pytest
from aiohttp.test_utils import TestClient, TestServer
from tooling.release.browser_smoke import check_browser, expect_screen

from ethernity.app import browser

pytestmark = pytest.mark.portability


@pytest.fixture(params=[False, True], ids=["direct", "launcher"])
def browser_command(tmp_path, request) -> list[str]:
    command = [sys.executable, "-m", "ethernity"]
    if request.param:
        # Model the persistent interpreter child of Windows virtualenv launchers.
        script = tmp_path / "launcher.py"
        script.write_text(
            "import subprocess, sys\n"
            "sys.exit(subprocess.call([sys.executable, '-m', 'ethernity', *sys.argv[1:]]))\n"
        )
        command = [sys.executable, str(script)]
    return command


def test_browser_launches_app_and_cleans_up_disconnected_tabs(browser_command) -> None:
    asyncio.run(check_browser(browser_command))


def test_browser_scroll_reports_move_one_cell_each(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    script = Path(__file__).parents[1] / "support" / "browser_scroll_app.py"
    monkeypatch.setattr(browser, "app_command", lambda: [sys.executable, str(script)])

    async def check() -> None:
        server = browser.LocalServer(0)
        async with TestClient(
            TestServer(await server._make_app()), cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as client:
            server.port = client.server.port
            server.public_url = str(client.make_url("/")).rstrip("/")
            await client.get(f"/?token={server.token}")
            async with client.ws_connect("/ws?width=100&height=35", origin=server.public_url) as ws:
                await expect_screen(ws, "SCROLL=0")
                await ws.send_json(["stdin", "\x1b[<65;40;15M" * 20])
                await expect_screen(ws, "SCROLL=20")
                await ws.send_json(["stdin", "\x1b[<64;40;15M" * 5])
                await expect_screen(ws, "SCROLL=15")

    asyncio.run(check())


def test_stopping_server_closes_active_app(monkeypatch, tmp_path, browser_command) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(browser, "app_command", lambda: browser_command)

    async def check() -> None:
        # This existing process launches another interpreter only after the snapshot.
        # Windows virtualenv launchers can do the same while Popen is returning.
        unrelated = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import subprocess, sys\n"
            "print('ready', flush=True)\n"
            "sys.stdin.readline()\n"
            "with subprocess.Popen([sys.executable, '-c', "
            "'import os, sys; print(os.getpid(), flush=True); sys.stdin.read()'], "
            "stdin=subprocess.PIPE) as child:\n"
            "    sys.stdin.read()\n"
            "    child.communicate(timeout=5)\n",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        assert unrelated.stdin is not None
        assert unrelated.stdout is not None
        try:
            assert await asyncio.wait_for(unrelated.stdout.readline(), 10) == b"ready\n"
            await check_shutdown(unrelated)
            assert unrelated.returncode is None
        finally:
            unrelated.stdin.close()
            await asyncio.wait_for(unrelated.communicate(), 10)
        assert unrelated.returncode == 0

    async def check_shutdown(unrelated: asyncio.subprocess.Process) -> None:
        parent = psutil.Process()
        # Ownership follows direct child roots, not the time a descendant appears.
        existing_roots = set(parent.children())
        assert unrelated.stdin is not None
        assert unrelated.stdout is not None
        unrelated.stdin.write(b"launch\n")
        await unrelated.stdin.drain()
        interpreter = psutil.Process(int(await asyncio.wait_for(unrelated.stdout.readline(), 10)))
        assert psutil.Process(unrelated.pid) in existing_roots
        server = browser.LocalServer(0)
        async with TestClient(
            TestServer(await server._make_app()), cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as client:
            server.port = client.server.port
            server.public_url = str(client.make_url("/")).rstrip("/")
            await client.get(f"/?token={server.token}")
            async with client.ws_connect("/ws", origin=server.public_url) as ws:
                await expect_screen(ws, "Choose files")
                session_roots = set(parent.children()) - existing_roots
                assert len(session_roots) == 1
                session_processes = [
                    process
                    for root in session_roots
                    for process in (root, *root.children(recursive=True))
                ]
                await asyncio.wait_for(asyncio.gather(client.server.close(), ws.receive()), 15)
                _, alive = await asyncio.to_thread(psutil.wait_procs, session_processes, timeout=5)
                assert not alive
                assert interpreter.is_running()

    asyncio.run(check())


def test_unresponsive_child_is_stopped_without_shell_quoting(monkeypatch, tmp_path) -> None:
    script = tmp_path / "child & data.py"
    script.write_text("import time\nprint('__GANGLION__', flush=True)\ntime.sleep(60)\n")
    monkeypatch.setattr(browser, "app_command", lambda: [sys.executable, str(script)])
    monkeypatch.setattr(browser, "STOP_TIMEOUT", 0.1)

    async def ignore(*args) -> None:
        pass

    async def check() -> None:
        server = browser.LocalServer(0)
        service = browser.LocalAppService(
            "ethernity",
            write_bytes=ignore,
            write_str=ignore,
            close=ignore,
            download_manager=server.download_manager,
        )
        await service.start(80, 24)
        process = service._process
        assert process is not None
        await service.stop()
        assert process.returncode is not None

    asyncio.run(check())


def test_browser_access_and_offline_assets() -> None:
    async def check() -> None:
        server = browser.LocalServer(0)
        async with TestClient(
            TestServer(await server._make_app()), cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as client:
            server.port = client.server.port
            server.public_url = str(client.make_url("/")).rstrip("/")
            for path in ("/", "/ws", "/static/app.js", "/download/missing", "/?token=wrong"):
                assert (await client.get(path)).status == 403
            response = await client.get(f"/?token={server.token}", allow_redirects=False)
            assert response.status == 302
            assert response.headers["Location"] == "/"
            assert response.cookies[server.cookie_name]["httponly"]
            assert response.cookies[server.cookie_name]["samesite"] == "Strict"
            response = await client.get("/")
            assert response.status == 200
            html = await response.text()
            assert "<title>Ethernity</title>" in html
            assert "https://" not in html
            assert "no-store" in response.headers["Cache-Control"]
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
            for asset in ("/static/app.js", "/static/app.css"):
                response = await client.get(asset)
                assert response.status == 200
                assert len(await response.read()) > 100
            assert (await client.get("/", headers={"Host": "attacker.example"})).status == 403
            assert (
                await client.get("/", headers={"Origin": "https://attacker.example"})
            ).status == 403
            for origin in (None, "null", "https://attacker.example"):
                headers = {} if origin is None else {"Origin": origin}
                with pytest.raises(aiohttp.WSServerHandshakeError) as error:
                    await client.ws_connect("/ws", headers=headers)
                assert error.value.status == 403
            with pytest.raises(aiohttp.WSServerHandshakeError) as error:
                await client.ws_connect("/ws?width=bad", origin=server.public_url)
            assert error.value.status == 400

    asyncio.run(check())


@pytest.mark.parametrize("frozen", [False, True])
def test_browser_relaunches_current_installation(monkeypatch, frozen) -> None:
    executable = "C:/Program Files/Ethernity & notes/ethernity.exe"
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    assert browser.app_command() == [executable, *([] if frozen else ["-m", "ethernity"])]
