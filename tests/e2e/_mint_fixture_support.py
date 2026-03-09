from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MINT_SNAPSHOT_FILENAME = "mint_snapshot.json"
SIGNING_KEY_PAYLOADS_TEXT = "signing_key_shard_payloads_threshold.txt"
SIGNING_KEY_PAYLOADS_BINARY = "signing_key_shard_payloads_threshold.bin"


@dataclass(frozen=True)
class MintFrozenCase:
    case_id: str
    source_mode: str
    use_signing_key_shards: bool
    mint_passphrase_shards: bool
    mint_signing_key_shards: bool
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None


def mint_cases_for_scenario(scenario_id: str) -> tuple[MintFrozenCase, ...]:
    cases: dict[str, tuple[MintFrozenCase, ...]] = {
        "file_no_shard": (
            MintFrozenCase("embedded_both", "passphrase", False, True, True, 2, 3, 1, 2),
            MintFrozenCase("passphrase_only", "passphrase", False, True, False, 2, 4),
            MintFrozenCase("signing_only", "passphrase", False, False, True, None, None, 2, 3),
        ),
        "sharded_embedded": (
            MintFrozenCase(
                "embedded_from_passphrase_shards_both",
                "passphrase_shards",
                False,
                True,
                True,
                2,
                4,
                2,
                3,
            ),
        ),
        "sharded_signing_sharded": (
            MintFrozenCase(
                "external_signing_both", "passphrase_shards", True, True, True, 2, 4, 1, 3
            ),
            MintFrozenCase(
                "external_signing_only", "passphrase_shards", True, False, True, None, None, 2, 3
            ),
        ),
    }
    return cases.get(scenario_id, ())


def mint_cli_args(case: MintFrozenCase, scenario_root: Path, passphrase: str) -> list[str]:
    args = [
        "mint",
        "--payloads-file",
        str(scenario_root / "main_payloads.txt"),
        "--output-dir",
        str(scenario_root / "mint-output" / case.case_id),
        "--quiet",
    ]
    if case.source_mode == "passphrase":
        args.extend(["--passphrase", passphrase])
    elif case.source_mode == "passphrase_shards":
        args.extend(["--shard-payloads-file", str(scenario_root / "shard_payloads_threshold.txt")])
    else:
        raise ValueError(f"unsupported mint source mode: {case.source_mode}")
    if case.use_signing_key_shards:
        args.extend(
            ["--signing-key-shard-payloads-file", str(scenario_root / SIGNING_KEY_PAYLOADS_TEXT)]
        )
    if case.mint_passphrase_shards:
        args.extend(
            ["--shard-threshold", str(case.shard_threshold), "--shard-count", str(case.shard_count)]
        )
    else:
        args.append("--no-passphrase-shards")
    if case.mint_signing_key_shards:
        args.extend(
            [
                "--signing-key-shard-threshold",
                str(case.signing_key_shard_threshold),
                "--signing-key-shard-count",
                str(case.signing_key_shard_count),
            ]
        )
    else:
        args.append("--no-signing-key-shards")
    return args
