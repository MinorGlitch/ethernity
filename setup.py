from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build import build as _build
from setuptools.command.sdist import sdist as _sdist
from setuptools.errors import SetupError

_PROJECT_ROOT = Path(__file__).resolve().parent
_REQUIRED_KIT_BUNDLES = (
    _PROJECT_ROOT / "src" / "ethernity" / "resources" / "kit" / "recovery_kit.bundle.html",
    _PROJECT_ROOT / "src" / "ethernity" / "resources" / "kit" / "recovery_kit.scanner.bundle.html",
)


def _assert_generated_kit_bundles_present() -> None:
    failures: list[str] = []
    for bundle_path in _REQUIRED_KIT_BUNDLES:
        if not bundle_path.is_file():
            failures.append(f"missing: {bundle_path.relative_to(_PROJECT_ROOT)}")
            continue
        if bundle_path.stat().st_size < 1000:
            failures.append(f"too small: {bundle_path.relative_to(_PROJECT_ROOT)}")
    if failures:
        details = "\n".join(f"  - {failure}" for failure in failures)
        raise SetupError(
            "recovery kit bundles must be generated before building release artifacts:\n"
            f"{details}\n"
            "Run 'cd kit && node build_kit.mjs'."
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
