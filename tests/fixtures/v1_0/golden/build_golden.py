#!/usr/bin/env python3
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

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ethernity.cli.startup import ensure_playwright_browsers as _ensure_playwright_browsers
from ethernity.crypto import decrypt_bytes
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import FrameType, decode_frame
from ethernity.encoding.qr_payloads import decode_qr_payload
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.qr.scan import scan_qr_payloads

PASS_PHRASE = "stable-v1-baseline-passphrase"


def _scenario_definitions(source_root: Path) -> list[dict[str, object]]:
    return [
        {
            "id": "file_no_shard",
            "backup_args": [
                "--input",
                str(source_root / "standalone_secret.txt"),
                "--passphrase",
                PASS_PHRASE,
            ],
            "expected_relative_paths": ["standalone_secret.txt"],
            "expected_source_root": source_root,
            "shard_payload_count": 0,
        },
        {
            "id": "directory_no_shard",
            "backup_args": [
                "--input-dir",
                str(source_root / "directory_payload"),
                "--passphrase",
                PASS_PHRASE,
            ],
            "expected_relative_paths": [
                "alpha.txt",
                "nested/beta.json",
                "nested/raw.bin",
            ],
            "expected_source_root": source_root / "directory_payload",
            "shard_payload_count": 0,
        },
        {
            "id": "mixed_no_shard",
            "backup_args": [
                "--input",
                str(source_root / "mixed_input.txt"),
                "--input-dir",
                str(source_root / "directory_payload"),
                "--base-dir",
                str(source_root),
                "--passphrase",
                PASS_PHRASE,
            ],
            "expected_relative_paths": [
                "mixed_input.txt",
                "directory_payload/alpha.txt",
                "directory_payload/nested/beta.json",
                "directory_payload/nested/raw.bin",
            ],
            "expected_source_root": source_root,
            "shard_payload_count": 0,
        },
        {
            "id": "sharded_embedded",
            "backup_args": [
                "--input-dir",
                str(source_root / "directory_payload"),
                "--passphrase",
                PASS_PHRASE,
                "--shard-threshold",
                "2",
                "--shard-count",
                "3",
                "--signing-key-mode",
                "embedded",
            ],
            "expected_relative_paths": [
                "alpha.txt",
                "nested/beta.json",
                "nested/raw.bin",
            ],
            "expected_source_root": source_root / "directory_payload",
            "shard_payload_count": 2,
        },
        {
            "id": "sharded_signing_sharded",
            "backup_args": [
                "--input",
                str(source_root / "mixed_input.txt"),
                "--input-dir",
                str(source_root / "directory_payload"),
                "--base-dir",
                str(source_root),
                "--passphrase",
                PASS_PHRASE,
                "--shard-threshold",
                "2",
                "--shard-count",
                "3",
                "--signing-key-mode",
                "sharded",
                "--signing-key-shard-threshold",
                "1",
                "--signing-key-shard-count",
                "2",
            ],
            "expected_relative_paths": [
                "mixed_input.txt",
                "directory_payload/alpha.txt",
                "directory_payload/nested/beta.json",
                "directory_payload/nested/raw.bin",
            ],
            "expected_source_root": source_root,
            "shard_payload_count": 2,
        },
    ]


def _run_cli(repo_root: Path, args: list[str], xdg_config_home: Path) -> None:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    cmd = [
        sys.executable,
        "-m",
        "ethernity.cli",
        "--config",
        str(repo_root / "src" / "ethernity" / "config" / "config.toml"),
        *args,
    ]
    result = subprocess.run(
        cmd,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def _write_payloads_file(pdf_paths: list[Path], destination: Path) -> None:
    payloads = scan_qr_payloads([str(path) for path in pdf_paths])
    normalized: list[str] = []
    for payload in payloads:
        if isinstance(payload, bytes):
            normalized.append(payload.decode("ascii"))
        else:
            normalized.append(payload)
    if not normalized:
        destination.write_text("", encoding="utf-8")
        return
    destination.write_text("\n".join(normalized) + "\n", encoding="utf-8")


def _manifest_projection(payloads_file: Path, passphrase: str) -> dict[str, object]:
    payload_lines = payloads_file.read_text(encoding="utf-8").splitlines()
    frames = [
        decode_frame(decode_qr_payload(line.strip())) for line in payload_lines if line.strip()
    ]
    main_frames = [frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
    ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
    plaintext = decrypt_bytes(ciphertext, passphrase=passphrase)
    manifest, _payload = decode_envelope(plaintext)
    files = [
        {
            "path": entry.path,
            "size": entry.size,
            "sha256": entry.sha256.hex(),
        }
        for entry in manifest.files
    ]
    files.sort(key=lambda item: str(item["path"]))
    return {
        "version": manifest.format_version,
        "sealed": manifest.sealed,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "files": files,
    }


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def main() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    source_root = repo_root / "tests" / "fixtures" / "v1_0" / "source"
    golden_root = repo_root / "tests" / "fixtures" / "v1_0" / "golden"

    os.environ.pop("ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", None)
    _ensure_playwright_browsers(quiet=True)

    for child in golden_root.iterdir():
        if child.name == "build_golden.py":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    scenarios = _scenario_definitions(source_root)
    index: dict[str, object] = {"version": "1.0.0", "passphrase": PASS_PHRASE, "scenarios": []}

    with tempfile.TemporaryDirectory() as xdg_tmp:
        xdg_config_home = Path(xdg_tmp)
        for scenario in scenarios:
            scenario_id = str(scenario["id"])
            scenario_root = golden_root / scenario_id
            backup_dir = scenario_root / "backup"
            scenario_root.mkdir(parents=True, exist_ok=True)
            backup_args = [
                "backup",
                *list(scenario["backup_args"]),
                "--design",
                "forge",
                "--output-dir",
                str(backup_dir),
                "--quiet",
            ]
            _run_cli(repo_root, backup_args, xdg_config_home)

            main_payloads = scenario_root / "main_payloads.txt"
            _write_payloads_file([backup_dir / "qr_document.pdf"], main_payloads)

            shard_paths = sorted(backup_dir.glob("shard-*.pdf"))
            shard_payloads_path = scenario_root / "shard_payloads_threshold.txt"
            shard_payload_count = int(scenario["shard_payload_count"])
            if shard_payload_count > 0:
                _write_payloads_file(shard_paths[:shard_payload_count], shard_payloads_path)
            elif shard_payloads_path.exists():
                shard_payloads_path.unlink()

            artifact_hashes = {}
            for artifact in sorted(backup_dir.glob("*.pdf")):
                artifact_hashes[artifact.name] = _file_sha256(artifact)
            artifact_hashes["main_payloads.txt"] = _file_sha256(main_payloads)
            if shard_payload_count > 0:
                artifact_hashes["shard_payloads_threshold.txt"] = _file_sha256(shard_payloads_path)

            expected_files = {}
            expected_source_root = Path(str(scenario["expected_source_root"]))
            for relative_path in list(scenario["expected_relative_paths"]):
                source_path = expected_source_root / str(relative_path)
                expected_files[str(relative_path)] = _file_sha256(source_path)

            snapshot = {
                "scenario_id": scenario_id,
                "passphrase": PASS_PHRASE,
                "expected_relative_paths": list(scenario["expected_relative_paths"]),
                "expected_file_sha256": expected_files,
                "artifact_hashes": artifact_hashes,
                "manifest_projection": _manifest_projection(main_payloads, PASS_PHRASE),
                "shard_payload_count": shard_payload_count,
                "expected_shard_pdfs": len(shard_paths),
                "expected_signing_key_shard_pdfs": len(
                    list(backup_dir.glob("signing-key-shard-*.pdf"))
                ),
            }
            (scenario_root / "snapshot.json").write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            index["scenarios"].append(
                {
                    "id": scenario_id,
                    "path": f"{scenario_id}/snapshot.json",
                }
            )

    (golden_root / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
