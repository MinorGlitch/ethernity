from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build import build as _build


class CleanBuild(_build):
    """Rebuild from a clean staging tree so stale build/lib files cannot leak into wheels."""

    def run(self) -> None:
        build_base = Path(self.build_base)
        if build_base.exists():
            shutil.rmtree(build_base)
        super().run()


setup(cmdclass={"build": CleanBuild})
