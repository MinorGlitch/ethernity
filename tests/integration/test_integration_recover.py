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

import hashlib
import tempfile
import unittest
from pathlib import Path

import segno
import zxingcpp  # noqa: F401
from PIL import Image  # noqa: F401

from ethernity.cli import run_recover_command
from ethernity.cli.core.types import RecoverArgs
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.sharding import encode_shard_payload, split_passphrase
from ethernity.crypto.signing import generate_signing_keypair
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.formats.envelope_codec import (
    build_manifest_and_payload,
    build_single_file_manifest,
    encode_envelope,
)
from ethernity.formats.envelope_types import PayloadPart
from ethernity.render.fallback_text import format_zbase32_lines
from tests.test_support import suppress_output

TEST_SIGNING_SEED = b"\x11" * 32


class TestIntegrationRecover(unittest.TestCase):
    def test_recover_from_frames_via_cli(self) -> None:
        payload = b"hello integration"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=8,
            )
            frames_path = tmp_path / "frames.txt"
            frames_path.write_text(
                "\n".join(encode_qr_payload(encode_frame(frame)) for frame in frames),
                encoding="utf-8",
            )
            output_path = tmp_path / "out.bin"

            args = RecoverArgs(
                fallback_file=None,
                payloads_file=str(frames_path),
                scan=[],
                passphrase=passphrase,
                shard_fallback_file=[],
                shard_payloads_file=[],
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
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frame = Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=1,
                data=ciphertext,
            )
            lines = format_zbase32_lines(
                encode_zbase32(encode_frame(frame)),
                group_size=4,
                line_length=80,
                line_count=None,
            )
            fallback_path = tmp_path / "fallback.txt"
            fallback_path.write_text("\n".join(lines), encoding="utf-8")
            output_path = tmp_path / "out.bin"

            args = RecoverArgs(
                fallback_file=str(fallback_path),
                payloads_file=None,
                scan=[],
                passphrase=passphrase,
                shard_fallback_file=[],
                shard_payloads_file=[],
                output=str(output_path),
                allow_unsigned=True,
                assume_yes=True,
                quiet=True,
            )
            with suppress_output():
                run_recover_command(args)
            self.assertEqual(output_path.read_bytes(), payload)

    def test_recover_from_scan_image(self) -> None:
        payload = b"scan integration"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=len(ciphertext),
            )
            frame_payloads = [encode_qr_payload(encode_frame(frame)) for frame in frames]
            qr_path = tmp_path / "qr.png"
            qr = segno.make(frame_payloads[0], error="Q")
            qr.save(qr_path, kind="png", scale=4, border=2)
            output_path = tmp_path / "out.bin"

            args = RecoverArgs(
                fallback_file=None,
                payloads_file=None,
                scan=[str(qr_path)],
                passphrase=passphrase,
                shard_fallback_file=[],
                shard_payloads_file=[],
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
        manifest, payload = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frame = Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=1,
                data=ciphertext,
            )
            lines = format_zbase32_lines(
                encode_zbase32(encode_frame(frame)),
                group_size=4,
                line_length=80,
                line_count=None,
            )
            fallback_path = tmp_path / "fallback.txt"
            fallback_path.write_text("\n".join(lines), encoding="utf-8")
            output_dir = tmp_path / "out"

            args = RecoverArgs(
                fallback_file=str(fallback_path),
                payloads_file=None,
                scan=[],
                passphrase=passphrase,
                shard_fallback_file=[],
                shard_payloads_file=[],
                output=str(output_dir),
                allow_unsigned=True,
                assume_yes=True,
                quiet=True,
            )
            with suppress_output():
                run_recover_command(args)

            self.assertEqual((output_dir / "alpha.txt").read_bytes(), b"alpha")
            self.assertEqual((output_dir / "beta" / "beta.txt").read_bytes(), b"beta")

    def test_recover_with_multiple_key_document_frames_same_doc_id(self) -> None:
        payload = b"integration shard payloads"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            sign_priv, sign_pub = generate_signing_keypair()

            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=8,
            )
            frames_path = tmp_path / "frames.txt"
            frames_path.write_text(
                "\n".join(encode_qr_payload(encode_frame(frame)) for frame in frames),
                encoding="utf-8",
            )

            shares = split_passphrase(
                passphrase,
                threshold=2,
                shares=3,
                doc_hash=doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )
            shard_frames = [
                Frame(
                    version=VERSION,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=doc_id,
                    index=0,
                    total=1,
                    data=encode_shard_payload(shares[0]),
                ),
                Frame(
                    version=VERSION,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=doc_id,
                    index=0,
                    total=1,
                    data=encode_shard_payload(shares[1]),
                ),
            ]
            shard_frames_path = tmp_path / "shard_frames.txt"
            shard_frames_path.write_text(
                "\n".join(encode_qr_payload(encode_frame(frame)) for frame in shard_frames),
                encoding="utf-8",
            )
            output_path = tmp_path / "out.bin"

            args = RecoverArgs(
                fallback_file=None,
                payloads_file=str(frames_path),
                scan=[],
                passphrase=None,
                shard_fallback_file=[],
                shard_payloads_file=[str(shard_frames_path)],
                output=str(output_path),
                allow_unsigned=False,
                assume_yes=True,
                quiet=True,
            )
            with suppress_output():
                run_recover_command(args)
            self.assertEqual(output_path.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
