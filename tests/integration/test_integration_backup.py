import argparse
import tempfile
import unittest
from pathlib import Path

from ethernity.cli import run_backup_command
from test_support import prepend_path, suppress_output, write_fake_age_script


class TestIntegrationBackup(unittest.TestCase):
    def test_backup_command_passphrase(self) -> None:
        payload = b"backup integration payload"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            write_fake_age_script(tmp_path)
            with prepend_path(tmp_path):
                input_path = tmp_path / "input.bin"
                input_path.write_bytes(payload)
                output_dir = tmp_path / "backup"

                args = argparse.Namespace(
                    config=None,
                    paper="A4",
                    input=[str(input_path)],
                    input_dir=[],
                    base_dir=None,
                    output_dir=str(output_dir),
                    passphrase=None,
                    passphrase_generate=True,
                    sealed=False,
                    shard_threshold=None,
                    shard_count=None,
                    signing_key_mode=None,
                    signing_key_shard_threshold=None,
                    signing_key_shard_count=None,
                    debug=False,
                    debug_max_bytes=0,
                )
                with suppress_output():
                    run_backup_command(args)

                qr_path = output_dir / "qr_document.pdf"
                recovery_path = output_dir / "recovery_document.pdf"
                self.assertTrue(qr_path.exists())
                self.assertTrue(recovery_path.exists())
                self.assertTrue(qr_path.read_bytes().startswith(b"%PDF"))
                self.assertTrue(recovery_path.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
