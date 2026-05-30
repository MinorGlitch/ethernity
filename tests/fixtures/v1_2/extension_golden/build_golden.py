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
import struct
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ethernity.cli.bootstrap.startup import ensure_playwright_browsers
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import decode_shard_payload
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import FrameType, decode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.formats.envelope_codec import decode_any_envelope, extract_payloads
from ethernity.formats.extension_envelope import ExtensionEnvelope
from ethernity.formats.extension_envelope_constants import CHUNK_CODEC_GZIP, CHUNK_CODEC_RAW
from ethernity.qr.scan import scan_qr_payloads

PASS_PHRASE = "stable-v1_2-extension-passphrase"
V1_0_PASS_PHRASE = "stable-v1-baseline-passphrase"
FIXED_MTIME = 1_700_200_000
BINARY_PAYLOADS_MAGIC = b"EQPB"
BINARY_PAYLOADS_VERSION = 1
PROFILES = (("base64", "base64"), ("raw", "raw"))


def _scenarios() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "large_raw_two_extension_chain",
            "profiles": ("base64", "raw"),
            "payload_codec": "raw",
            "builder": _build_large_raw_two_extension_chain,
            "checks": [
                "40 KiB raw root",
                "20 KiB and 28 KiB raw extension updates",
                "latest, index, and doc-hash selection",
            ],
        },
        {
            "id": "gzip_replacement_chain",
            "profiles": ("base64", "raw"),
            "payload_codec": "gzip",
            "builder": _build_gzip_replacement_chain,
            "checks": [
                "gzip-coded root replay",
                "gzip-coded extension chunks",
                "replacement, inherited files, and empty files",
            ],
        },
        {
            "id": "extension_local_sharded_chain",
            "profiles": ("raw",),
            "payload_codec": "raw",
            "builder": _build_extension_local_sharded_chain,
            "checks": ["extension-local shards", "extension signing-key shards"],
        },
        {
            "id": "reuse_root_shards_chain",
            "profiles": ("raw",),
            "payload_codec": "raw",
            "builder": _build_reuse_root_shards_chain,
            "checks": ["root shards reused by extension", "no extension passphrase shards"],
        },
        {
            "id": "loose_scan_append_chain",
            "profiles": ("raw",),
            "payload_codec": "raw",
            "builder": _build_loose_scan_append_chain,
            "checks": ["renamed scan import", "loose extension append layout"],
        },
        {
            "id": "v1_0_root_plus_v1_2_extension",
            "profiles": ("base64",),
            "payload_codec": "raw",
            "builder": _build_v1_0_root_plus_v1_2_extension,
            "checks": ["frozen v1.0 root compatibility"],
        },
    )


def _run_cli(repo_root: Path, args: list[str], *, config_path: Path, xdg_home: Path) -> None:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_home)
    result = subprocess.run(
        [sys.executable, "-m", "ethernity.cli", "--config", str(config_path), *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def _profile_config(base_config: str, *, qr_codec: str, payload_codec: str) -> str:
    text = base_config.replace(
        'qr_payload_codec = "raw" # required: raw | base64',
        f'qr_payload_codec = "{qr_codec}" # required: raw | base64',
        1,
    )
    return text.replace(
        'payload_codec = "auto" # one of: auto | raw | gzip',
        f'payload_codec = "{payload_codec}" # one of: auto | raw | gzip',
        1,
    )


def _write_file(path: Path, data: bytes, *, mtime_offset: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    mtime = FIXED_MTIME + mtime_offset
    os.utime(path, (mtime, mtime))


def _random_bytes(label: str, size: int) -> bytes:
    out = bytearray()
    counter = 0
    seed = label.encode("ascii")
    while len(out) < size:
        out.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:size])


def _compressible_bytes(label: str, size: int) -> bytes:
    pattern = (f"{label}|0123456789abcdef|").encode("ascii")
    return (pattern * ((size // len(pattern)) + 1))[:size]


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _backup(
    repo_root: Path,
    xdg_home: Path,
    config_path: Path,
    *,
    source_dir: Path,
    chain_dir: Path,
    passphrase: str,
    shards: tuple[int, int] | None = None,
) -> None:
    args = [
        "backup",
        "--input-dir",
        str(source_dir),
        "--base-dir",
        str(source_dir),
        "--passphrase",
        passphrase,
        "--design",
        "sentinel",
        "--output-dir",
        str(chain_dir),
        "--quiet",
    ]
    if shards is not None:
        args.extend(["--shard-threshold", str(shards[0]), "--shard-count", str(shards[1])])
    _run_cli(repo_root, args, config_path=config_path, xdg_home=xdg_home)


def _extend(
    repo_root: Path,
    xdg_home: Path,
    config_path: Path,
    *,
    source_dir: Path,
    root_dir: Path,
    passphrase: str | None,
    scans: tuple[Path, ...] = (),
    shard_threshold: int | None = None,
    shard_count: int | None = 0,
    unlock_policy: str | None = None,
    signing_key_shards: bool = False,
) -> None:
    args = [
        "extend",
        "--root-dir",
        str(root_dir),
        "--input-dir",
        str(source_dir),
        "--base-dir",
        str(source_dir),
        "--design",
        "sentinel",
        "--quiet",
    ]
    for scan in scans:
        args.extend(["--scan", str(scan)])
    if passphrase is not None:
        args.extend(["--passphrase", passphrase])
    if unlock_policy is not None:
        args.extend(["--unlock-policy", unlock_policy])
    if shard_threshold is not None:
        args.extend(["--shard-threshold", str(shard_threshold)])
    if shard_count is not None:
        args.extend(["--shard-count", str(shard_count)])
    if signing_key_shards:
        args.extend(
            [
                "--signing-key-mode",
                "sharded",
                "--signing-key-shard-threshold",
                "1",
                "--signing-key-shard-count",
                "2",
            ]
        )
    _run_cli(repo_root, args, config_path=config_path, xdg_home=xdg_home)


def _extension_qr(root_dir: Path, index: int, *, loose: bool = False) -> Path:
    if loose:
        matches = sorted(root_dir.glob(f"extension-{index:02d}-*/qr_document-*.pdf"))
    else:
        matches = sorted((root_dir / "extensions" / f"{index:02d}").glob("qr_document-*.pdf"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one extension {index} QR document under {root_dir}")
    return matches[0]


def _root_and_extensions(root_dir: Path, count: int) -> tuple[Path, ...]:
    extensions = tuple(_extension_qr(root_dir, index) for index in range(1, count + 1))
    return (root_dir / "qr_document.pdf", *extensions)


def _build_large_raw_two_extension_chain(
    repo_root: Path,
    scenario_root: Path,
    xdg_home: Path,
    config_path: Path,
) -> dict[str, Any]:
    source = scenario_root / "source"
    chain = scenario_root / "chain"
    _write_file(source / "root-40960.bin", _random_bytes("root", 40 * 1024))
    _backup(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        chain_dir=chain,
        passphrase=PASS_PHRASE,
    )
    states = {"root": _hash_tree(source)}
    _write_file(
        source / "extension-one-20480.bin",
        _random_bytes("ext-one", 20 * 1024),
        mtime_offset=10,
    )
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=chain,
        passphrase=PASS_PHRASE,
    )
    states["extension_01"] = _hash_tree(source)
    _write_file(
        source / "extension-two-28672.bin",
        _random_bytes("ext-two", 28 * 1024),
        mtime_offset=20,
    )
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=chain,
        passphrase=PASS_PHRASE,
    )
    states["extension_02"] = _hash_tree(source)
    documents = _root_and_extensions(chain, 2)
    return _built(
        chain=chain,
        scans=(chain,),
        documents=documents,
        states=states,
        passphrase=PASS_PHRASE,
    )


def _build_gzip_replacement_chain(
    repo_root: Path,
    scenario_root: Path,
    xdg_home: Path,
    config_path: Path,
) -> dict[str, Any]:
    source = scenario_root / "source"
    chain = scenario_root / "chain"
    _write_file(source / "alpha.txt", _compressible_bytes("root-alpha", 18 * 1024))
    _write_file(source / "nested" / "inherited.txt", b"inherited from root\n")
    _write_file(source / "empty-at-root.txt", b"")
    _backup(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        chain_dir=chain,
        passphrase=PASS_PHRASE,
    )
    states = {"root": _hash_tree(source)}
    _write_file(
        source / "alpha.txt",
        _compressible_bytes("extension-alpha-replacement", 24 * 1024),
        mtime_offset=30,
    )
    _write_file(source / "new-empty.txt", b"", mtime_offset=31)
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=chain,
        passphrase=PASS_PHRASE,
    )
    states["extension_01"] = _hash_tree(source)
    documents = _root_and_extensions(chain, 1)
    return _built(
        chain=chain,
        scans=(chain,),
        documents=documents,
        states=states,
        passphrase=PASS_PHRASE,
    )


def _build_extension_local_sharded_chain(
    repo_root: Path,
    scenario_root: Path,
    xdg_home: Path,
    config_path: Path,
) -> dict[str, Any]:
    source = scenario_root / "source"
    chain = scenario_root / "chain"
    _write_file(source / "alpha.txt", b"root alpha\n")
    _backup(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        chain_dir=chain,
        passphrase=PASS_PHRASE,
    )
    states = {"root": _hash_tree(source)}
    _write_file(source / "alpha.txt", b"extension local alpha\n", mtime_offset=40)
    _write_file(source / "beta.txt", b"extension local beta\n", mtime_offset=41)
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=chain,
        passphrase=PASS_PHRASE,
        shard_threshold=2,
        shard_count=3,
        signing_key_shards=True,
    )
    states["extension_01"] = _hash_tree(source)
    documents = _root_and_extensions(chain, 1)
    return _built(
        chain=chain,
        scans=(chain,),
        documents=documents,
        states=states,
        passphrase=PASS_PHRASE,
    )


def _build_reuse_root_shards_chain(
    repo_root: Path,
    scenario_root: Path,
    xdg_home: Path,
    config_path: Path,
) -> dict[str, Any]:
    source = scenario_root / "source"
    chain = scenario_root / "chain"
    _write_file(source / "alpha.txt", b"root shard alpha\n")
    _backup(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        chain_dir=chain,
        passphrase=PASS_PHRASE,
        shards=(2, 3),
    )
    states = {"root": _hash_tree(source)}
    _write_file(source / "alpha.txt", b"reuse root shard extension alpha\n", mtime_offset=50)
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=chain,
        passphrase=PASS_PHRASE,
        unlock_policy="reuse-root",
        shard_count=None,
    )
    states["extension_01"] = _hash_tree(source)
    documents = _root_and_extensions(chain, 1)
    return _built(
        chain=chain,
        scans=(chain,),
        documents=documents,
        states=states,
        passphrase=PASS_PHRASE,
    )


def _build_loose_scan_append_chain(
    repo_root: Path,
    scenario_root: Path,
    xdg_home: Path,
    config_path: Path,
) -> dict[str, Any]:
    source = scenario_root / "source"
    original = scenario_root / "original_chain"
    scans_dir = scenario_root / "loose_scans"
    loose_chain = scenario_root / "loose_chain"
    scans_dir.mkdir(parents=True)
    _write_file(source / "alpha.txt", b"root loose alpha\n")
    _backup(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        chain_dir=original,
        passphrase=PASS_PHRASE,
    )
    states = {"root": _hash_tree(source)}
    _write_file(source / "alpha.txt", b"first loose extension alpha\n", mtime_offset=60)
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=original,
        passphrase=PASS_PHRASE,
    )
    states["extension_01"] = _hash_tree(source)
    root_scan = scans_dir / "phone-root-carrier.pdf"
    ext1_scan = scans_dir / "wallet-extension-one.pdf"
    shutil.copy2(original / "qr_document.pdf", root_scan)
    shutil.copy2(_extension_qr(original, 1), ext1_scan)
    _write_file(source / "alpha.txt", b"second loose extension alpha\n", mtime_offset=70)
    _write_file(source / "beta.txt", b"second loose extension beta\n", mtime_offset=71)
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=loose_chain,
        passphrase=PASS_PHRASE,
        scans=(root_scan, ext1_scan),
    )
    states["extension_02"] = _hash_tree(source)
    ext2 = _extension_qr(loose_chain, 2, loose=True)
    shutil.rmtree(original)
    return _built(
        chain=loose_chain,
        scans=(root_scan, ext1_scan, loose_chain),
        documents=(root_scan, ext1_scan, ext2),
        states=states,
        passphrase=PASS_PHRASE,
    )


def _build_v1_0_root_plus_v1_2_extension(
    repo_root: Path,
    scenario_root: Path,
    xdg_home: Path,
    config_path: Path,
) -> dict[str, Any]:
    source = scenario_root / "source"
    chain = scenario_root / "chain"
    v1_root = repo_root / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
    v1_source = repo_root / "tests" / "fixtures" / "v1_0" / "source" / "standalone_secret.txt"
    shutil.copytree(v1_root / "backup", chain)
    source.mkdir(parents=True)
    shutil.copy2(v1_source, source / "standalone_secret.txt")
    states = {"root": _hash_tree(source)}
    _write_file(source / "extension_note.txt", b"added after frozen v1.0 root\n", mtime_offset=80)
    _extend(
        repo_root,
        xdg_home,
        config_path,
        source_dir=source,
        root_dir=chain,
        passphrase=V1_0_PASS_PHRASE,
    )
    states["extension_01"] = _hash_tree(source)
    documents = _root_and_extensions(chain, 1)
    return _built(
        chain=chain,
        scans=(chain,),
        documents=documents,
        states=states,
        passphrase=V1_0_PASS_PHRASE,
    )


def _built(
    *,
    chain: Path,
    scans: tuple[Path, ...],
    documents: tuple[Path, ...],
    states: dict[str, dict[str, str]],
    passphrase: str,
) -> dict[str, Any]:
    named_documents = {"root": (documents[0],), "chain": documents}
    for index, document in enumerate(documents[1:], start=1):
        named_documents[f"extension_{index:02d}"] = (document,)
    return {
        "chain": chain,
        "scans": scans,
        "documents": named_documents,
        "states": states,
        "passphrase": passphrase,
    }


def _scan_payload_bytes(pdf_paths: tuple[Path, ...]) -> list[bytes]:
    payloads = scan_qr_payloads([str(path) for path in pdf_paths])
    return [
        payload if isinstance(payload, bytes) else payload.encode("utf-8") for payload in payloads
    ]


def _write_payload_text(payloads: list[bytes], path: Path) -> None:
    lines = []
    for payload in payloads:
        encoded = encode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64)
        lines.append(encoded.decode("ascii") if isinstance(encoded, bytes) else encoded)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_payload_binary(payloads: list[bytes], path: Path) -> None:
    out = bytearray(BINARY_PAYLOADS_MAGIC)
    out.append(BINARY_PAYLOADS_VERSION)
    out.extend(struct.pack(">I", len(payloads)))
    for payload in payloads:
        out.extend(struct.pack(">I", len(payload)))
        out.extend(payload)
    path.write_bytes(bytes(out))


def _write_payload_fixtures(
    scenario_root: Path,
    documents: dict[str, tuple[Path, ...]],
) -> dict[str, Any]:
    fixtures = {}
    for name, paths in sorted(documents.items()):
        payloads = _scan_payload_bytes(paths)
        text_path = scenario_root / f"{name}_payloads.txt"
        binary_path = scenario_root / f"{name}_payloads.bin"
        _write_payload_text(payloads, text_path)
        _write_payload_binary(payloads, binary_path)
        fixtures[name] = {
            "text": text_path.relative_to(scenario_root).as_posix(),
            "binary": binary_path.relative_to(scenario_root).as_posix(),
            "frame_count": len(payloads),
        }
    return fixtures


def _write_shard_fixture(
    scenario_root: Path,
    name: str,
    pdfs: list[Path],
) -> dict[str, Any] | None:
    if not pdfs:
        return None
    threshold = _shard_threshold(pdfs[0])
    selected = pdfs[:threshold]
    payloads = _scan_payload_bytes(tuple(selected))
    text_path = scenario_root / f"{name}_payloads_threshold.txt"
    binary_path = scenario_root / f"{name}_payloads_threshold.bin"
    _write_payload_text(payloads, text_path)
    _write_payload_binary(payloads, binary_path)
    return {
        "text": text_path.relative_to(scenario_root).as_posix(),
        "binary": binary_path.relative_to(scenario_root).as_posix(),
        "threshold": threshold,
        "pdf_count": len(pdfs),
        "projection": _shard_projection(pdfs),
    }


def _shard_threshold(pdf: Path) -> int:
    for frame in _frames_from_pdf(pdf):
        return int(decode_shard_payload(frame.data).threshold)
    raise RuntimeError(f"could not decode shard threshold from {pdf}")


def _shard_projection(pdfs: list[Path]) -> dict[str, Any]:
    labels: dict[str, str] = {}
    out = {}
    for pdf in pdfs:
        rows = []
        for frame in _frames_from_pdf(pdf):
            payload = decode_shard_payload(frame.data)
            set_id = None if payload.shard_set_id is None else payload.shard_set_id.hex()
            if set_id is not None:
                set_id = labels.setdefault(set_id, f"set-{len(labels) + 1}")
            rows.append(
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
        out[pdf.name] = rows
    return out


def _frames_from_pdf(pdf: Path) -> list[Any]:
    frames = []
    for payload in scan_qr_payloads([str(pdf)]):
        try:
            raw = payload if isinstance(payload, bytes) else decode_qr_payload(payload)
            frames.append(decode_frame(raw))
        except ValueError:
            continue
    return frames


def _document_projection(payloads_file: Path, passphrase: str) -> list[dict[str, Any]]:
    frames = [
        decode_frame(decode_qr_payload(line.strip()))
        for line in payloads_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    doc_ids = sorted(
        {frame.doc_id for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT}
    )
    projection = []
    for doc_id in doc_ids:
        main_frames = [
            frame
            for frame in frames
            if frame.doc_id == doc_id and frame.frame_type == FrameType.MAIN_DOCUMENT
        ]
        ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
        plaintext = decrypt_bytes(ciphertext, passphrase=passphrase)
        version, decoded = decode_any_envelope(plaintext)
        doc_hash = hashlib.blake2b(ciphertext, digest_size=32).hexdigest()
        if version == 1:
            manifest, payload = decoded
            projection.append(
                {
                    "kind": "root",
                    "doc_id": doc_id.hex(),
                    "doc_hash": doc_hash,
                    "payload_codec": manifest.payload_codec,
                    "payload_raw_len": manifest.payload_raw_len,
                    "sealed": manifest.sealed,
                    "files": [
                        {"path": entry.path, "size": entry.size, "sha256": entry.sha256.hex()}
                        for entry, _data in extract_payloads(manifest, payload)
                    ],
                }
            )
        elif isinstance(decoded, ExtensionEnvelope):
            projection.append(
                _extension_projection(decoded, doc_id=doc_id.hex(), doc_hash=doc_hash)
            )
        else:
            raise RuntimeError("unexpected decoded envelope")
    return sorted(projection, key=lambda item: (item["kind"], item["doc_hash"]))


def _extension_projection(
    document: ExtensionEnvelope,
    *,
    doc_id: str,
    doc_hash: str,
) -> dict[str, Any]:
    codec_names = {CHUNK_CODEC_RAW: "raw", CHUNK_CODEC_GZIP: "gzip"}
    return {
        "kind": "extension",
        "doc_id": doc_id,
        "doc_hash": doc_hash,
        "index": document.header.index,
        "parent_doc_hash": document.header.parent_doc_hash.hex(),
        "root_doc_hash": document.header.root_doc_hash.hex(),
        "files": [
            {"path": item.path, "size": item.size, "sha256": item.sha256.hex()}
            for item in document.files
        ],
        "chunks": [
            {
                "chunk_id": chunk.chunk_id.hex(),
                "codec": codec_names[chunk.codec],
                "raw_len": chunk.raw_len,
                "stored_len": len(chunk.data),
                "decoded_sha256": hashlib.sha256(chunk.decode_data()).hexdigest(),
            }
            for chunk in document.chunks
        ],
    }


def _artifact_hashes(root: Path) -> dict[str, str]:
    suffixes = {".pdf", ".txt", ".bin"}
    return {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in suffixes
    }


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _shard_fixtures(scenario_root: Path, chain: Path) -> dict[str, Any]:
    extensions_dir = chain / "extensions"
    extension_dirs = sorted(extensions_dir.glob("[0-9][0-9]")) if extensions_dir.exists() else []
    extension_dirs += sorted(chain.glob("extension-[0-9][0-9]-*"))
    root_shards = sorted(chain.glob("shard-*.pdf"))
    extension_shards = [
        path for item in extension_dirs for path in sorted(item.glob("shard-*.pdf"))
    ]
    signing_shards = [
        path for item in extension_dirs for path in sorted(item.glob("signing-key-shard-*.pdf"))
    ]
    fixtures = {}
    for key, name, pdfs in (
        ("root", "root_shard", root_shards),
        ("extension", "extension_shard", extension_shards),
        ("signing_key", "signing_key_shard", signing_shards),
    ):
        fixture = _write_shard_fixture(scenario_root, name, pdfs)
        if fixture is not None:
            fixtures[key] = fixture
    return fixtures


def _generate_scenario(
    repo_root: Path,
    profile_root: Path,
    xdg_home: Path,
    config_path: Path,
    scenario: dict[str, Any],
) -> dict[str, str]:
    scenario_root = profile_root / str(scenario["id"])
    scenario_root.mkdir(parents=True, exist_ok=False)
    builder = scenario["builder"]
    if not isinstance(builder, Callable):
        raise TypeError("scenario builder must be callable")
    built = builder(repo_root, scenario_root, xdg_home, config_path)
    payload_fixtures = _write_payload_fixtures(scenario_root, built["documents"])
    shard_fixtures = _shard_fixtures(scenario_root, built["chain"])
    source = scenario_root / "source"
    if source.exists():
        shutil.rmtree(source)
    projection = _document_projection(
        scenario_root / payload_fixtures["chain"]["text"],
        str(built["passphrase"]),
    )
    root_projection = next(item for item in projection if item["kind"] == "root")
    extension_doc_hashes = {
        f"extension_{item['index']:02d}": item["doc_hash"]
        for item in projection
        if item["kind"] == "extension"
    }
    snapshot = {
        "scenario_id": scenario["id"],
        "version": "1.2.0",
        "profile": profile_root.name,
        "qr_payload_codec": profile_root.name,
        "passphrase": built["passphrase"],
        "checks": scenario["checks"],
        "scan_paths": [path.relative_to(scenario_root).as_posix() for path in built["scans"]],
        "chain_dir": built["chain"].relative_to(scenario_root).as_posix(),
        "payload_fixtures": payload_fixtures,
        "shard_fixtures": shard_fixtures,
        "states": built["states"],
        "root_doc_hash": root_projection["doc_hash"],
        "extension_doc_hashes": extension_doc_hashes,
        "document_projection": projection,
        "artifact_hashes": _artifact_hashes(scenario_root),
    }
    (scenario_root / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"id": str(scenario["id"]), "path": f"{scenario['id']}/snapshot.json"}


def main() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    golden_root = repo_root / "tests" / "fixtures" / "v1_2" / "extension_golden"
    ensure_playwright_browsers(quiet=True)
    for child in golden_root.iterdir():
        if child.name in {"README.md", "build_golden.py"}:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    base_config = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    index: dict[str, Any] = {"version": "1.2.0", "passphrase": PASS_PHRASE, "profiles": {}}
    with tempfile.TemporaryDirectory() as tmp:
        xdg_home = Path(tmp)
        for profile_name, qr_codec in PROFILES:
            profile_root = golden_root / profile_name
            profile_root.mkdir(parents=True)
            profile_index: dict[str, Any] = {
                "version": "1.2.0",
                "profile": profile_name,
                "qr_payload_codec": qr_codec,
                "passphrase": PASS_PHRASE,
                "scenarios": [],
            }
            for scenario in _scenarios():
                if profile_name not in scenario["profiles"]:
                    continue
                config_path = xdg_home / f"{profile_name}_{scenario['id']}.toml"
                config_path.write_text(
                    _profile_config(
                        base_config,
                        qr_codec=qr_codec,
                        payload_codec=str(scenario["payload_codec"]),
                    ),
                    encoding="utf-8",
                )
                profile_index["scenarios"].append(
                    _generate_scenario(repo_root, profile_root, xdg_home, config_path, scenario)
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


if __name__ == "__main__":
    main()
