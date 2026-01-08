import argparse
import tempfile
import unittest
from pathlib import Path

from ethernity.cli import run_backup_command
from test_support import suppress_output, temp_env


class TestIntegrationBackup(unittest.TestCase):
    def test_backup_command_passphrase(self) -> None:
        payload = b"backup integration payload"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            config_path = repo_root / "ethernity" / "config" / "a4.toml"
            env_overrides = {
                "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
            }
            with temp_env(env_overrides):
                input_path = tmp_path / "input.bin"
                input_path.write_bytes(payload)
                output_dir = tmp_path / "backup"

                args = argparse.Namespace(
                    config=str(config_path),
                    paper=None,
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
