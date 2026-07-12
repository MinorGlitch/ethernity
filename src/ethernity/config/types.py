"""Config dataclasses and literal types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ethernity.qr.codec import QrConfig

PayloadCodec = Literal["auto", "raw", "gzip"]
QrPayloadCodec = Literal["raw", "base64"]
QrErrorCorrection = Literal["L", "M", "Q", "H"]
PageSize = Literal["A4", "LETTER"]
SigningKeyMode = Literal["embedded", "sharded"]
ExtensionUnlockPolicy = Literal["self-contained", "reuse-root"]
ExtensionSigningKeyMode = Literal["not-stored", "sharded"]


@dataclass(frozen=True)
class BackupDefaults:
    """Default CLI values for backup commands."""

    base_dir: str | None = None
    output_dir: str | None = None
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: SigningKeyMode | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    payload_codec: PayloadCodec = "auto"
    qr_payload_codec: QrPayloadCodec = "raw"


@dataclass(frozen=True)
class RecoverDefaults:
    """Default CLI values for recover commands."""

    output: str | None = None


@dataclass(frozen=True)
class ExtendDefaults:
    """Default CLI values for extension commands."""

    base_dir: str | None = None
    unlock_policy: ExtensionUnlockPolicy | None = None
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: ExtensionSigningKeyMode | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    qr_payload_codec: QrPayloadCodec = "raw"


@dataclass(frozen=True)
class UiDefaults:
    """Default CLI UI behavior flags."""

    quiet: bool = False
    no_color: bool = False
    no_animations: bool = False
    show_internals: bool = False


@dataclass(frozen=True)
class DebugDefaults:
    """Default debug output settings."""

    max_bytes: int | None = None


@dataclass(frozen=True)
class RuntimeDefaults:
    """Default runtime tuning knobs."""

    render_jobs: int | Literal["auto"] | None = None


@dataclass(frozen=True)
class ExtensionChunkingDefaults:
    """Default content-defined chunking profile for new extension chains."""

    target_size: int = 16 * 1024
    min_size: int = 4 * 1024
    max_size: int = 64 * 1024


@dataclass(frozen=True)
class CliDefaults:
    """Grouped defaults for CLI subcommands and UI behavior."""

    backup: BackupDefaults = field(default_factory=BackupDefaults)
    recover: RecoverDefaults = field(default_factory=RecoverDefaults)
    extend: ExtendDefaults = field(default_factory=ExtendDefaults)
    ui: UiDefaults = field(default_factory=UiDefaults)
    debug: DebugDefaults = field(default_factory=DebugDefaults)
    runtime: RuntimeDefaults = field(default_factory=RuntimeDefaults)


@dataclass(frozen=True)
class AppConfig:
    """Resolved application configuration used by runtime services."""

    design_name: str
    paper_size: str
    qr_config: QrConfig
    qr_chunk_size: int
    extension_chunking: ExtensionChunkingDefaults = field(default_factory=ExtensionChunkingDefaults)
    cli_defaults: CliDefaults = field(default_factory=CliDefaults)
