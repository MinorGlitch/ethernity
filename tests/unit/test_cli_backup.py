import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity import cli
from ethernity.config import load_app_config
from ethernity.compression import MAGIC as COMPRESSION_MAGIC
from ethernity.models import DocumentMode, DocumentPlan, KeyMaterial, ShardingConfig


class TestCliBackup(unittest.TestCase):
    def test_run_backup_passphrase_autogen(self) -> None:
        config = load_app_config(paper_size="A4")
        plan = DocumentPlan(
            version=1,
            mode=DocumentMode.PASSPHRASE,
            key_material=KeyMaterial.PASSPHRASE,
            sealed=False,
            sharding=None,
            recipients=(),
        )
        payload = b"payload"
        calls: list[object] = []
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=payload,
            mtime=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.cli.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "auto-pass"),
            ) as encrypt_mock:
                with mock.patch("ethernity.pdf_render.render_frames_to_pdf") as render_mock:
                    render_mock.side_effect = lambda inputs: calls.append(inputs)
                    result = cli.run_backup(
                        input_files=[input_file],
                        base_dir=None,
                        output_dir=str(output_dir),
                        plan=plan,
                        recipients=[],
                        passphrase=None,
                        config=config,
                        title_override=None,
                        subtitle_override=None,
                    )

            encrypt_mock.assert_called_once()
            self.assertEqual(result.passphrase_used, "auto-pass")
            self.assertTrue(Path(result.qr_path).name == "qr_document.pdf")
            self.assertTrue(Path(result.recovery_path).name == "recovery_document.pdf")
            self.assertTrue(output_dir.exists())
            self.assertEqual(len(calls), 2)
            self.assertFalse(calls[0].render_fallback)
            self.assertFalse(calls[1].render_qr)

    def test_run_backup_generate_identity(self) -> None:
        config = load_app_config(paper_size="A4")
        plan = DocumentPlan(
            version=1,
            mode=DocumentMode.RECIPIENT,
            key_material=KeyMaterial.IDENTITY,
            sealed=False,
            sharding=None,
            recipients=(),
        )
        payload = b"payload"
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=payload,
            mtime=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.cli.generate_identity",
                return_value=("AGE-SECRET-KEY-TEST", "age1recipient"),
            ) as generate_mock:
                with mock.patch("ethernity.cli.encrypt_bytes", return_value=b"ciphertext") as encrypt_mock:
                    with mock.patch("ethernity.pdf_render.render_frames_to_pdf") as render_mock:
                        result = cli.run_backup(
                            input_files=[input_file],
                            base_dir=None,
                            output_dir=str(output_dir),
                            plan=plan,
                            recipients=[],
                            passphrase=None,
                            config=config,
                            title_override=None,
                            subtitle_override=None,
                        )

            generate_mock.assert_called_once()
            encrypt_mock.assert_called_once()
            args, kwargs = encrypt_mock.call_args
            self.assertEqual(kwargs["recipients"], ["age1recipient"])
            self.assertTrue(args[0].startswith(COMPRESSION_MAGIC))
            self.assertEqual(result.generated_identity, "AGE-SECRET-KEY-TEST")
            self.assertEqual(result.generated_recipient, "age1recipient")
            self.assertEqual(result.passphrase_used, None)
            self.assertTrue(output_dir.exists())

    def test_run_backup_sharding_passes_signing_keys(self) -> None:
        config = load_app_config(paper_size="A4")
        plan = DocumentPlan(
            version=1,
            mode=DocumentMode.PASSPHRASE,
            key_material=KeyMaterial.PASSPHRASE,
            sealed=False,
            sharding=ShardingConfig(threshold=2, shares=3),
            recipients=(),
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        ciphertext = b"ciphertext"
        sign_priv = b"\x11" * 32
        sign_pub = b"\x22" * 32
        shard_stub = SimpleNamespace(index=1, shares=3)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.cli.encrypt_bytes_with_passphrase",
                return_value=(ciphertext, "auto-pass"),
            ):
                with mock.patch(
                    "ethernity.signing.generate_signing_keypair",
                    return_value=(sign_priv, sign_pub),
                ):
                    with mock.patch(
                        "ethernity.sharding.split_passphrase",
                        return_value=[shard_stub],
                    ) as split_mock:
                        with mock.patch(
                            "ethernity.sharding.encode_shard_payload",
                            return_value=b"shard",
                        ):
                            with mock.patch("ethernity.pdf_render.render_frames_to_pdf"):
                                result = cli.run_backup(
                                    input_files=[input_file],
                                    base_dir=None,
                                    output_dir=str(output_dir),
                                    plan=plan,
                                    recipients=[],
                                    passphrase=None,
                                    config=config,
                                    title_override=None,
                                    subtitle_override=None,
                                )

        expected_doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
        split_mock.assert_called_once()
        args, kwargs = split_mock.call_args
        self.assertEqual(args[0], "auto-pass")
        self.assertEqual(kwargs["threshold"], 2)
        self.assertEqual(kwargs["shares"], 3)
        self.assertEqual(kwargs["doc_hash"], expected_doc_hash)
        self.assertEqual(kwargs["sign_priv"], sign_priv)
        self.assertEqual(kwargs["sign_pub"], sign_pub)
        self.assertEqual(len(result.shard_paths), 1)
        self.assertTrue(result.shard_paths[0].endswith("-1-of-3.pdf"))

    def test_backup_command_requires_recipients_or_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.bin"
            input_path.write_bytes(b"payload")
            args = argparse.Namespace(
                config=None,
                paper="A4",
                input=[str(input_path)],
                input_dir=[],
                base_dir=None,
                output_dir=None,
                mode="recipient",
                passphrase=None,
                passphrase_generate=False,
                recipient=[],
                recipients_file=[],
                generate_identity=False,
                sealed=False,
                shard_threshold=None,
                shard_count=None,
                title=None,
                subtitle=None,
            )
            with self.assertRaises(ValueError):
                cli.run_backup_command(args)


if __name__ == "__main__":
    unittest.main()
