import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.age_cli import (
    AgeCliError,
    AgeKeygenError,
    decrypt_bytes,
    encrypt_bytes,
    encrypt_bytes_with_passphrase,
    generate_identity,
    parse_identities,
    parse_recipients,
    _drain_pty_loop,
    _drain_pty_with_passphrase,
    _run_age_with_pty,
    _safe_unlink,
    _safe_write,
    _write_temp_identities,
)
from test_support import write_fake_age_script


class TestAgeCli(unittest.TestCase):
    def _write_script(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text(body, encoding="utf-8")
        os.chmod(path, 0o755)
        return path

    def test_parse_identities_and_recipients(self) -> None:
        text = "\n# comment\nage1\n  age2  \n\n#another\n"
        self.assertEqual(parse_recipients(text), ["age1", "age2"])
        self.assertEqual(parse_identities(text), ["age1", "age2"])

    def test_autogen_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"payload"
            with mock.patch("ethernity.age_cli._generate_passphrase", return_value="test-passphrase"):
                ciphertext, passphrase = encrypt_bytes_with_passphrase(
                    data, passphrase=None, age_path=str(age_path)
                )
            self.assertEqual(ciphertext, data)
            self.assertEqual(passphrase, "test-passphrase")

    def test_decrypt_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"ciphertext"
            plaintext = decrypt_bytes(data, passphrase="secret", age_path=str(age_path))
            self.assertEqual(plaintext, data)

    def test_encrypt_bytes_requires_valid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            encrypt_bytes(b"payload")
        with self.assertRaises(ValueError):
            encrypt_bytes(b"payload", recipients=["age1"], passphrase="secret")
        with self.assertRaises(ValueError):
            encrypt_bytes(b"payload", recipients=[])

    def test_decrypt_bytes_requires_valid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            decrypt_bytes(b"payload")
        with self.assertRaises(ValueError):
            decrypt_bytes(b"payload", identities=["id"], passphrase="secret")
        with self.assertRaises(ValueError):
            decrypt_bytes(b"payload", identities=[])

    def test_encrypt_bytes_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"payload"
            ciphertext = encrypt_bytes(data, recipients=["age1"], age_path=str(age_path))
            self.assertEqual(ciphertext, data)

    def test_encrypt_bytes_recipient_error(self) -> None:
        script = """#!/usr/bin/env python3
import sys
sys.stderr.write("boom\\n")
sys.exit(2)
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = self._write_script(Path(tmpdir), "age", script)
            with self.assertRaises(AgeCliError) as ctx:
                encrypt_bytes(b"payload", recipients=["age1"], age_path=str(age_path))
        self.assertIn("boom", str(ctx.exception))

    def test_encrypt_bytes_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"payload"
            ciphertext = encrypt_bytes(data, passphrase="secret", age_path=str(age_path))
            self.assertEqual(ciphertext, data)

    def test_encrypt_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            age_path = write_fake_age_script(Path(tmpdir))
            data = b"payload"
            ciphertext, passphrase = encrypt_bytes_with_passphrase(
                data, passphrase="secret", age_path=str(age_path)
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
            with self.assertRaises(AgeCliError) as ctx:
                encrypt_bytes_with_passphrase(b"payload", passphrase="secret", age_path=str(age_path))
        self.assertIn("age failed", str(ctx.exception))

    def test_decrypt_identities_removes_temp_file(self) -> None:
        with mock.patch("ethernity.age_cli._run_age", return_value=b"ok"):
            with mock.patch("ethernity.age_cli.os.remove", side_effect=OSError):
                output = decrypt_bytes(b"payload", identities=["AGE-SECRET-KEY-TEST"])
        self.assertEqual(output, b"ok")

    def test_generate_identity_parses_output(self) -> None:
        script = """#!/usr/bin/env python3
import sys
sys.stdout.write("AGE-SECRET-KEY-TEST\\n")
sys.stderr.write("public key: age1recipient\\n")
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            age_keygen_path = self._write_script(Path(tmpdir), "age-keygen", script)
            identity, recipient = generate_identity(age_keygen_path=str(age_keygen_path))
        self.assertEqual(identity, "AGE-SECRET-KEY-TEST")
        self.assertEqual(recipient, "age1recipient")

    def test_generate_identity_parses_recipient_field(self) -> None:
        script = """#!/usr/bin/env python3
import sys
sys.stdout.write("AGE-SECRET-KEY-TEST\\n")
sys.stderr.write("recipient: age1recipient\\n")
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            age_keygen_path = self._write_script(Path(tmpdir), "age-keygen", script)
            identity, recipient = generate_identity(age_keygen_path=str(age_keygen_path))
        self.assertEqual(identity, "AGE-SECRET-KEY-TEST")
        self.assertEqual(recipient, "age1recipient")

    def test_generate_identity_missing_output(self) -> None:
        script = """#!/usr/bin/env python3
import sys
sys.stdout.write("AGE-SECRET-KEY-TEST\\n")
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            age_keygen_path = self._write_script(Path(tmpdir), "age-keygen", script)
            with self.assertRaises(ValueError):
                generate_identity(age_keygen_path=str(age_keygen_path))

    def test_generate_identity_error(self) -> None:
        script = """#!/usr/bin/env python3
import sys
sys.stderr.write("fail\\n")
sys.exit(2)
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            age_keygen_path = self._write_script(Path(tmpdir), "age-keygen", script)
            with self.assertRaises(AgeKeygenError) as ctx:
                generate_identity(age_keygen_path=str(age_keygen_path))
        self.assertIn("age-keygen failed", str(ctx.exception))

    def test_write_temp_identities(self) -> None:
        path = _write_temp_identities(["id1", "id2\n"])
        try:
            content = Path(path).read_text(encoding="utf-8")
        finally:
            os.remove(path)
        self.assertEqual(content, "id1\nid2\n")

    def test_safe_unlink_ignores_errors(self) -> None:
        with mock.patch("ethernity.age_cli.os.remove", side_effect=OSError):
            _safe_unlink("missing.txt")

    def test_safe_write_ignores_errors(self) -> None:
        with mock.patch("ethernity.age_cli.os.write", side_effect=OSError):
            _safe_write(1, b"data")

    def test_drain_pty_loop_handles_read_error(self) -> None:
        class FakeProc:
            def poll(self):
                return None

        with mock.patch("ethernity.age_cli.select.select", return_value=([1], [], [])):
            with mock.patch("ethernity.age_cli.os.read", side_effect=OSError):
                output = _drain_pty_loop(1, FakeProc())
        self.assertEqual(output, "")

    def test_drain_pty_loop_drains_after_exit(self) -> None:
        class FakeProc:
            def poll(self):
                return 0

        reads = [b"tail", b""]
        on_data_calls: list[bytes] = []

        def _read(_fd, _size):
            return reads.pop(0)

        with mock.patch("ethernity.age_cli.select.select", return_value=([], [], [])):
            with mock.patch("ethernity.age_cli.os.read", side_effect=_read):
                output = _drain_pty_loop(
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

        with mock.patch("ethernity.age_cli.select.select", return_value=([], [], [])):
            with mock.patch("ethernity.age_cli.os.read", return_value=b""):
                with mock.patch("ethernity.age_cli.time.monotonic", side_effect=_monotonic):
                    with mock.patch("ethernity.age_cli.os.write") as write_mock:
                        _drain_pty_with_passphrase(1, FakeProc(), "secret")
        self.assertTrue(write_mock.called)

    def test_run_age_with_pty_closes_on_error(self) -> None:
        def _builder(_output_path: str, _input_path: str):
            return ["age"]

        def _drain(_fd, _proc):
            return ""

        with mock.patch("ethernity.age_cli.pty.openpty", return_value=(123, 124)):
            with mock.patch("ethernity.age_cli.subprocess.Popen", side_effect=OSError("boom")):
                with mock.patch("ethernity.age_cli.os.close", side_effect=OSError):
                    with self.assertRaises(OSError):
                        _run_age_with_pty(cmd_builder=_builder, data=b"data", drain=_drain)


if __name__ == "__main__":
    unittest.main()
