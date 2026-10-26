from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

import aiohttp
import psutil
import pytest
from aiohttp.test_utils import TestClient, TestServer
from tooling.release.browser_smoke import check_browser, expect_screen
from tooling.release.desktop_smoke import check_desktop

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


@pytest.mark.skipif(sys.platform not in {"darwin", "win32"}, reason="Native desktop platforms")
def test_desktop_launch_opens_browser_and_quits_explicitly() -> None:
    asyncio.run(check_desktop([sys.executable, "-m", "ethernity.desktop"]))


@pytest.mark.parametrize("input_reader", ["native", "windows-pipe"])
def test_desktop_stays_open_for_other_tabs_and_refreshes(
    monkeypatch, tmp_path, input_reader
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    if input_reader == "windows-pipe":
        script = Path(__file__).parents[1] / "support" / "desktop_pipe_app.py"
        monkeypatch.setattr(browser, "app_command", lambda: [sys.executable, str(script)])

    async def check() -> None:
        statuses = []
        server = browser.LocalServer(0, on_status=statuses.append)
        async with TestClient(
            TestServer(await server._make_app()), cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as client:
            server.port = client.server.port
            server.public_url = str(client.make_url("/")).rstrip("/")
            await client.get(f"/?token={server.token}")
            first = await client.ws_connect("/ws", origin=server.public_url)
            second = await client.ws_connect("/ws", origin=server.public_url)
            await expect_screen(first, "Choose files")
            await expect_screen(second, "Choose files")
            services = tuple(server.services)
            await first.close()
            assert not second.closed
            await second.close()
            try:
                await asyncio.wait_for(asyncio.gather(*(s.closed.wait() for s in services)), 10)
            finally:
                # Reap a broken implementation too, without hiding the failed exit assertion.
                await asyncio.gather(*(s.stop() for s in services if not s.closed.is_set()))
            assert not server.quit_requested.is_set()
            assert not server.services
            assert not server.websockets
            async with client.ws_connect("/ws", origin=server.public_url) as refreshed:
                await expect_screen(refreshed, "Choose files")
                await refreshed.send_json(["stdin", "q"])
                await asyncio.wait_for(server.quit_requested.wait(), 10)
                await asyncio.wait_for(server.shutdown_desktop(), 10)
            assert server.quitting
            assert statuses[-1].text == "Quitting"
            response = await client.get("/ws", headers={"Origin": server.public_url})
            assert response.status == 503

    asyncio.run(check())


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
            greeting = await asyncio.wait_for(unrelated.stdout.readline(), 10)
            assert greeting in (b"ready\n", b"ready\r\n")
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


@pytest.mark.parametrize("launcher", [False, True], ids=["direct", "launcher"])
def test_unresponsive_child_is_stopped_without_shell_quoting(
    monkeypatch, tmp_path, launcher
) -> None:
    script = tmp_path / "child & data.py"
    script.write_text(
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdout.buffer.write(b'__GANGLION__\\nD\\x00\\x00\\x00\\x05ready')\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(60)\n"
    )
    command = [sys.executable, str(script)]
    if launcher:
        wrapper = tmp_path / "launcher.py"
        wrapper.write_text(
            "import subprocess, sys\nsys.exit(subprocess.call([sys.executable, *sys.argv[1:]]))\n"
        )
        command.insert(1, str(wrapper))
    monkeypatch.setattr(browser, "app_command", lambda: command)
    monkeypatch.setattr(browser, "STOP_TIMEOUT", 0.1)

    async def ignore(*args) -> None:
        pass

    async def check() -> None:
        ready = asyncio.Event()

        async def receive(data: bytes) -> None:
            assert data == b"ready"
            ready.set()

        server = browser.LocalServer(0)
        service = browser.LocalAppService(
            "ethernity",
            write_bytes=receive,
            write_str=ignore,
            close=ignore,
            download_manager=server.download_manager,
        )
        await service.start(80, 24)
        process = service._process
        assert process is not None
        descendants = []
        try:
            await asyncio.wait_for(ready.wait(), 10)
            descendants = psutil.Process(process.pid).children(recursive=True)
            if launcher:
                assert descendants
            await asyncio.wait_for(service.stop(), 5)
            assert process.returncode is not None
            _, alive = await asyncio.to_thread(psutil.wait_procs, descendants, timeout=5)
            assert not alive
        finally:
            for descendant in descendants:
                with contextlib.suppress(psutil.NoSuchProcess):
                    descendant.kill()
            if process.returncode is None:
                process.kill()
            await process.wait()

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


@pytest.mark.parametrize("suffix", ["", ".exe"])
def test_desktop_relaunches_sibling_console_executable(monkeypatch, tmp_path, suffix) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / f"ethernity-desktop{suffix}"))
    assert browser.app_command() == [str(tmp_path / f"ethernity{suffix}")]


@pytest.mark.parametrize("quit_app", [False, True], ids=["close-tab", "quit-app"])
@pytest.mark.parametrize("input_reader", ["native", "windows-pipe"])
def test_desktop_shutdown_finishes_file_commit_and_reports_status(
    monkeypatch, tmp_path, quit_app, input_reader
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "input.txt").write_text("test input")
    script = Path(__file__).parents[1] / "support" / "desktop_write_app.py"
    monkeypatch.setattr(
        browser, "app_command", lambda: [sys.executable, str(script), str(tmp_path), input_reader]
    )

    async def check() -> None:
        statuses = []
        server = browser.LocalServer(0, on_status=statuses.append)
        async with TestClient(
            TestServer(await server._make_app()), cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as client:
            server.port = client.server.port
            server.public_url = str(client.make_url("/")).rstrip("/")
            await client.get(f"/?token={server.token}")
            ws = await client.ws_connect("/ws", origin=server.public_url)
            try:
                async with asyncio.timeout(15):
                    while not (tmp_path / "started").exists() or not any(s.busy for s in statuses):
                        await asyncio.sleep(0.02)
                (service,) = server.services
                process = service._process
                assert process is not None
                if quit_app:
                    server.quit_requested.set()
                    shutdown = asyncio.create_task(server.shutdown_desktop())
                else:
                    await ws.close()
                    shutdown = asyncio.create_task(service.closed.wait())
                # Shutdown must not cross the commit boundary, even after the tab disconnects.
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(shutdown), 0.2)
                assert not (tmp_path / "saved.txt").exists()
                assert not service.closed.is_set()
                (tmp_path / "release").touch()
                await asyncio.wait_for(shutdown, 10)
                assert process.returncode == 0
                assert (tmp_path / "saved.txt").read_text() == "complete"
                assert not server.services
                assert (
                    any(s.text == "Backup complete" and not s.busy for s in statuses) or quit_app
                ), statuses
                assert all(str(tmp_path) not in s.text for s in statuses)
            finally:
                (tmp_path / "release").touch()
                await ws.close()

    asyncio.run(check())


@pytest.mark.skipif(sys.platform not in {"darwin", "win32"}, reason="Native desktop platforms")
def test_native_status_icon_animates_during_work_and_stops_when_idle() -> None:
    async def check() -> None:
        script = Path(__file__).parents[1] / "support" / "desktop_animation.py"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 15)
            assert process.returncode == 0, output.decode(errors="replace")
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    asyncio.run(check())
