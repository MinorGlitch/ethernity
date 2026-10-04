from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPLACEMENT_SNAPSHOT_FILENAME = "mint_snapshot.json"
SIGNING_KEY_PAYLOADS_TEXT = "signing_key_shard_payloads_threshold.txt"
SIGNING_KEY_PAYLOADS_BINARY = "signing_key_shard_payloads_threshold.bin"


@dataclass(frozen=True)
class ReplacementFrozenCase:
    case_id: str
    source_mode: str
    use_signing_key_shards: bool
    create_passphrase_shards: bool
    create_signing_key_shards: bool
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None


def replacement_cases_for_scenario(scenario_id: str) -> tuple[ReplacementFrozenCase, ...]:
    cases: dict[str, tuple[ReplacementFrozenCase, ...]] = {
        "file_no_shard": (
            ReplacementFrozenCase("embedded_both", "passphrase", False, True, True, 2, 3, 1, 2),
            ReplacementFrozenCase("passphrase_only", "passphrase", False, True, False, 2, 4),
            ReplacementFrozenCase(
                "signing_only", "passphrase", False, False, True, None, None, 2, 3
            ),
        ),
        "sharded_embedded": (
            ReplacementFrozenCase(
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
            ReplacementFrozenCase(
                "external_signing_both", "passphrase_shards", True, True, True, 2, 4, 1, 3
            ),
            ReplacementFrozenCase(
                "external_signing_only", "passphrase_shards", True, False, True, None, None, 2, 3
            ),
        ),
    }
    return cases.get(scenario_id, ())


def replacement_cli_args(
    case: ReplacementFrozenCase, scenario_root: Path, passphrase: str
) -> list[str]:
    args = [
        "replace-recovery-docs",
        "--payloads-file",
        str(scenario_root / "main_payloads.txt"),
        "--output-dir",
        str(scenario_root / "replacement-output" / case.case_id),
        "--yes",
    ]
    if case.source_mode == "passphrase":
        args.extend(["--passphrase", passphrase])
    elif case.source_mode == "passphrase_shards":
        args.extend(
            ["--recovery-payloads-file", str(scenario_root / "shard_payloads_threshold.txt")]
        )
    else:
        raise ValueError(f"unsupported replacement source mode: {case.source_mode}")
    if case.use_signing_key_shards:
        args.extend(["--signing-key-payloads-file", str(scenario_root / SIGNING_KEY_PAYLOADS_TEXT)])
    if case.create_passphrase_shards:
        args.extend(
            [
                "--recovery-threshold",
                str(case.shard_threshold),
                "--recovery-count",
                str(case.shard_count),
            ]
        )
    else:
        args.append("--no-passphrase-recovery")
    if case.create_signing_key_shards:
        args.extend(
            [
                "--signing-key-recovery",
                "--signing-key-threshold",
                str(case.signing_key_shard_threshold),
                "--signing-key-count",
                str(case.signing_key_shard_count),
            ]
        )
    return args
