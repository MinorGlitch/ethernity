"""Exercise the actual desktop entry point using Python's documented browser override."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import psutil

from tooling.release.browser_smoke import check_session

PROBE = """import json, os, sys
from pathlib import Path
import psutil
for parent in psutil.Process().parents():
    command = parent.cmdline()
    if Path(parent.exe()).stem == 'ethernity-desktop' or 'ethernity.desktop' in command:
        destination = Path(os.environ['ETHERNITY_BROWSER_PROBE'])
        pending = destination.with_suffix('.tmp')
        pending.write_text(
            json.dumps({'url': sys.argv[1], 'pid': parent.pid}))
        pending.replace(destination)
        break
else:
    raise RuntimeError('Browser was not opened by the desktop launcher')
"""


async def check_desktop(
    command: list[str], *, while_running: Callable[[], None] | None = None
) -> None:
    """Check the URL, real UI sessions and automatic server/child shutdown."""
    with tempfile.TemporaryDirectory(prefix="ethernity-desktop-") as temporary:
        directory = Path(temporary)
        probe = directory / "browser.py"
        result = directory / "opened.json"
        probe.write_text(PROBE, encoding="utf-8")
        environment = dict(
            os.environ,
            BROWSER=shlex.join([sys.executable, str(probe), "%s"]),
            ETHERNITY_BROWSER_PROBE=str(result),
            XDG_CONFIG_HOME=str(directory / "config"),
        )
        environment.pop("TEXTUAL_DRIVER", None)
        environment.pop("PYTHONPATH", None)
        if len(command) == 1 and command[0].endswith(".app"):
            # Launch Services does not inherit the caller's environment without --env.
            command = ["/usr/bin/open", "-W", "-n", command[0]]
            for name in ("BROWSER", "ETHERNITY_BROWSER_PROBE", "XDG_CONFIG_HOME"):
                command.extend(["--env", f"{name}={environment[name]}"])
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=directory,
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        server: psutil.Process | None = None
        try:
            async with asyncio.timeout(75):
                while not result.exists():
                    if process.returncode is not None:
                        raise RuntimeError(
                            f"Desktop launcher exited early: {await process.communicate()}"
                        )
                    await asyncio.sleep(0.05)
            data = json.loads(result.read_text())
            server = psutil.Process(data["pid"])
            if while_running is not None:
                await asyncio.to_thread(while_running)
            await check_session(data["url"], server.pid)
            # asyncio owns and reaps this child. psutil.wait() would race its child watcher.
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
            if process.returncode != 0:
                raise RuntimeError(f"Desktop launcher failed: {stderr.decode(errors='replace')}")
            if server.pid != process.pid:
                _, alive = await asyncio.to_thread(psutil.wait_procs, [server], timeout=5)
                if alive:
                    raise RuntimeError("Desktop server remained running after its last tab closed")
        finally:
            await stop_owned_processes(process, server)


async def stop_owned_processes(
    process: asyncio.subprocess.Process, server: psutil.Process | None
) -> None:
    owned = []
    roots = [server]
    with contextlib.suppress(psutil.NoSuchProcess):
        roots.append(psutil.Process(process.pid))
    for root in roots:
        if root is not None:
            with contextlib.suppress(psutil.NoSuchProcess):
                owned.extend([*root.children(recursive=True), root])
    for child in set(owned):
        with contextlib.suppress(psutil.NoSuchProcess):
            child.terminate()
    others = [child for child in owned if child.pid != process.pid]
    _, alive = await asyncio.to_thread(psutil.wait_procs, others, timeout=5)
    for child in alive:
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    if process.returncode is None:
        await asyncio.wait_for(process.communicate(), timeout=10)


def smoke_desktop(path: Path) -> None:
    asyncio.run(check_desktop([str(path.resolve())]))
