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

import contextlib
import hashlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from typer.testing import CliRunner

from ethernity import cli
from ethernity.cli.core.types import BackupArgs
from ethernity.cli.io.inputs import _load_input_files
from ethernity.config import (
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    RecoverDefaults,
    RuntimeDefaults,
    UiDefaults,
    load_app_config,
)
from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.core.models import DocumentPlan, ShardingConfig, SigningSeedMode
from ethernity.encoding.framing import Frame
from ethernity.formats import envelope_codec as envelope_codec_module

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "ethernity" / "config" / "config.toml"


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
    def test_run_backup_enforces_ciphertext_bound(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(version=1, sealed=False, sharding=None)
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )

        def _fake_chunk(
            payload: bytes,
            *,
            doc_id: bytes,
            frame_type: int,
            chunk_size: int,
            version: int = 1,
        ) -> list[Frame]:
            _ = payload, chunk_size
            return [
                Frame(
                    version=version,
                    frame_type=frame_type,
                    doc_id=doc_id,
                    index=0,
                    total=1,
                    data=b"x",
                )
            ]

        cases = (
            (MAX_CIPHERTEXT_BYTES - 1, False),
            (MAX_CIPHERTEXT_BYTES, False),
            (MAX_CIPHERTEXT_BYTES + 1, True),
        )
        for size, expect_error in cases:
            with self.subTest(ciphertext_size=size):
                with tempfile.TemporaryDirectory() as tmpdir:
                    output_dir = Path(tmpdir) / "out"
                    ciphertext = b"c" * size
                    with mock.patch(
                        "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                        return_value=(ciphertext, "auto-pass"),
                    ):
                        with mock.patch(
                            "ethernity.cli.flows.backup_flow.chunk_payload",
                            side_effect=_fake_chunk,
                        ) as chunk_mock:
                            with mock.patch(
                                "ethernity.cli.flows.backup_flow.choose_frame_chunk_size",
                                return_value=256,
                            ):
                                with mock.patch("ethernity.render.render_frames_to_pdf"):
                                    if expect_error:
                                        with self.assertRaisesRegex(
                                            ValueError, "MAX_CIPHERTEXT_BYTES"
                                        ):
                                            cli.run_backup(
                                                input_files=[input_file],
                                                base_dir=None,
                                                output_dir=str(output_dir),
                                                plan=plan,
                                                passphrase=None,
                                                config=config,
                                            )
                                        chunk_mock.assert_not_called()
                                    else:
                                        result = cli.run_backup(
                                            input_files=[input_file],
                                            base_dir=None,
                                            output_dir=str(output_dir),
                                            plan=plan,
                                            passphrase=None,
                                            config=config,
                                        )
                                        self.assertEqual(
                                            Path(result.qr_path).name,
                                            "qr_document.pdf",
                                        )
                                        chunk_mock.assert_called_once()

    def test_run_backup_warns_when_chunk_size_reduced(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        config = replace(config, qr_chunk_size=1024)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=None,
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "auto-pass"),
            ):
                with mock.patch(
                    "ethernity.cli.flows.backup_flow.choose_frame_chunk_size",
                    return_value=512,
                ):
                    with mock.patch("ethernity.cli.flows.backup_flow._warn") as warn_mock:
                        with mock.patch("ethernity.render.render_frames_to_pdf"):
                            cli.run_backup(
                                input_files=[input_file],
                                base_dir=None,
                                output_dir=str(output_dir),
                                plan=plan,
                                passphrase=None,
                                config=config,
                                quiet=False,
                            )

        warn_mock.assert_called_once()
        message = warn_mock.call_args.args[0]
        self.assertIn("1024", message)
        self.assertIn("512", message)

    def test_run_backup_does_not_warn_when_chunk_size_unchanged(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        config = replace(config, qr_chunk_size=1024)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=None,
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            with mock.patch(
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "auto-pass"),
            ):
                with mock.patch(
                    "ethernity.cli.flows.backup_flow.choose_frame_chunk_size",
                    return_value=1024,
                ):
                    with mock.patch("ethernity.cli.flows.backup_flow._warn") as warn_mock:
                        with mock.patch("ethernity.render.render_frames_to_pdf"):
                            cli.run_backup(
                                input_files=[input_file],
                                base_dir=None,
                                output_dir=str(output_dir),
                                plan=plan,
                                passphrase=None,
                                config=config,
                                quiet=False,
                            )

        warn_mock.assert_not_called()

    def test_run_backup_passphrase_autogen(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
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
            self.assertIsNone(result.kit_index_path)

    def test_run_backup_renders_kit_index_when_template_exists(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=None,
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        calls: list[object] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            templates_dir = Path(tmpdir) / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)
            kit_template = templates_dir / "kit_document.html.j2"
            kit_template.write_text("{{ doc.title }}", encoding="utf-8")
            kit_index_template = templates_dir / "kit_index_document.html.j2"
            kit_index_template.write_text("{{ doc.title }}", encoding="utf-8")
            config = replace(config, kit_template_path=kit_template)

            with mock.patch(
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "auto-pass"),
            ):
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

        self.assertIsNotNone(result.kit_index_path)
        self.assertEqual(Path(result.kit_index_path or "").name, "recovery_kit_index.pdf")
        self.assertEqual(len(calls), 3)
        self.assertEqual(Path(calls[2].template_path).name, "kit_index_document.html.j2")
        self.assertEqual(calls[2].doc_type, "kit")
        self.assertFalse(calls[2].render_fallback)
        inventory_rows = calls[2].context["inventory_rows"]
        self.assertEqual(
            [row["component_id"] for row in inventory_rows],
            ["QR-DOC-01", "RECOVERY-DOC-01"],
        )

    def test_run_backup_uses_packaged_kit_index_when_override_missing(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=None,
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        calls: list[object] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            user_templates_dir = Path(tmpdir) / "user-templates" / "forge"
            user_templates_dir.mkdir(parents=True, exist_ok=True)
            kit_template = user_templates_dir / "kit_document.html.j2"
            kit_template.write_text("{{ doc.title }}", encoding="utf-8")
            config = replace(config, kit_template_path=kit_template)

            package_root = Path(tmpdir) / "package"
            package_design_dir = package_root / "templates" / "forge"
            package_design_dir.mkdir(parents=True, exist_ok=True)
            packaged_kit_index = package_design_dir / "kit_index_document.html.j2"
            packaged_kit_index.write_text("{{ doc.title }}", encoding="utf-8")

            with mock.patch("ethernity.cli.flows.backup_flow.PACKAGE_ROOT", package_root):
                with mock.patch(
                    "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                    return_value=(b"ciphertext", "auto-pass"),
                ):
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

        self.assertIsNotNone(result.kit_index_path)
        self.assertEqual(len(calls), 3)
        self.assertEqual(Path(calls[2].template_path), packaged_kit_index)
        inventory_rows = calls[2].context["inventory_rows"]
        self.assertEqual(
            [row["component_id"] for row in inventory_rows],
            ["QR-DOC-01", "RECOVERY-DOC-01"],
        )

    def test_run_backup_uses_packaged_kit_index_when_override_incompatible(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            sharding=None,
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        calls: list[object] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            user_templates_dir = Path(tmpdir) / "user-templates" / "forge"
            user_templates_dir.mkdir(parents=True, exist_ok=True)
            kit_template = user_templates_dir / "kit_document.html.j2"
            kit_template.write_text("{{ doc.title }}", encoding="utf-8")
            stale_kit_index = user_templates_dir / "kit_index_document.html.j2"
            stale_kit_index.write_text("stale template without marker", encoding="utf-8")
            config = replace(config, kit_template_path=kit_template)

            package_root = Path(tmpdir) / "package"
            package_design_dir = package_root / "templates" / "forge"
            package_design_dir.mkdir(parents=True, exist_ok=True)
            packaged_kit_index = package_design_dir / "kit_index_document.html.j2"
            packaged_kit_index.write_text(
                "kit_index_inventory_artifacts_v3 {{ doc.title }}",
                encoding="utf-8",
            )

            with mock.patch("ethernity.cli.flows.backup_flow.PACKAGE_ROOT", package_root):
                with mock.patch(
                    "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                    return_value=(b"ciphertext", "auto-pass"),
                ):
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

        self.assertIsNotNone(result.kit_index_path)
        self.assertEqual(len(calls), 3)
        self.assertEqual(Path(calls[2].template_path), packaged_kit_index)

    def test_run_backup_kit_index_inventory_includes_shards(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=False,
            signing_seed_mode=SigningSeedMode.SHARDED,
            sharding=ShardingConfig(threshold=2, shares=2),
            signing_seed_sharding=ShardingConfig(threshold=1, shares=1),
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        calls: list[object] = []
        shard_one = SimpleNamespace(share_index=1, share_count=2, threshold=2)
        shard_two = SimpleNamespace(share_index=2, share_count=2, threshold=2)
        signing_shard = SimpleNamespace(share_index=1, share_count=1, threshold=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            templates_dir = Path(tmpdir) / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)
            kit_template = templates_dir / "kit_document.html.j2"
            kit_template.write_text("{{ doc.title }}", encoding="utf-8")
            kit_index_template = templates_dir / "kit_index_document.html.j2"
            kit_index_template.write_text("{{ doc.title }}", encoding="utf-8")
            config = replace(config, kit_template_path=kit_template)

            with mock.patch(
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "auto-pass"),
            ):
                with mock.patch(
                    "ethernity.crypto.sharding.split_passphrase",
                    return_value=[shard_one, shard_two],
                ):
                    with mock.patch(
                        "ethernity.crypto.sharding.split_signing_seed",
                        return_value=[signing_shard],
                    ):
                        with mock.patch(
                            "ethernity.crypto.sharding.encode_shard_payload",
                            return_value=b"shard",
                        ):
                            with mock.patch("ethernity.render.render_frames_to_pdf") as render_mock:
                                render_mock.side_effect = lambda inputs: calls.append(inputs)
                                cli.run_backup(
                                    input_files=[input_file],
                                    base_dir=None,
                                    output_dir=str(output_dir),
                                    plan=plan,
                                    passphrase=None,
                                    config=config,
                                )

        index_inputs = next(
            item for item in calls if Path(item.template_path).name == "kit_index_document.html.j2"
        )
        inventory_rows = index_inputs.context["inventory_rows"]
        self.assertEqual(
            [row["component_id"] for row in inventory_rows],
            [
                "QR-DOC-01",
                "RECOVERY-DOC-01",
                "SHARD-01",
                "SHARD-02",
                "SIGNING-SHARD-01",
            ],
        )

    def test_run_backup_sharding_passes_signing_keys(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
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
        shard_stub = SimpleNamespace(share_index=1, share_count=3, threshold=2)

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
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
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
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
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
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
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
        passphrase_shard = SimpleNamespace(share_index=1, share_count=3, threshold=2)
        signing_shard = SimpleNamespace(share_index=2, share_count=2, threshold=1)
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

        self.assertEqual(captured.get("signing_seed"), sign_priv)
        self.assertEqual(len(result.signing_key_shard_paths), 1)
        self.assertIn("signing-key-shard-", result.signing_key_shard_paths[0])
        _, kwargs = split_signing_mock.call_args
        self.assertEqual(kwargs["threshold"], 1)
        self.assertEqual(kwargs["shares"], 2)

    def test_run_backup_command_warns_for_sealed_sharded_and_passes_through(self) -> None:
        args = BackupArgs(
            input=["input.bin"],
            quiet=False,
            debug=False,
            passphrase="manual-pass",
            passphrase_words=15,
            output_dir="out",
            base_dir="/base",
        )
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(
            version=1,
            sealed=True,
            signing_seed_mode=SigningSeedMode.SHARDED,
            sharding=ShardingConfig(threshold=2, shares=3),
        )
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        result = cli.BackupResult(
            doc_id=b"\x11" * 16,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used="manual-pass",
        )

        with (
            mock.patch("ethernity.cli.flows.backup.load_app_config", return_value=config),
            mock.patch("ethernity.cli.flows.backup.apply_template_design", return_value=config),
            mock.patch("ethernity.cli.flows.backup._validate_backup_args") as validate_args,
            mock.patch("ethernity.cli.flows.backup.plan_from_args", return_value=plan),
            mock.patch("ethernity.cli.flows.backup._warn") as warn_mock,
            mock.patch(
                "ethernity.cli.flows.backup.progress",
                return_value=contextlib.nullcontext(None),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._load_input_files",
                return_value=([input_file], Path("/resolved"), "file", []),
            ),
            mock.patch(
                "ethernity.cli.flows.backup.run_backup", return_value=result
            ) as run_backup_mock,
            mock.patch("ethernity.cli.flows.backup.print_backup_summary") as summary_mock,
            mock.patch("ethernity.cli.flows.backup._print_completion_actions") as completion_mock,
        ):
            exit_code = cli.run_backup_command(args)

        self.assertEqual(exit_code, 0)
        validate_args.assert_called_once_with(args)
        warn_mock.assert_called_once()
        run_backup_mock.assert_called_once_with(
            input_files=[input_file],
            base_dir=Path("/resolved"),
            output_dir="out",
            input_origin="file",
            input_roots=[],
            plan=plan,
            passphrase="manual-pass",
            passphrase_words=15,
            config=config,
            debug=False,
            debug_max_bytes=0,
            debug_reveal_secrets=False,
            quiet=False,
        )
        summary_mock.assert_called_once_with(result, plan, "manual-pass", quiet=False)
        completion_mock.assert_called_once_with(result, False)

    def test_run_backup_command_no_warning_when_not_sealed_sharded(self) -> None:
        args = BackupArgs(input=["input.bin"])
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        plan = DocumentPlan(version=1, sealed=False, signing_seed_mode=SigningSeedMode.EMBEDDED)
        input_file = cli.InputFile(
            source_path=Path("input.bin"),
            relative_path="input.bin",
            data=b"payload",
            mtime=None,
        )
        result = cli.BackupResult(
            doc_id=b"\x11" * 16,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used=None,
        )
        with (
            mock.patch("ethernity.cli.flows.backup.load_app_config", return_value=config),
            mock.patch("ethernity.cli.flows.backup.apply_template_design", return_value=config),
            mock.patch("ethernity.cli.flows.backup._validate_backup_args"),
            mock.patch("ethernity.cli.flows.backup.plan_from_args", return_value=plan),
            mock.patch("ethernity.cli.flows.backup._warn") as warn_mock,
            mock.patch(
                "ethernity.cli.flows.backup.progress",
                return_value=contextlib.nullcontext(None),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._load_input_files",
                return_value=([input_file], None, "file", []),
            ),
            mock.patch("ethernity.cli.flows.backup.ui_screen_mode") as screen_mode,
            mock.patch("ethernity.cli.flows.backup.run_backup", return_value=result),
            mock.patch("ethernity.cli.flows.backup.print_backup_summary"),
            mock.patch("ethernity.cli.flows.backup._print_completion_actions"),
        ):
            exit_code = cli.run_backup_command(args)
        self.assertEqual(exit_code, 0)
        warn_mock.assert_not_called()
        screen_mode.assert_not_called()


class TestCliBackupUx(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self._load_defaults_patcher = mock.patch(
            "ethernity.cli.app.load_cli_defaults",
            return_value=CliDefaults(),
        )
        self._load_defaults_patcher.start()
        self.addCleanup(self._load_defaults_patcher.stop)

    def test_load_input_files_rejects_empty_stdin(self) -> None:
        with mock.patch("ethernity.cli.io.inputs.sys.stdin", new=io.StringIO("")):
            with self.assertRaises(ValueError) as ctx:
                _load_input_files(["-"], [], None, allow_stdin=True)
        self.assertIn("stdin input is empty", str(ctx.exception))

    def test_load_input_files_accepts_non_empty_stdin(self) -> None:
        with mock.patch("ethernity.cli.io.inputs.sys.stdin", new=io.StringIO("payload")):
            entries, base, input_origin, input_roots = _load_input_files(
                ["-"], [], None, allow_stdin=True
            )
        self.assertIsNone(base)
        self.assertEqual(input_origin, "file")
        self.assertEqual(input_roots, [])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].relative_path, "data.txt")
        self.assertEqual(entries[0].data, b"payload")

    def test_backup_empty_stdin_requires_explicit_input_flag(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(cli.app, ["backup"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--input -", result.output)

    def test_backup_explicit_stdin_flag_reaches_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: BackupArgs) -> int:
            captured["input"] = list(args.input or [])
            return 0

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.commands.backup.run_backup_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    ["backup", "--input", "-"],
                    input="payload",
                )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured.get("input"), ["-"])

    def test_backup_qr_chunk_size_flag_reaches_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: BackupArgs) -> int:
            captured["qr_chunk_size"] = args.qr_chunk_size
            return 0

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.commands.backup.run_backup_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    ["backup", "--input", "-", "--qr-chunk-size", "640"],
                    input="payload",
                )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured.get("qr_chunk_size"), 640)

    def test_backup_inherits_operator_defaults_when_cli_values_unset(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: BackupArgs) -> int:
            captured["base_dir"] = args.base_dir
            captured["output_dir"] = args.output_dir
            captured["shard_threshold"] = args.shard_threshold
            captured["shard_count"] = args.shard_count
            captured["signing_key_mode"] = args.signing_key_mode
            captured["signing_key_shard_threshold"] = args.signing_key_shard_threshold
            captured["signing_key_shard_count"] = args.signing_key_shard_count
            return 0

        defaults = CliDefaults(
            backup=BackupDefaults(
                base_dir="./vault",
                output_dir="./out",
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            recover=RecoverDefaults(),
            ui=UiDefaults(),
            debug=DebugDefaults(),
            runtime=RuntimeDefaults(),
        )

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch("ethernity.cli.app.load_cli_defaults", return_value=defaults):
                with mock.patch(
                    "ethernity.cli.commands.backup.run_backup_command",
                    side_effect=_capture_args,
                ):
                    result = self.runner.invoke(
                        cli.app,
                        ["backup", "--input", "-"],
                        input="payload",
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured.get("base_dir"), "./vault")
        self.assertEqual(captured.get("output_dir"), "./out")
        self.assertEqual(captured.get("shard_threshold"), 2)
        self.assertEqual(captured.get("shard_count"), 3)
        self.assertEqual(captured.get("signing_key_mode"), "sharded")
        self.assertEqual(captured.get("signing_key_shard_threshold"), 2)
        self.assertEqual(captured.get("signing_key_shard_count"), 3)

    def test_backup_cli_values_override_operator_defaults(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: BackupArgs) -> int:
            captured["output_dir"] = args.output_dir
            captured["shard_threshold"] = args.shard_threshold
            return 0

        defaults = CliDefaults(
            backup=BackupDefaults(output_dir="./default-out", shard_threshold=2),
            recover=RecoverDefaults(),
            ui=UiDefaults(),
            debug=DebugDefaults(),
            runtime=RuntimeDefaults(),
        )

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch("ethernity.cli.app.load_cli_defaults", return_value=defaults):
                with mock.patch(
                    "ethernity.cli.commands.backup.run_backup_command",
                    side_effect=_capture_args,
                ):
                    result = self.runner.invoke(
                        cli.app,
                        [
                            "backup",
                            "--input",
                            "-",
                            "--output-dir",
                            "./cli-out",
                            "--shard-threshold",
                            "4",
                        ],
                        input="payload",
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured.get("output_dir"), "./cli-out")
        self.assertEqual(captured.get("shard_threshold"), 4)

    def test_backup_review_cancel_returns_code_1(self) -> None:
        input_file = cli.InputFile(
            source_path=Path("input.txt"),
            relative_path="input.txt",
            data=b"payload",
            mtime=None,
        )
        with (
            mock.patch(
                "ethernity.cli.flows.backup._prompt_encryption",
                return_value=("pass", 12),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._prompt_recovery_options",
                return_value=(False, False, SigningSeedMode.EMBEDDED, None, None),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._prompt_layout",
                return_value=(None, "A4"),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._prompt_design",
                return_value=None,
            ),
            mock.patch(
                "ethernity.cli.flows.backup.load_app_config",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.cli.flows.backup.apply_template_design",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._prompt_inputs",
                return_value=([input_file], None, None, "file", []),
            ),
            mock.patch(
                "ethernity.cli.flows.backup._build_review_rows",
                return_value=[("Inputs", None)],
            ),
            mock.patch(
                "ethernity.cli.flows.backup.prompt_yes_no",
                return_value=False,
            ),
            mock.patch(
                "ethernity.cli.flows.backup.ui_screen_mode",
                return_value=contextlib.nullcontext(),
            ) as screen_mode,
            mock.patch("ethernity.cli.flows.backup.console.print") as print_mock,
        ):
            result = cli.run_wizard(quiet=True)
        self.assertEqual(result, 1)
        screen_mode.assert_called_once_with(quiet=True)
        self.assertIn(mock.call("Backup cancelled."), print_mock.mock_calls)


if __name__ == "__main__":
    unittest.main()
