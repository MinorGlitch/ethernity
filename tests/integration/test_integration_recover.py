import argparse
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.encoding.chunking import chunk_payload, payload_to_fallback_lines
from ethernity.formats.envelope_codec import (
    build_manifest_and_payload,
    build_single_file_manifest,
    encode_envelope,
)
from ethernity.formats.envelope_types import PayloadPart
from ethernity.encoding.framing import FrameType, encode_frame
from ethernity.cli import run_recover_command
from tests.test_support import prepend_path, suppress_output, write_fake_age_script


class TestIntegrationRecover(unittest.TestCase):
    def test_recover_from_frames_via_cli(self) -> None:
        payload = b"hello integration"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            age_path = write_fake_age_script(tmp_path)
            with mock.patch.dict(
                os.environ, {"ETHERNITY_AGE_PATH": str(age_path)}, clear=False
            ):
                with prepend_path(tmp_path):
                    manifest = build_single_file_manifest("payload.bin", payload)
                    envelope = encode_envelope(payload, manifest)
                    ciphertext, passphrase = encrypt_bytes_with_passphrase(
                        envelope, passphrase=None
                    )
                    doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
                    frames = chunk_payload(
                        ciphertext,
                        doc_id=doc_id,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        chunk_size=8,
                    )
                    frames_path = tmp_path / "frames.txt"
                    frames_path.write_text(
                        "\n".join(encode_frame(frame).hex() for frame in frames),
                        encoding="utf-8",
                    )
                    output_path = tmp_path / "out.bin"

                    args = argparse.Namespace(
                        fallback_file=None,
                        frames_file=str(frames_path),
                        frames_encoding="auto",
                        scan=[],
                        passphrase=passphrase,
                        shard_fallback_file=[],
                        shard_frames_file=[],
                        shard_frames_encoding="auto",
                        output=str(output_path),
                        allow_unsigned=True,
                        assume_yes=True,
                        quiet=True,
                    )
                    with suppress_output():
                        run_recover_command(args)
                    self.assertEqual(output_path.read_bytes(), payload)

    def test_recover_from_fallback_via_cli(self) -> None:
        payload = b"fallback integration"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            age_path = write_fake_age_script(tmp_path)
            with mock.patch.dict(
                os.environ, {"ETHERNITY_AGE_PATH": str(age_path)}, clear=False
            ):
                with prepend_path(tmp_path):
                    manifest = build_single_file_manifest("payload.bin", payload)
                    envelope = encode_envelope(payload, manifest)
                    ciphertext, passphrase = encrypt_bytes_with_passphrase(
                        envelope, passphrase=None
                    )
                    doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
                    lines = payload_to_fallback_lines(
                        ciphertext,
                        doc_id=doc_id,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        line_length=80,
                    )
                    fallback_path = tmp_path / "fallback.txt"
                    fallback_path.write_text("\n".join(lines), encoding="utf-8")
                    output_path = tmp_path / "out.bin"

                    args = argparse.Namespace(
                        fallback_file=str(fallback_path),
                        frames_file=None,
                        frames_encoding="auto",
                        scan=[],
                        passphrase=passphrase,
                        shard_fallback_file=[],
                        shard_frames_file=[],
                        shard_frames_encoding="auto",
                        output=str(output_path),
                        allow_unsigned=True,
                        assume_yes=True,
                        quiet=True,
                    )
                    with suppress_output():
                        run_recover_command(args)
                    self.assertEqual(output_path.read_bytes(), payload)

    def test_recover_from_scan_image(self) -> None:
        try:
            import zxingcpp  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("optional QR scan dependencies not installed")

        try:
            import segno
        except ImportError:
            self.skipTest("segno not installed")

        payload = b"scan integration"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            age_path = write_fake_age_script(tmp_path)
            with mock.patch.dict(
                os.environ, {"ETHERNITY_AGE_PATH": str(age_path)}, clear=False
            ):
                with prepend_path(tmp_path):
                    manifest = build_single_file_manifest("payload.bin", payload)
                    envelope = encode_envelope(payload, manifest)
                    ciphertext, passphrase = encrypt_bytes_with_passphrase(
                        envelope, passphrase=None
                    )
                    doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
                    frames = chunk_payload(
                        ciphertext,
                        doc_id=doc_id,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        chunk_size=len(ciphertext),
                    )
                    frame_payloads = [encode_frame(frame) for frame in frames]
                    qr_path = tmp_path / "qr.png"
                    qr = segno.make(frame_payloads[0], error="Q")
                    qr.save(qr_path, kind="png", scale=4, border=2)
                    output_path = tmp_path / "out.bin"

                    args = argparse.Namespace(
                        fallback_file=None,
                        frames_file=None,
                        frames_encoding="auto",
                        scan=[str(qr_path)],
                        passphrase=passphrase,
                        shard_fallback_file=[],
                        shard_frames_file=[],
                        shard_frames_encoding="auto",
                        output=str(output_path),
                        allow_unsigned=True,
                        assume_yes=True,
                        quiet=True,
                    )
                    with suppress_output():
                        run_recover_command(args)
                    self.assertEqual(output_path.read_bytes(), payload)

    def test_recover_multi_file_output_dir(self) -> None:
        parts = [
            PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),
            PayloadPart(path="beta/beta.txt", data=b"beta", mtime=2),
        ]
        manifest, payload = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            age_path = write_fake_age_script(tmp_path)
            with mock.patch.dict(
                os.environ, {"ETHERNITY_AGE_PATH": str(age_path)}, clear=False
            ):
                with prepend_path(tmp_path):
                    envelope = encode_envelope(payload, manifest)
                    ciphertext, passphrase = encrypt_bytes_with_passphrase(
                        envelope, passphrase=None
                    )
                    doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
                    lines = payload_to_fallback_lines(
                        ciphertext,
                        doc_id=doc_id,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        line_length=80,
                    )
                    fallback_path = tmp_path / "fallback.txt"
                    fallback_path.write_text("\n".join(lines), encoding="utf-8")
                    output_dir = tmp_path / "out"

                    args = argparse.Namespace(
                        fallback_file=str(fallback_path),
                        frames_file=None,
                        frames_encoding="auto",
                        scan=[],
                        passphrase=passphrase,
                        shard_fallback_file=[],
                        shard_frames_file=[],
                        shard_frames_encoding="auto",
                        output=str(output_dir),
                        allow_unsigned=True,
                        assume_yes=True,
                        quiet=True,
                    )
                    with suppress_output():
                        run_recover_command(args)

                    self.assertEqual((output_dir / "alpha.txt").read_bytes(), b"alpha")
                    self.assertEqual((output_dir / "beta" / "beta.txt").read_bytes(), b"beta")


if __name__ == "__main__":
    unittest.main()
