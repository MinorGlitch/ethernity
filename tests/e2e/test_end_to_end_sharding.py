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

from ethernity.cli import run_recover_command
from ethernity.cli.core.types import RecoverArgs
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.sharding import encode_shard_payload, split_passphrase
from ethernity.crypto.signing import generate_signing_keypair
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.formats.envelope_codec import build_single_file_manifest, encode_envelope
from ethernity.render.fallback_text import format_zbase32_lines
from tests.test_support import suppress_output

TEST_SIGNING_SEED = b"\x11" * 32


class TestEndToEndSharding(unittest.TestCase):
    def test_recover_with_shard_frames(self) -> None:
        payload = b"end-to-end shard recovery"
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
                chunk_size=12,
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
                    version=frames[0].version,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=doc_id,
                    index=0,
                    total=1,
                    data=encode_shard_payload(share),
                )
                for share in shares
            ]
            shard_frames_path = tmp_path / "shard_frames.txt"
            shard_frames_path.write_text(
                "\n".join(encode_qr_payload(encode_frame(frame)) for frame in shard_frames),
                encoding="utf-8",
            )

            output_path = tmp_path / "recovered.bin"
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

    def test_recover_with_shard_fallback(self) -> None:
        payload = b"shard fallback recovery"
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
                chunk_size=10,
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
            shard_paths: list[str] = []
            for idx, share in enumerate(shares[:2], start=1):
                shard_frame = Frame(
                    version=frames[0].version,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=doc_id,
                    index=0,
                    total=1,
                    data=encode_shard_payload(share),
                )
                shard_lines = format_zbase32_lines(
                    encode_zbase32(encode_frame(shard_frame)),
                    group_size=4,
                    line_length=80,
                    line_count=None,
                )
                shard_path = tmp_path / f"shard_{idx}.txt"
                shard_path.write_text("\n".join(shard_lines), encoding="utf-8")
                shard_paths.append(str(shard_path))

            output_path = tmp_path / "recovered.bin"
            args = RecoverArgs(
                fallback_file=None,
                payloads_file=str(frames_path),
                scan=[],
                passphrase=None,
                shard_fallback_file=shard_paths,
                shard_payloads_file=[],
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
