import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.crypto import (
    AgeCliError,
    decrypt_bytes,
    encrypt_bytes_with_passphrase,
)
from ethernity.crypto import age_cli
from test_support import write_fake_age_script


class TestAgeCli(unittest.TestCase):
    def _write_script(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text(body, encoding="utf-8")
        os.chmod(path, 0o755)
        return path

    def test_autogen_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"payload"
            with mock.patch.dict(
                os.environ, {age_cli._AGE_PATH_ENV: str(age_path)}, clear=False
            ):
                with mock.patch(
                    "ethernity.crypto.age_cli.generate_passphrase", return_value="test-passphrase"
                ):
                    ciphertext, passphrase = encrypt_bytes_with_passphrase(
                        data, passphrase=None
                    )
            self.assertEqual(ciphertext, data)
            self.assertEqual(passphrase, "test-passphrase")

    def test_decrypt_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"ciphertext"
            with mock.patch.dict(
                os.environ, {age_cli._AGE_PATH_ENV: str(age_path)}, clear=False
            ):
                plaintext = decrypt_bytes(data, passphrase="secret")
            self.assertEqual(plaintext, data)

    def test_encrypt_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"payload"
            with mock.patch.dict(
                os.environ, {age_cli._AGE_PATH_ENV: str(age_path)}, clear=False
            ):
                ciphertext, passphrase = encrypt_bytes_with_passphrase(
                    data, passphrase="secret"
                )
            self.assertEqual(ciphertext, data)
        self.assertEqual(passphrase, "secret")

    def test_encrypt_passphrase_error(self) -> None:
        script = """#!/usr/bin/env python3
import sys
sys.stderr.write("Enter passphrase: ")
sys.stderr.flush()
sys.exit(2)
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = self._write_script(Path(tmpdir), "age", script)
            with mock.patch.dict(
                os.environ, {age_cli._AGE_PATH_ENV: str(age_path)}, clear=False
            ):
                with self.assertRaises(AgeCliError) as ctx:
                    encrypt_bytes_with_passphrase(b"payload", passphrase="secret")
        self.assertIn("age failed", str(ctx.exception))

    def test_encrypt_passphrase_sets_env_without_pty(self) -> None:
        data = b"payload"
        captured: dict[str, object] = {}

        def _run(cmd, input=None, stdout=None, stderr=None, env=None, check=None):
            captured["env"] = env
            captured["input"] = input
            output_path = None
            input_path = None
            if "-o" in cmd:
                idx = cmd.index("-o")
                if idx + 1 < len(cmd):
                    output_path = cmd[idx + 1]
            if cmd:
                input_path = cmd[-1]
            if output_path and input_path:
                with open(input_path, "rb") as src, open(output_path, "wb") as dst:
                    dst.write(src.read())
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        with mock.patch("ethernity.crypto.age_cli._USE_PTY", False):
            with mock.patch("ethernity.crypto.age_cli.subprocess.run", side_effect=_run):
                with mock.patch.dict(
                    os.environ, {age_cli._AGE_PATH_ENV: "age"}, clear=False
                ):
                    ciphertext, passphrase = encrypt_bytes_with_passphrase(
                        data, passphrase="secret"
                    )

        self.assertEqual(ciphertext, data)
        self.assertEqual(passphrase, "secret")
        env = captured.get("env")
        self.assertIsInstance(env, dict)
        self.assertEqual(env.get("AGE_PASSPHRASE"), "secret")
        self.assertEqual(captured.get("input"), b"secret\nsecret\n")

    def test_safe_unlink_ignores_errors(self) -> None:
        with mock.patch("ethernity.crypto.age_cli.os.remove", side_effect=OSError):
            age_cli._safe_unlink("missing.txt")

    def test_safe_write_ignores_errors(self) -> None:
        with mock.patch("ethernity.crypto.age_cli.os.write", side_effect=OSError):
            age_cli._safe_write(1, b"data")

    def test_drain_pty_loop_handles_read_error(self) -> None:
        class FakeProc:
            def poll(self):
                return None

        with mock.patch("ethernity.crypto.age_cli.select.select", return_value=([1], [], [])):
            with mock.patch("ethernity.crypto.age_cli.os.read", side_effect=OSError):
                output = age_cli._drain_pty_loop(1, FakeProc())
        self.assertEqual(output, "")

    def test_drain_pty_loop_drains_after_exit(self) -> None:
        class FakeProc:
            def poll(self):
                return 0

        reads = [b"tail", b""]
        on_data_calls: list[bytes] = []

        def _read(_fd, _size):
            return reads.pop(0)

        with mock.patch("ethernity.crypto.age_cli.select.select", return_value=([], [], [])):
            with mock.patch("ethernity.crypto.age_cli.os.read", side_effect=_read):
                output = age_cli._drain_pty_loop(
                    1,
                    FakeProc(),
                    on_data=on_data_calls.append,
                )
        self.assertEqual(output, "tail")
        self.assertEqual(on_data_calls, [b"tail"])

    def test_drain_pty_with_passphrase_timeout(self) -> None:
        class FakeProc:
            def poll(self):
                return 0

        times = [0.0, 3.0, 3.0]

        def _monotonic():
            return times.pop(0) if times else 3.0

        with mock.patch("ethernity.crypto.age_cli.select.select", return_value=([], [], [])):
            with mock.patch("ethernity.crypto.age_cli.os.read", return_value=b""):
                with mock.patch("ethernity.crypto.age_cli.time.monotonic", side_effect=_monotonic):
                    with mock.patch("ethernity.crypto.age_cli.os.write") as write_mock:
                        age_cli._drain_pty_with_passphrase(1, FakeProc(), "secret")
        self.assertTrue(write_mock.called)

    def test_run_age_with_pty_closes_on_error(self) -> None:
        def _builder(_output_path: str, _input_path: str):
            return ["age"]

        def _drain(_fd, _proc):
            return ""

        fake_pty = mock.Mock()
        fake_pty.openpty.return_value = (123, 124)
        fake_fcntl = mock.Mock()
        fake_fcntl.ioctl.return_value = 0
        fake_termios = mock.Mock(TIOCSCTTY=1)
        with mock.patch("ethernity.crypto.age_cli._USE_PTY", True):
            with mock.patch("ethernity.crypto.age_cli._pty", fake_pty):
                with mock.patch("ethernity.crypto.age_cli._fcntl", fake_fcntl):
                    with mock.patch("ethernity.crypto.age_cli._termios", fake_termios):
                        with mock.patch(
                            "ethernity.crypto.age_cli.subprocess.Popen",
                            side_effect=OSError("boom"),
                        ):
                            with mock.patch("ethernity.crypto.age_cli.os.close", side_effect=OSError):
                                with self.assertRaises(OSError):
                                    age_cli._run_age_with_pty(
                                        cmd_builder=_builder,
                                        data=b"data",
                                        drain=_drain,
                                    )


if __name__ == "__main__":
    unittest.main()
