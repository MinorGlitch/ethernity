from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build import build as _build
from setuptools.command.sdist import sdist as _sdist
from setuptools.errors import SetupError

_PROJECT_ROOT = Path(__file__).resolve().parent


def _assert_generated_kit_bundles_present() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(_PROJECT_ROOT / "tooling" / "release_resources.py"),
            "--kit-directory",
            str(_PROJECT_ROOT / "src" / "ethernity" / "resources" / "kit"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SetupError(
            "recovery kit bundles must be generated before building release artifacts:\n"
            f"{result.stderr.strip()}\n"
            "Run 'cd kit && npm ci && node build_kit.mjs'."
        )


class CleanBuild(_build):
    """Rebuild from a clean staging tree so stale build/lib files cannot leak into wheels."""

    def run(self) -> None:
        _assert_generated_kit_bundles_present()
        build_base = Path(self.build_base)
        if build_base.exists():
            shutil.rmtree(build_base)
        super().run()


class CheckedSdist(_sdist):
    """Refuse to publish sdists without generated recovery kit bundles."""

    def run(self) -> None:
        _assert_generated_kit_bundles_present()
        super().run()


setup(cmdclass={"build": CleanBuild, "sdist": CheckedSdist})
