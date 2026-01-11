import hashlib
import io
import os
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Generator
from unittest import mock

from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    ShardPayload,
    split_passphrase,
)
from ethernity.crypto.signing import (
    DOC_HASH_LEN,
    ED25519_PUB_LEN,
    ED25519_SEED_LEN,
    ED25519_SIG_LEN,
    generate_signing_keypair,
)
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.formats.envelope_codec import (
    EnvelopeManifest,
    build_manifest_and_payload,
    encode_envelope,
)
from ethernity.formats.envelope_types import ManifestFile, PayloadPart

# =============================================================================
# Test Constants
# =============================================================================

TEST_PASSPHRASE = "correct-horse-battery-staple"
TEST_DOC_ID = b"\x10" * DOC_ID_LEN
TEST_DOC_HASH = b"\x20" * DOC_HASH_LEN
TEST_SIGNING_SEED = b"\x5a" * ED25519_SEED_LEN
TEST_SIGNING_PUB = b"\x6b" * ED25519_PUB_LEN
TEST_SIGNATURE = b"\x7c" * ED25519_SIG_LEN
TEST_PAYLOAD = b"test payload data"


# =============================================================================
# Environment Helpers
# =============================================================================


@contextmanager
def temp_env(overrides: dict[str, str], *, clear: bool = False):
    with mock.patch.dict(os.environ, overrides, clear=clear):
        yield


@contextmanager
def with_playwright_skip():
    with temp_env({"ETHERNITY_SKIP_PLAYWRIGHT_INSTALL": "1"}):
        yield


def build_cli_env(
    *, overrides: dict[str, str] | None = None, skip_playwright: bool = True
) -> dict[str, str]:
    env = os.environ.copy()
    if skip_playwright:
        env["ETHERNITY_SKIP_PLAYWRIGHT_INSTALL"] = "1"
    if overrides:
        env.update(overrides)
    return env


@contextmanager
def suppress_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        yield


# =============================================================================
# Frame Builders
# =============================================================================


def make_test_frame(
    *,
    data: bytes = TEST_PAYLOAD,
    doc_id: bytes | None = None,
    frame_type: FrameType = FrameType.MAIN_DOCUMENT,
    index: int = 0,
    total: int = 1,
    version: int = 1,
) -> Frame:
    """Create a test frame with sensible defaults."""
    return Frame(
        version=version,
        frame_type=frame_type,
        doc_id=doc_id or TEST_DOC_ID,
        index=index,
        total=total,
        data=data,
    )


def make_test_frames(
    count: int,
    *,
    data: bytes = TEST_PAYLOAD,
    doc_id: bytes | None = None,
    frame_type: FrameType = FrameType.MAIN_DOCUMENT,
) -> list[Frame]:
    """Create multiple test frames with sequential indices."""
    return [
        make_test_frame(
            data=data,
            doc_id=doc_id,
            frame_type=frame_type,
            index=i,
            total=count,
        )
        for i in range(count)
    ]


# =============================================================================
# Crypto Helpers
# =============================================================================


def make_test_keypair() -> tuple[bytes, bytes]:
    """Generate a consistent test keypair (actually generates a real one)."""
    return generate_signing_keypair()


def make_test_shards(
    count: int = 3,
    threshold: int = 2,
    *,
    passphrase: str = TEST_PASSPHRASE,
    doc_hash: bytes | None = None,
) -> list[ShardPayload]:
    """Create test shard payloads with real cryptographic values."""
    sign_priv, sign_pub = generate_signing_keypair()
    return split_passphrase(
        passphrase,
        threshold=threshold,
        shares=count,
        doc_hash=doc_hash or TEST_DOC_HASH,
        sign_priv=sign_priv,
        sign_pub=sign_pub,
    )


def make_fake_shard(
    *,
    index: int = 1,
    threshold: int = 2,
    shares: int = 3,
    key_type: str = KEY_TYPE_PASSPHRASE,
    share: bytes | None = None,
    secret_len: int = 16,
    doc_hash: bytes | None = None,
    sign_pub: bytes | None = None,
    signature: bytes | None = None,
) -> ShardPayload:
    """Create a fake shard payload (not cryptographically valid)."""
    return ShardPayload(
        index=index,
        threshold=threshold,
        shares=shares,
        key_type=key_type,
        share=share or b"\x01" * 16,
        secret_len=secret_len,
        doc_hash=doc_hash or TEST_DOC_HASH,
        sign_pub=sign_pub or TEST_SIGNING_PUB,
        signature=signature or TEST_SIGNATURE,
    )


# =============================================================================
# Envelope/Manifest Helpers
# =============================================================================


def make_test_manifest(
    *,
    files: list[tuple[str, bytes]] | None = None,
    sealed: bool = False,
    created_at: float = 0.0,
    signing_seed: bytes | None = None,
) -> tuple[EnvelopeManifest, bytes]:
    """Create a test manifest with payload."""
    if files is None:
        files = [("test.bin", TEST_PAYLOAD)]
    parts = [PayloadPart(path=path, data=data, mtime=0) for path, data in files]
    return build_manifest_and_payload(
        parts,
        sealed=sealed,
        created_at=created_at,
        signing_seed=signing_seed,
    )


def make_test_envelope(
    *,
    payload: bytes = TEST_PAYLOAD,
    filename: str = "test.bin",
    sealed: bool = False,
) -> tuple[bytes, EnvelopeManifest]:
    """Create a test envelope with defaults."""
    manifest, _ = make_test_manifest(files=[(filename, payload)], sealed=sealed)
    envelope = encode_envelope(payload, manifest)
    return envelope, manifest


def make_manifest_file(
    *,
    path: str = "test.bin",
    data: bytes = TEST_PAYLOAD,
    mtime: int | None = None,
) -> ManifestFile:
    """Create a ManifestFile entry."""
    return ManifestFile(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).digest(),
        mtime=mtime,
    )


# =============================================================================
# File System Helpers
# =============================================================================


@contextmanager
def temp_files(
    **kwargs: bytes | str,
) -> Generator[dict[str, Path], None, None]:
    """Create temporary files with specified content.

    Usage:
        with temp_files(input=b"data", config="[section]") as paths:
            paths["input"]  # Path to file with b"data"
            paths["config"]  # Path to file with "[section]"
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        result: dict[str, Path] = {}
        for name, content in kwargs.items():
            file_path = tmp_path / name
            if isinstance(content, bytes):
                file_path.write_bytes(content)
            else:
                file_path.write_text(content, encoding="utf-8")
            result[name] = file_path
        result["_dir"] = tmp_path
        yield result


@contextmanager
def temp_directory() -> Generator[Path, None, None]:
    """Create a temporary directory with cleanup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# Assertion Helpers
# =============================================================================


def assert_frames_equal(frame1: Frame, frame2: Frame, *, msg: str = "") -> None:
    """Assert two frames are equal with detailed error message."""
    prefix = f"{msg}: " if msg else ""
    assert frame1.version == frame2.version, f"{prefix}version mismatch"
    assert frame1.frame_type == frame2.frame_type, f"{prefix}frame_type mismatch"
    assert frame1.doc_id == frame2.doc_id, f"{prefix}doc_id mismatch"
    assert frame1.index == frame2.index, f"{prefix}index mismatch"
    assert frame1.total == frame2.total, f"{prefix}total mismatch"
    assert frame1.data == frame2.data, f"{prefix}data mismatch"


def assert_manifest_files_equal(
    files1: tuple[ManifestFile, ...],
    files2: tuple[ManifestFile, ...],
    *,
    msg: str = "",
) -> None:
    """Assert manifest file lists are equal."""
    prefix = f"{msg}: " if msg else ""
    assert len(files1) == len(files2), f"{prefix}file count mismatch"
    for i, (f1, f2) in enumerate(zip(files1, files2)):
        assert f1.path == f2.path, f"{prefix}file {i} path mismatch"
        assert f1.size == f2.size, f"{prefix}file {i} size mismatch"
        assert f1.sha256 == f2.sha256, f"{prefix}file {i} sha256 mismatch"


def assert_shards_valid(shards: list[ShardPayload], *, threshold: int) -> None:
    """Assert shards are valid and have correct properties."""
    assert len(shards) >= threshold, "not enough shards"
    first = shards[0]
    indices = set()
    for shard in shards:
        assert shard.threshold == first.threshold, "threshold mismatch"
        assert shard.shares == first.shares, "shares mismatch"
        assert shard.key_type == first.key_type, "key_type mismatch"
        assert shard.doc_hash == first.doc_hash, "doc_hash mismatch"
        assert shard.sign_pub == first.sign_pub, "sign_pub mismatch"
        assert shard.index not in indices, f"duplicate index {shard.index}"
        indices.add(shard.index)


# =============================================================================
# Mock Helpers
# =============================================================================


@contextmanager
def mock_signing_keypair(
    seed: bytes | None = None,
    pub: bytes | None = None,
) -> Generator[tuple[bytes, bytes], None, None]:
    """Mock generate_signing_keypair to return predictable values."""
    keypair = (seed or TEST_SIGNING_SEED, pub or TEST_SIGNING_PUB)
    with mock.patch(
        "ethernity.crypto.signing.generate_signing_keypair",
        return_value=keypair,
    ):
        yield keypair


@contextmanager
def mock_encryption(
    ciphertext: bytes = b"encrypted",
    passphrase: str = TEST_PASSPHRASE,
) -> Generator[tuple[bytes, str], None, None]:
    """Mock encrypt_bytes_with_passphrase."""
    result = (ciphertext, passphrase)
    with mock.patch(
        "ethernity.crypto.encrypt_bytes_with_passphrase",
        return_value=result,
    ):
        yield result


# =============================================================================
# PDF/Render Helpers
# =============================================================================


def is_valid_pdf(data: bytes) -> bool:
    """Check if bytes represent a valid PDF file."""
    return data.startswith(b"%PDF-") and b"%%EOF" in data[-128:]


def pdf_page_count(data: bytes) -> int:
    """Rough estimate of PDF page count (not 100% accurate)."""
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")
