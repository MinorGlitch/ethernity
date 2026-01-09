import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path

from test_support import suppress_output

from ethernity.cli import run_recover_command
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.crypto.sharding import encode_shard_payload, split_passphrase
from ethernity.crypto.signing import generate_signing_keypair
from ethernity.encoding.chunking import chunk_payload, frame_to_fallback_lines
from ethernity.encoding.framing import Frame, FrameType, encode_frame
from ethernity.formats.envelope_codec import build_single_file_manifest, encode_envelope


class TestEndToEndSharding(unittest.TestCase):
    def test_recover_with_shard_frames(self) -> None:
        payload = b"end-to-end shard recovery"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest = build_single_file_manifest("payload.bin", payload)
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            sign_priv, sign_pub = generate_signing_keypair()

            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=12,
            )
            frames_path = tmp_path / "frames.txt"
            frames_path.write_text(
                "\n".join(encode_frame(frame).hex() for frame in frames),
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
                "\n".join(encode_frame(frame).hex() for frame in shard_frames),
                encoding="utf-8",
            )

            output_path = tmp_path / "recovered.bin"
            args = argparse.Namespace(
                fallback_file=None,
                frames_file=str(frames_path),
                frames_encoding="auto",
                scan=[],
                passphrase=None,
                shard_fallback_file=[],
                shard_frames_file=[str(shard_frames_path)],
                shard_frames_encoding="auto",
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
            manifest = build_single_file_manifest("payload.bin", payload)
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            sign_priv, sign_pub = generate_signing_keypair()

            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=10,
            )
            frames_path = tmp_path / "frames.txt"
            frames_path.write_text(
                "\n".join(encode_frame(frame).hex() for frame in frames),
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
                shard_lines = frame_to_fallback_lines(shard_frame, line_length=80, line_count=None)
                shard_path = tmp_path / f"shard_{idx}.txt"
                shard_path.write_text("\n".join(shard_lines), encoding="utf-8")
                shard_paths.append(str(shard_path))

            output_path = tmp_path / "recovered.bin"
            args = argparse.Namespace(
                fallback_file=None,
                frames_file=str(frames_path),
                frames_encoding="auto",
                scan=[],
                passphrase=None,
                shard_fallback_file=shard_paths,
                shard_frames_file=[],
                shard_frames_encoding="auto",
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
