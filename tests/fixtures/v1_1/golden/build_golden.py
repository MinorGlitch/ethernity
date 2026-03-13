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

import argparse
import hashlib
import importlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from ethernity.cli.startup import ensure_playwright_browsers as _ensure_playwright_browsers
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import decode_shard_payload
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import FrameType, decode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.qr.scan import scan_qr_payloads

PASS_PHRASE = "stable-v1_1-golden-passphrase"
_BINARY_PAYLOADS_MAGIC = b"EQPB"
_BINARY_PAYLOADS_VERSION = 1
_FROZEN_PROFILES: tuple[tuple[str, str], ...] = (("base64", "base64"), ("raw", "raw"))
_SHARD_SCENARIO_IDS: frozenset[str] = frozenset({"sharded_embedded", "sharded_signing_sharded"})


def _mint_support() -> Any:
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return importlib.import_module("tests.e2e._mint_fixture_support")


def _mint_snapshot_filename() -> str:
    return str(_mint_support().MINT_SNAPSHOT_FILENAME)


def _signing_key_payloads_text() -> str:
    return str(_mint_support().SIGNING_KEY_PAYLOADS_TEXT)


def _signing_key_payloads_binary() -> str:
    return str(_mint_support().SIGNING_KEY_PAYLOADS_BINARY)


def _mint_cases_for_scenario(scenario_id: str) -> tuple[Any, ...]:
    return tuple(_mint_support().mint_cases_for_scenario(scenario_id))


def _mint_cli_args(case: Any, scenario_root: Path, passphrase: str) -> list[str]:
    return list(_mint_support().mint_cli_args(case, scenario_root, passphrase))


def _include_scenario(scenario_id: str) -> bool:
    return scenario_id in _SHARD_SCENARIO_IDS


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


def _run_cli(repo_root: Path, args: list[str], xdg_config_home: Path, config_path: Path) -> None:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    cmd = [
        sys.executable,
        "-m",
        "ethernity.cli",
        "--config",
        str(config_path),
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


def _scan_payload_bytes(pdf_paths: list[Path]) -> list[bytes]:
    payloads = scan_qr_payloads([str(path) for path in pdf_paths])
    normalized: list[bytes] = []
    for payload in payloads:
        if isinstance(payload, bytes):
            normalized.append(payload)
        else:
            normalized.append(payload.encode("utf-8"))
    return normalized


def _write_payloads_text_file(payloads: list[bytes], destination: Path) -> None:
    normalized: list[str] = []
    for payload in payloads:
        encoded = encode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64)
        normalized.append(encoded.decode("ascii") if isinstance(encoded, bytes) else encoded)
    if not normalized:
        destination.write_text("", encoding="utf-8")
        return
    destination.write_text("\n".join(normalized) + "\n", encoding="utf-8")


def _write_payloads_binary_file(payloads: list[bytes], destination: Path) -> None:
    out = bytearray()
    out.extend(_BINARY_PAYLOADS_MAGIC)
    out.append(_BINARY_PAYLOADS_VERSION)
    out.extend(struct.pack(">I", len(payloads)))
    for payload in payloads:
        out.extend(struct.pack(">I", len(payload)))
        out.extend(payload)
    destination.write_bytes(bytes(out))


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


def _valid_scanned_frames(pdf_path: Path) -> list:
    payloads = scan_qr_payloads([str(pdf_path)])
    frames = []
    for payload in payloads:
        try:
            if isinstance(payload, bytes):
                frame = decode_frame(payload)
            else:
                frame = decode_frame(decode_qr_payload(payload))
        except ValueError:
            continue
        frames.append(frame)
    return frames


def _shard_projections_by_file(pdf_paths: list[Path]) -> dict[str, list[dict[str, object]]]:
    shard_set_labels: dict[str, str] = {}
    shard_projections: dict[str, list[dict[str, object]]] = {}
    for pdf_path in pdf_paths:
        projections: list[dict[str, object]] = []
        for frame in _valid_scanned_frames(pdf_path):
            payload = decode_shard_payload(frame.data)
            set_id = None if payload.shard_set_id is None else payload.shard_set_id.hex()
            if set_id is not None:
                set_id = shard_set_labels.setdefault(set_id, f"set-{len(shard_set_labels) + 1}")
            projections.append(
                {
                    "doc_id": frame.doc_id.hex(),
                    "version": payload.version,
                    "share_index": payload.share_index,
                    "threshold": payload.threshold,
                    "share_count": payload.share_count,
                    "key_type": payload.key_type,
                    "secret_len": payload.secret_len,
                    "doc_hash": payload.doc_hash.hex(),
                    "sign_pub": payload.sign_pub.hex(),
                    "set_id": set_id,
                }
            )
        shard_projections[pdf_path.name] = projections
    return shard_projections


def _required_threshold_from_shard_pdfs(pdf_paths: list[Path]) -> int:
    if not pdf_paths:
        return 0
    for frame in _valid_scanned_frames(pdf_paths[0]):
        return int(decode_shard_payload(frame.data).threshold)
    raise RuntimeError(f"failed to decode shard threshold from {pdf_paths[0]}")


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _config_with_qr_payload_codec(base_config: str, codec: str) -> str:
    return base_config.replace(
        'qr_payload_codec = "raw" # required: raw | base64',
        f'qr_payload_codec = "{codec}" # required: raw | base64',
        1,
    )


def _write_signing_key_payload_fixtures(scenario_root: Path) -> None:
    signing_key_paths = sorted((scenario_root / "backup").glob("signing-key-shard-*.pdf"))
    text_path = scenario_root / _signing_key_payloads_text()
    binary_path = scenario_root / _signing_key_payloads_binary()
    if not signing_key_paths:
        if text_path.exists():
            text_path.unlink()
        if binary_path.exists():
            binary_path.unlink()
        return
    threshold = _required_threshold_from_shard_pdfs(signing_key_paths)
    signing_key_payload_bytes = _scan_payload_bytes(signing_key_paths[:threshold])
    _write_payloads_text_file(signing_key_payload_bytes, text_path)
    _write_payloads_binary_file(signing_key_payload_bytes, binary_path)


def _write_mint_snapshot(
    repo_root: Path,
    *,
    scenario_root: Path,
    scenario_id: str,
    profile_name: str,
    profile_config_path: Path,
    xdg_config_home: Path,
) -> None:
    _write_signing_key_payload_fixtures(scenario_root)
    mint_cases: dict[str, object] = {}
    for mint_case in _mint_cases_for_scenario(scenario_id):
        mint_output_dir = scenario_root / "mint-output" / mint_case.case_id
        _run_cli(
            repo_root,
            _mint_cli_args(mint_case, scenario_root, PASS_PHRASE),
            xdg_config_home,
            profile_config_path,
        )
        mint_pdfs = sorted(mint_output_dir.glob("*.pdf"))
        mint_cases[mint_case.case_id] = {
            "shard_projections": _shard_projections_by_file(mint_pdfs),
            "expected_shard_pdfs": len(list(mint_output_dir.glob("shard-*.pdf"))),
            "expected_signing_key_shard_pdfs": len(
                list(mint_output_dir.glob("signing-key-shard-*.pdf"))
            ),
        }
        shutil.rmtree(mint_output_dir)
    mint_snapshot = {
        "scenario_id": scenario_id,
        "profile": profile_name,
        "mint_cases": mint_cases,
    }
    (scenario_root / _mint_snapshot_filename()).write_text(
        json.dumps(mint_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _generate_mint_golden() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    golden_root = repo_root / "tests" / "fixtures" / "v1_1" / "golden"
    os.environ.pop("ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", None)
    _ensure_playwright_browsers(quiet=True)

    with tempfile.TemporaryDirectory() as xdg_tmp:
        xdg_config_home = Path(xdg_tmp)
        base_config_path = repo_root / "src" / "ethernity" / "config" / "config.toml"
        base_config_text = base_config_path.read_text(encoding="utf-8")
        for profile_name, qr_codec in _FROZEN_PROFILES:
            profile_root = golden_root / profile_name
            profile_config_path = xdg_config_home / f"config_{profile_name}.toml"
            profile_config_path.write_text(
                _config_with_qr_payload_codec(base_config_text, qr_codec),
                encoding="utf-8",
            )
            profile_index = json.loads((profile_root / "index.json").read_text(encoding="utf-8"))
            for scenario in cast(list[dict[str, object]], profile_index["scenarios"]):
                scenario_id = str(scenario["id"])
                if not _include_scenario(scenario_id):
                    continue
                if not _mint_cases_for_scenario(scenario_id):
                    continue
                scenario_root = profile_root / scenario_id
                _write_mint_snapshot(
                    repo_root,
                    scenario_root=scenario_root,
                    scenario_id=scenario_id,
                    profile_name=profile_name,
                    profile_config_path=profile_config_path,
                    xdg_config_home=xdg_config_home,
                )


def _generate_full_golden() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    source_root = repo_root / "tests" / "fixtures" / "v1_0" / "source"
    golden_root = repo_root / "tests" / "fixtures" / "v1_1" / "golden"

    os.environ.pop("ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", None)
    _ensure_playwright_browsers(quiet=True)

    for child in golden_root.iterdir():
        if child.name in {"build_golden.py", "README.md"}:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    scenarios = [
        scenario
        for scenario in _scenario_definitions(source_root)
        if _include_scenario(str(scenario["id"]))
    ]
    index: dict[str, Any] = {
        "version": "1.1.0",
        "passphrase": PASS_PHRASE,
        "profiles": {},
    }

    with tempfile.TemporaryDirectory() as xdg_tmp:
        xdg_config_home = Path(xdg_tmp)
        base_config_path = repo_root / "src" / "ethernity" / "config" / "config.toml"
        base_config_text = base_config_path.read_text(encoding="utf-8")
        for profile_name, qr_codec in _FROZEN_PROFILES:
            profile_root = golden_root / profile_name
            profile_root.mkdir(parents=True, exist_ok=True)
            profile_index: dict[str, Any] = {
                "version": "1.1.0",
                "profile": profile_name,
                "qr_payload_codec": qr_codec,
                "passphrase": PASS_PHRASE,
                "scenarios": [],
            }
            profile_config_path = xdg_config_home / f"config_{profile_name}.toml"
            profile_config_path.write_text(
                _config_with_qr_payload_codec(base_config_text, qr_codec),
                encoding="utf-8",
            )
            for scenario in scenarios:
                backup_args_raw = cast(list[str], scenario["backup_args"])
                expected_relative_paths = cast(list[str], scenario["expected_relative_paths"])
                expected_source_root = cast(Path, scenario["expected_source_root"])
                shard_payload_count = cast(int, scenario["shard_payload_count"])
                scenario_id = str(scenario["id"])
                scenario_root = profile_root / scenario_id
                backup_dir = scenario_root / "backup"
                scenario_root.mkdir(parents=True, exist_ok=True)
                backup_args = [
                    "backup",
                    *backup_args_raw,
                    "--design",
                    "forge",
                    "--output-dir",
                    str(backup_dir),
                    "--quiet",
                ]
                _run_cli(repo_root, backup_args, xdg_config_home, profile_config_path)

                main_payloads = scenario_root / "main_payloads.txt"
                main_payloads_binary = scenario_root / "main_payloads.bin"
                main_payload_bytes = _scan_payload_bytes([backup_dir / "qr_document.pdf"])
                _write_payloads_text_file(main_payload_bytes, main_payloads)
                _write_payloads_binary_file(main_payload_bytes, main_payloads_binary)

                shard_paths = sorted(backup_dir.glob("shard-*.pdf"))
                shard_payloads_path = scenario_root / "shard_payloads_threshold.txt"
                shard_payloads_binary_path = scenario_root / "shard_payloads_threshold.bin"
                if shard_payload_count > 0:
                    shard_payload_bytes = _scan_payload_bytes(shard_paths[:shard_payload_count])
                    _write_payloads_text_file(shard_payload_bytes, shard_payloads_path)
                    _write_payloads_binary_file(shard_payload_bytes, shard_payloads_binary_path)
                else:
                    if shard_payloads_path.exists():
                        shard_payloads_path.unlink()
                    if shard_payloads_binary_path.exists():
                        shard_payloads_binary_path.unlink()
                _write_signing_key_payload_fixtures(scenario_root)
                signing_key_paths = sorted(backup_dir.glob("signing-key-shard-*.pdf"))

                artifact_hashes = {}
                for artifact in sorted(backup_dir.glob("*.pdf")):
                    artifact_hashes[artifact.name] = _file_sha256(artifact)
                artifact_hashes["main_payloads.txt"] = _file_sha256(main_payloads)
                artifact_hashes["main_payloads.bin"] = _file_sha256(main_payloads_binary)
                if shard_payload_count > 0:
                    artifact_hashes["shard_payloads_threshold.txt"] = _file_sha256(
                        shard_payloads_path
                    )
                    artifact_hashes["shard_payloads_threshold.bin"] = _file_sha256(
                        shard_payloads_binary_path
                    )
                signing_key_binary_path = scenario_root / _signing_key_payloads_binary()
                if signing_key_binary_path.exists():
                    artifact_hashes[_signing_key_payloads_text()] = _file_sha256(
                        scenario_root / _signing_key_payloads_text()
                    )
                    artifact_hashes[_signing_key_payloads_binary()] = _file_sha256(
                        signing_key_binary_path
                    )

                expected_files = {}
                for relative_path in expected_relative_paths:
                    source_path = expected_source_root / str(relative_path)
                    expected_files[str(relative_path)] = _file_sha256(source_path)

                snapshot = {
                    "scenario_id": scenario_id,
                    "profile": profile_name,
                    "qr_payload_codec": qr_codec,
                    "passphrase": PASS_PHRASE,
                    "expected_relative_paths": expected_relative_paths,
                    "expected_file_sha256": expected_files,
                    "artifact_hashes": artifact_hashes,
                    "backup_shard_projections": _shard_projections_by_file(
                        shard_paths + signing_key_paths
                    ),
                    "manifest_projection": _manifest_projection(main_payloads, PASS_PHRASE),
                    "shard_payload_count": shard_payload_count,
                    "expected_shard_pdfs": len(shard_paths),
                    "expected_signing_key_shard_pdfs": len(signing_key_paths),
                }
                (scenario_root / "snapshot.json").write_text(
                    json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if _mint_cases_for_scenario(scenario_id):
                    _write_mint_snapshot(
                        repo_root,
                        scenario_root=scenario_root,
                        scenario_id=scenario_id,
                        profile_name=profile_name,
                        profile_config_path=profile_config_path,
                        xdg_config_home=xdg_config_home,
                    )
                profile_index["scenarios"].append(
                    {
                        "id": scenario_id,
                        "path": f"{scenario_id}/snapshot.json",
                    }
                )

            (profile_root / "index.json").write_text(
                json.dumps(profile_index, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            index["profiles"][profile_name] = {
                "path": f"{profile_name}/index.json",
                "qr_payload_codec": qr_codec,
            }

    (golden_root / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mint-only", action="store_true")
    args = parser.parse_args()
    if args.mint_only:
        _generate_mint_golden()
        return
    _generate_full_golden()


if __name__ == "__main__":
    main()
