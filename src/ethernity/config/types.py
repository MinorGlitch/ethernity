"""Config dataclasses and literal types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from ethernity.formats.extension_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.formats.extension_document import ExtensionChunkingProfile
from ethernity.page_sizes import PaperSizeName
from ethernity.qr.codec import QrConfig

PayloadCodec = Literal["auto", "raw", "gzip"]
QrPayloadCodec = Literal["raw", "base64"]
QrErrorCorrection = Literal["L", "M", "Q", "H"]
PageSize: TypeAlias = PaperSizeName
SigningKeyMode = Literal["embedded", "sharded"]

# Application policy only; the extension format accepts any valid bounded profile.
DEFAULT_EXTENSION_CHUNKING_PROFILE = ExtensionChunkingProfile(
    algorithm_id=CHUNK_ALGORITHM_FASTCDC,
    target_size=16 * 1024,
    min_size=4 * 1024,
    max_size=64 * 1024,
)


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
class AddFilesDefaults:
    """Default CLI values for Add Files."""

    base_dir: str | None = None
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
class CliDefaults:
    """Grouped defaults for CLI subcommands and UI behavior."""

    backup: BackupDefaults = field(default_factory=BackupDefaults)
    recover: RecoverDefaults = field(default_factory=RecoverDefaults)
    add_files: AddFilesDefaults = field(default_factory=AddFilesDefaults)
    ui: UiDefaults = field(default_factory=UiDefaults)
    debug: DebugDefaults = field(default_factory=DebugDefaults)


@dataclass(frozen=True)
class AppConfig:
    """Resolved application configuration used by runtime services."""

    design_name: str
    paper_size: PaperSizeName
    qr_config: QrConfig
    qr_chunk_size: int
    extension_chunking: ExtensionChunkingProfile = DEFAULT_EXTENSION_CHUNKING_PROFILE
    cli_defaults: CliDefaults = field(default_factory=CliDefaults)
