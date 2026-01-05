import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.encoding.chunking import chunk_payload
from ethernity.formats.envelope_codec import build_single_file_manifest, encode_envelope
from ethernity.encoding.framing import FrameType, encode_frame
from test_support import prepend_path, write_fake_age_script


class TestEndToEndCli(unittest.TestCase):
    def test_backup_cli_creates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            write_fake_age_script(tmp_path)
            input_path = tmp_path / "input.txt"
            input_path.write_text("backup cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            repo_root = Path(__file__).resolve().parents[2]

            with prepend_path(tmp_path):
                env = os.environ.copy()
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ethernity.cli",
                        "--paper",
                        "A4",
                        "backup",
                        "--input",
                        str(input_path),
                        "--output-dir",
                        str(output_dir),
                        "--passphrase-generate",
                    ],
                    cwd=repo_root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "qr_document.pdf").exists())
            self.assertTrue((output_dir / "recovery_document.pdf").exists())

    def test_recover_cli_from_frames(self) -> None:
        payload = b"recover cli payload"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            write_fake_age_script(tmp_path)
            repo_root = Path(__file__).resolve().parents[2]

            with prepend_path(tmp_path):
                manifest = build_single_file_manifest("payload.bin", payload)
                envelope = encode_envelope(payload, manifest)
                ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
                self.assertIsNotNone(passphrase)
                doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
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
                output_path = tmp_path / "recovered.bin"

                env = os.environ.copy()
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ethernity.cli",
                        "recover",
                        "--frames-file",
                        str(frames_path),
                        "--passphrase",
                        passphrase,
                        "--allow-unsigned",
                        "--output",
                        str(output_path),
                    ],
                    cwd=repo_root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_path.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
