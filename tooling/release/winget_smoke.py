"""Verify WinGet's ZIP install, upgrade, command alias, and uninstall on Windows."""

from __future__ import annotations

import functools
import http.server
import os
import re
import tempfile
import threading
from pathlib import Path

from tooling.release.install_smoke import fixture, run
from tooling.release.installers import winget_manifest


def main() -> None:
    tag = os.environ["RELEASE_TAG"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        print(
            "WinGet is published only for stable three-part versions. "
            "Direct installers are tested separately."
        )
        return
    archive = Path(f"ethernity-{tag}-windows-x64.zip").resolve()
    run("winget", "settings", "--enable", "LocalManifestFiles")
    with tempfile.TemporaryDirectory(prefix="ethernity-winget-") as temp:
        directory = Path(temp)
        old = fixture(directory, "v0.0.1", "windows", "x64")
        # Serve only these test archives. Never expose the checkout or user files.
        (directory / archive.name).write_bytes(archive.read_bytes())
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        alias = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WinGet/Links/ethernity.exe"
        if alias.exists():
            raise AssertionError("WinGet test requires a clean runner without Ethernity")
        try:
            for action, path, version in (("install", old, "v0.0.1"), ("upgrade", archive, tag)):
                manifest = directory / "MinorGlitch.Ethernity.yaml"
                url = f"http://127.0.0.1:{server.server_port}/{path.name}"
                manifest.write_text(winget_manifest(path, version, url), encoding="utf-8")
                run("winget", "validate", "--manifest", str(manifest))
                run(
                    "winget",
                    action,
                    "--manifest",
                    str(manifest),
                    "--scope",
                    "user",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                )
                assert run(str(alias), "--version") == f"ethernity {version.removeprefix('v')}"
            assert not (alias.resolve().parent / "obsolete.txt").exists()
            run(str(alias), "run", "--help")
            run(
                "winget",
                "uninstall",
                "--id",
                "MinorGlitch.Ethernity",
                "--exact",
                "--scope",
                "user",
                "--purge",
                "--disable-interactivity",
            )
            assert not alias.exists()
            print("WinGet: install, upgrade, command alias and uninstall passed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            if alias.exists():
                run(
                    "winget",
                    "uninstall",
                    "--id",
                    "MinorGlitch.Ethernity",
                    "--exact",
                    "--scope",
                    "user",
                    "--purge",
                    "--disable-interactivity",
                )


if __name__ == "__main__":
    main()
