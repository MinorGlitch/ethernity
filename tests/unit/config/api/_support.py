"""Shared fixtures for config API tests."""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import ethernity.config.install as installer
import ethernity.config.paths as config_paths


@contextlib.contextmanager
def isolated_user_config(config_root: Path) -> Iterator[None]:
    with (
        mock.patch.object(
            config_paths,
            "user_config_dir_path",
            return_value=config_root,
        ),
        mock.patch.object(
            config_paths,
            "user_config_file_path",
            side_effect=lambda name: config_root / name,
        ),
        mock.patch.object(
            installer,
            "user_config_dir_path",
            return_value=config_root,
        ),
    ):
        yield


@contextlib.contextmanager
def temporary_config_path(initial_text: str | None = None) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.toml"
        if initial_text is not None:
            path.write_text(initial_text, encoding="utf-8")
        yield path


__all__ = ["isolated_user_config", "temporary_config_path"]
