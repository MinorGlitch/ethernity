"""The generated assembler accepts arbitrary scan order and rejects damaged fragments."""

import gzip
import json
import subprocess
import zlib
from pathlib import Path

from ethernity.qr.codec import QrConfig
from ethernity.workflows.kit import printed, service as kit

_ROOT = Path(__file__).resolve().parents[2]


def _replace_data(fragment: str, data: str, *, index: int | None = None) -> str:
    fields = fragment.split(":", 6)
    if index is not None:
        fields[2] = f"{index:04X}"
    fields[4] = f"{len(data):04X}"
    prefix = ":".join(fields[:5]) + ":"
    return f"{prefix}{zlib.crc32((prefix + data).encode()):08X}:{data}"


def _check_cases(cases: list[dict], tmp_path: Path) -> None:
    input_path = tmp_path / "cases.json"
    input_path.write_text(json.dumps(cases))
    result = subprocess.run(
        ["node", str(_ROOT / "kit/tests/printed_kit_loader_check.mjs"), str(input_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Printed kit assembler checks passed" in result.stdout


def _encoded_case(encoded: str) -> dict:
    shell, code = [
        p.decode() for p in printed._startup_payloads(["0" * 12, 3, len(encoded), "gzip"])
    ]
    fragment = _replace_data("EK1:" + "0" * 12 + ":0003:0003:0001:00000000:0", encoded)
    return {"name": encoded, "shell": shell, "code": code, "scans": [fragment]}


def test_base44_decodes_all_block_lengths_and_rejects_overflow_before_gzip(tmp_path: Path) -> None:
    cases = []
    # Zeros, maximum values, and asymmetric byte patterns exercise leading zeros,
    # exact 120-bit arithmetic, byte order, full blocks, and every final block length.
    for size in range(1, 46):
        for data in (bytes(size), b"\xff" * size, bytes(range(size))):
            cases.append(
                {
                    **_encoded_case(printed.encode_base44(data)),
                    "decoded_hex": data.hex(),
                    "expected": "decoded",
                }
            )

    widths = (2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18, 20, 21, 22)
    invalid = ["0" * size for size in range(1, 22) if size not in widths]
    for byte_count, width in enumerate(widths, start=1):
        # First unrepresentable value for this byte count, still a valid Base44 number.
        value = 1 << (8 * byte_count)
        invalid.append(
            "".join(printed.BASE44_ALPHABET[(value // 44**i) % 44] for i in range(width))
        )
    for encoded in invalid:
        for prefix in ("", "0" * 22):
            cases.append(
                {**_encoded_case(prefix + encoded), "save_error": True, "invalid_base44": True}
            )
    _check_cases(cases, tmp_path)


def test_printed_loader_roundtrips_both_variants_and_rejects_bad_scans(tmp_path: Path) -> None:
    cases = []
    for name in (kit.DEFAULT_KIT_BUNDLE_NAME, kit.SCANNER_KIT_BUNDLE_NAME):
        bundle = (_ROOT / "src/ethernity/resources/kit" / name).read_bytes()
        metadata = kit._extract_kit_bundle_loader_metadata(bundle)
        expected = gzip.decompress(kit._decode_base91(metadata.payload, metadata.alphabet)).decode()
        for size in (1799, 1800, kit.DEFAULT_KIT_CHUNK_SIZE):
            startup, code, *parts = [
                p.decode() for p in kit.build_kit_qr_payloads(bundle, size, QrConfig())
            ]
            common = {"name": f"{name}, {size}", "shell": startup, "code": code}
            reordered = list(reversed(parts)) + [parts[0]]
            for separator in ("", "\n", "\r\n\t "):
                cases.append({**common, "scans": [separator.join(reordered)], "expected": expected})
            cases.append({**common, "scans": parts, "file": True, "expected": expected})
            cases.append({**common, "files": reordered, "scans": [], "expected": expected})
            cases.append({**common, "scans": parts[:-1], "missing": True})
            damaged = parts[0][:-1] + ("0" if parts[0][-1] != "0" else "1")
            cases.append(
                {**common, "scans": [parts[0], damaged], "error": "Damaged QR", "collected": 1}
            )
            cases.append(
                {
                    **common,
                    "files": [parts[0], damaged, parts[1]],
                    "scans": [],
                    "error": "Damaged QR",
                    "collected": 1,
                }
            )
            cases.append(
                {
                    **common,
                    "scans": [parts[0], _replace_data(parts[0], "000")],
                    "error": "Conflicting QR",
                    "collected": 1,
                }
            )
            cases.append(
                {**common, "scans": [parts[0][:-1]], "error": "Damaged QR", "collected": 0}
            )
            cases.append({**common, "scans": ["garbage"], "error": "Invalid scan", "collected": 0})
            other = parts[0][:4] + "FFFFFFFFFFFF" + parts[0][16:]
            cases.append({**common, "scans": [other], "error": "another kit", "collected": 0})
            cases.append(
                {
                    **common,
                    "scans": [_replace_data(parts[0], "000", index=0)],
                    "error": "Damaged QR",
                    "collected": 0,
                }
            )
            cases.append(
                {**common, "scans": [], "unsupported": True, "error": "Cannot open assembly page"}
            )
            # An invalid scan must not discard good parts or prevent a later successful retry.
            cases.append({**common, "scans": [parts[0] + damaged, *parts], "expected": expected})

    oversized = gzip.compress(b"x" * 1000001)
    shell, code, *parts = [
        p.decode() for p in printed.build_payloads(oversized, "gzip", 1800, QrConfig())
    ]
    cases.append(
        {
            "name": "decompression limit",
            "shell": shell,
            "code": code,
            "scans": parts,
            "save_error": True,
        }
    )

    _check_cases(cases, tmp_path)
