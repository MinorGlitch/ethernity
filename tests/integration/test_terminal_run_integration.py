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

from pathlib import Path

from click.testing import CliRunner

from ethernity.run.cli import cli
from tests.test_support import temp_env


def test_run_backup_and_restore_round_trip(tmp_path: Path) -> None:
    payload = "terminal runner round trip\n"
    input_path = tmp_path / "secret.txt"
    backup_dir = tmp_path / "backup"
    restored_path = tmp_path / "restored.txt"
    input_path.write_text(payload, encoding="utf-8")

    runner = CliRunner()
    with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
        backup_result = runner.invoke(
            cli,
            [
                "backup",
                "--input",
                str(input_path),
                "--output-dir",
                str(backup_dir),
                "--passphrase",
                "correct horse battery staple",
                "--yes",
            ],
        )
        restore_result = runner.invoke(
            cli,
            [
                "restore",
                "--scan",
                str(backup_dir),
                "--passphrase",
                "correct horse battery staple",
                "--output",
                str(restored_path),
                "--yes",
            ],
        )

    assert backup_result.exit_code == 0, backup_result.output
    assert restore_result.exit_code == 0, restore_result.output
    assert (backup_dir / "qr_document.pdf").read_bytes().startswith(b"%PDF")
    assert (backup_dir / "recovery_document.pdf").read_bytes().startswith(b"%PDF")
    assert any(backup_dir.glob("shard-*-1-of-3.pdf"))
    assert restored_path.read_text(encoding="utf-8") == payload
