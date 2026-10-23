from __future__ import annotations

import asyncio
import sys

import aiohttp
import psutil
import pytest
from aiohttp.test_utils import TestClient, TestServer
from tooling.release.browser_smoke import check_browser, expect_screen

from ethernity.app import browser

pytestmark = pytest.mark.portability


def test_browser_launches_app_and_cleans_up_disconnected_tabs() -> None:
    asyncio.run(check_browser([sys.executable, "-m", "ethernity"]))


def test_stopping_server_closes_active_app(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def check() -> None:
        server = browser.LocalServer(0)
        async with TestClient(
            TestServer(await server._make_app()), cookie_jar=aiohttp.CookieJar(unsafe=True)
        ) as client:
            server.port = client.server.port
            server.public_url = str(client.make_url("/")).rstrip("/")
            await client.get(f"/?token={server.token}")
            async with client.ws_connect("/ws", origin=server.public_url) as ws:
                await expect_screen(ws, "Choose files")
                children = psutil.Process().children()
                assert children
                await asyncio.wait_for(asyncio.gather(client.server.close(), ws.receive()), 15)
                _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=5)
                assert not alive

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
            for path in ("/", "/ws", "/static/js/textual.js", "/download/missing", "/?token=wrong"):
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
            for asset in ("/static/js/textual.js", "/static/css/xterm.css"):
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
