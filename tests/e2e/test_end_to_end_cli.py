# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.test_support import build_cli_env, cli_subprocess_timeout_seconds


def _run_cli(repo_root: Path, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
    return subprocess.run(
        [sys.executable, "-m", "ethernity", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=cli_subprocess_timeout_seconds(),
    )


def test_root_help_points_to_terminal_app_and_run_surface(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = _run_cli(repo_root, tmp_path, "--help")

    assert result.returncode == 0, result.stderr
    assert "Launch the Ethernity terminal app" in result.stdout
    assert "ethernity run backup" in result.stdout
    assert not (tmp_path / "xdg").exists()


def test_old_top_level_backup_command_is_rejected(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = _run_cli(repo_root, tmp_path, "backup")

    assert result.returncode == 2
    assert "unknown command 'backup'" in result.stderr


def test_run_backup_and_restore_round_trip_via_module_entrypoint(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    input_path = tmp_path / "payload.txt"
    backup_dir = tmp_path / "backup"
    restored_path = tmp_path / "restored.txt"
    input_path.write_text("subprocess round trip\n", encoding="utf-8")

    backup_result = _run_cli(
        repo_root,
        tmp_path,
        "run",
        "backup",
        "--input",
        str(input_path),
        "--output-dir",
        str(backup_dir),
        "--passphrase",
        "correct horse battery staple",
        "--yes",
    )
    restore_result = _run_cli(
        repo_root,
        tmp_path,
        "run",
        "restore",
        "--scan",
        str(backup_dir),
        "--passphrase",
        "correct horse battery staple",
        "--output",
        str(restored_path),
        "--yes",
    )

    assert backup_result.returncode == 0, backup_result.stderr + backup_result.stdout
    assert restore_result.returncode == 0, restore_result.stderr + restore_result.stdout
    assert (backup_dir / "qr_document.pdf").read_bytes().startswith(b"%PDF")
    assert (backup_dir / "recovery_document.pdf").read_bytes().startswith(b"%PDF")
    assert restored_path.read_text(encoding="utf-8") == "subprocess round trip\n"
