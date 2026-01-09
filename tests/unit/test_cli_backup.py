import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity import cli
from ethernity.config import load_app_config
from ethernity.core.models import DocumentPlan, ShardingConfig, SigningSeedMode
from ethernity.formats import envelope_codec as envelope_codec_module

REPO_ROOT = Path(__file__).resolve().parents[2]
A4_CONFIG_PATH = REPO_ROOT / "src" / "ethernity" / "config" / "a4.toml"


class _CaptureBuild:
    def __init__(self, captured: dict[str, object], real_build):
        self._captured = captured
        self._real_build = real_build

    def __call__(self, *args, **kwargs):
        self._captured["signing_seed"] = kwargs.get("signing_seed")
        return self._real_build(*args, **kwargs)


def _run_backup_with_plan(
    *,
    plan: DocumentPlan,
    input_file: cli.InputFile,
    config,
    sign_priv: bytes,
    sign_pub: bytes,
    real_build,
) -> bytes | None:
    captured: dict[str, object] = {}
    capture_build = _CaptureBuild(captured, real_build)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "out"
        with mock.patch(
            "ethernity.crypto.signing.generate_signing_keypair",
            return_value=(sign_priv, sign_pub),
        ):
            with mock.patch(
                "ethernity.formats.envelope_codec.build_manifest_and_payload",
                side_effect=capture_build,
            ):
                with mock.patch("ethernity.render.render_frames_to_pdf"):
                    with mock.patch(
                        "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                        return_value=(b"ciphertext", "auto-pass"),
                    ):
                        with mock.patch(
                            "ethernity.crypto.sharding.split_passphrase",
                            return_value=[],
                        ):
                            cli.run_backup(
                                input_files=[input_file],
                                base_dir=None,
                                output_dir=str(output_dir),
                                plan=plan,
                                passphrase=None,
                                config=config,
                            )

    return captured.get("signing_seed")


class TestCliBackup(unittest.TestCase):
    def test_run_backup_passphrase_autogen(self) -> None:
        config = load_app_config(path=A4_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=None,
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
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "auto-pass"),
            ) as encrypt_mock:
                with mock.patch("ethernity.render.render_frames_to_pdf") as render_mock:
                    render_mock.side_effect = lambda inputs: calls.append(inputs)
                    result = cli.run_backup(
                        input_files=[input_file],
                        base_dir=None,
                        output_dir=str(output_dir),
                        plan=plan,
                        passphrase=None,
                        config=config,
                    )

            encrypt_mock.assert_called_once()
            self.assertEqual(result.passphrase_used, "auto-pass")
            self.assertTrue(Path(result.qr_path).name == "qr_document.pdf")
            self.assertTrue(Path(result.recovery_path).name == "recovery_document.pdf")
            self.assertTrue(output_dir.exists())
            self.assertEqual(len(calls), 2)
            self.assertFalse(calls[0].render_fallback)
            self.assertFalse(calls[1].render_qr)

    def test_run_backup_sharding_passes_signing_keys(self) -> None:
        config = load_app_config(path=A4_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=ShardingConfig(threshold=2, shares=3),
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
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(ciphertext, "auto-pass"),
            ):
                with mock.patch(
                    "ethernity.crypto.signing.generate_signing_keypair",
                    return_value=(sign_priv, sign_pub),
                ):
                    with mock.patch(
                        "ethernity.crypto.sharding.split_passphrase",
                        return_value=[shard_stub],
                    ) as split_mock:
                        with mock.patch(
                            "ethernity.crypto.sharding.encode_shard_payload",
                            return_value=b"shard",
                        ):
                            with mock.patch("ethernity.render.render_frames_to_pdf"):
                                result = cli.run_backup(
                                    input_files=[input_file],
                                    base_dir=None,
                                    output_dir=str(output_dir),
                                    plan=plan,
                                    passphrase=None,
                                    config=config,
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

    def test_run_backup_stores_signing_seed_when_unsealed_sharded_passphrase(self) -> None:
        config = load_app_config(path=A4_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=ShardingConfig(threshold=2, shares=3),
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        sign_priv = b"\x11" * 32
        sign_pub = b"\x22" * 32
        captured: dict[str, object] = {}
        real_build = envelope_codec_module.build_manifest_and_payload
        capture_build = _CaptureBuild(captured, real_build)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.crypto.signing.generate_signing_keypair",
                return_value=(sign_priv, sign_pub),
            ):
                with mock.patch(
                    "ethernity.formats.envelope_codec.build_manifest_and_payload",
                    side_effect=capture_build,
                ):
                    with mock.patch(
                        "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                        return_value=(b"ciphertext", "auto-pass"),
                    ):
                        with mock.patch(
                            "ethernity.crypto.sharding.split_passphrase",
                            return_value=[],
                        ):
                            with mock.patch("ethernity.render.render_frames_to_pdf"):
                                cli.run_backup(
                                    input_files=[input_file],
                                    base_dir=None,
                                    output_dir=str(output_dir),
                                    plan=plan,
                                    passphrase=None,
                                    config=config,
                                )

        self.assertEqual(captured.get("signing_seed"), sign_priv)

    def test_run_backup_omits_signing_seed_for_sealed(self) -> None:
        config = load_app_config(path=A4_CONFIG_PATH)
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        sign_priv = b"\x11" * 32
        sign_pub = b"\x22" * 32
        real_build = envelope_codec_module.build_manifest_and_payload

        sealed_plan = DocumentPlan(
            version=1,
            sealed=True,
            sharding=ShardingConfig(threshold=2, shares=3),
        )
        signing_seed = _run_backup_with_plan(
            plan=sealed_plan,
            input_file=input_file,
            config=config,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
            real_build=real_build,
        )
        self.assertIsNone(signing_seed)

    def test_run_backup_shards_signing_seed_when_mode_sharded(self) -> None:
        config = load_app_config(path=A4_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            signing_seed_mode=SigningSeedMode.SHARDED,
            sharding=ShardingConfig(threshold=2, shares=3),
            signing_seed_sharding=ShardingConfig(threshold=1, shares=2),
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        sign_priv = b"\x11" * 32
        sign_pub = b"\x22" * 32
        passphrase_shard = SimpleNamespace(index=1, shares=3)
        signing_shard = SimpleNamespace(index=2, shares=2)
        captured: dict[str, object] = {}
        real_build = envelope_codec_module.build_manifest_and_payload
        capture_build = _CaptureBuild(captured, real_build)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.crypto.signing.generate_signing_keypair",
                return_value=(sign_priv, sign_pub),
            ):
                with mock.patch(
                    "ethernity.formats.envelope_codec.build_manifest_and_payload",
                    side_effect=capture_build,
                ):
                    with mock.patch(
                        "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                        return_value=(b"ciphertext", "auto-pass"),
                    ):
                        with mock.patch(
                            "ethernity.crypto.sharding.split_passphrase",
                            return_value=[passphrase_shard],
                        ):
                            with mock.patch(
                                "ethernity.crypto.sharding.split_signing_seed",
                                return_value=[signing_shard],
                            ) as split_signing_mock:
                                with mock.patch(
                                    "ethernity.crypto.sharding.encode_shard_payload",
                                    return_value=b"shard",
                                ):
                                    with mock.patch("ethernity.render.render_frames_to_pdf"):
                                        result = cli.run_backup(
                                            input_files=[input_file],
                                            base_dir=None,
                                            output_dir=str(output_dir),
                                            plan=plan,
                                            passphrase=None,
                                            config=config,
                                        )

        self.assertIsNone(captured.get("signing_seed"))
        self.assertEqual(len(result.signing_key_shard_paths), 1)
        self.assertIn("signing-key-shard-", result.signing_key_shard_paths[0])
        _, kwargs = split_signing_mock.call_args
        self.assertEqual(kwargs["threshold"], 1)
        self.assertEqual(kwargs["shares"], 2)


if __name__ == "__main__":
    unittest.main()
