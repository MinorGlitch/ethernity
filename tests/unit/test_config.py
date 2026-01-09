import tempfile
import unittest
from pathlib import Path

from ethernity.config import (
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    load_app_config,
)


class TestConfig(unittest.TestCase):
    def test_load_app_config_parses_qr_config(self) -> None:
        toml = """
[template]
path = 123

[recovery_template]
path = 456

[shard_template]
path = 789

[signing_key_shard_template]
path = 1011

[page]
size = "A4"

[qr]
scale = "6"
border = 2.0
module_shape = "square"
payload_encoding = 123
version = "3"
mask = 2
micro = "true"
boost_error = false
dark = [1, 2, 3]
light = [4, 5, 6, 7]
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_app_config(path=path)

        self.assertEqual(config.template_path, DEFAULT_TEMPLATE_PATH)
        self.assertEqual(config.recovery_template_path, DEFAULT_RECOVERY_TEMPLATE_PATH)
        self.assertEqual(config.shard_template_path, DEFAULT_SHARD_TEMPLATE_PATH)
        self.assertEqual(
            config.signing_key_shard_template_path,
            DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
        )
        self.assertEqual(config.paper_size, DEFAULT_PAPER_SIZE)
        self.assertEqual(config.qr_payload_encoding, "binary")
        self.assertEqual(config.qr_config.scale, 6)
        self.assertEqual(config.qr_config.border, 2)
        self.assertEqual(config.qr_config.module_shape, "square")
        self.assertEqual(config.qr_config.version, 3)
        self.assertEqual(config.qr_config.mask, 2)
        self.assertEqual(config.qr_config.micro, True)
        self.assertEqual(config.qr_config.dark, (1, 2, 3))
        self.assertEqual(config.qr_config.light, (4, 5, 6, 7))
        self.assertFalse(config.qr_config.boost_error)


if __name__ == "__main__":
    unittest.main()
