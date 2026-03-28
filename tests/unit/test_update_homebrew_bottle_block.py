import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "update_homebrew_bottle_block.py"
_SPEC = importlib.util.spec_from_file_location("update_homebrew_bottle_block", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class TestUpdateHomebrewBottleBlock(unittest.TestCase):
    def test_build_bottle_block_uses_cellar_and_sorted_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            linux_file = temp_path / "ethernity-v1.2.3.x86_64_linux.bottle.tar.gz"
            mac_file = temp_path / "ethernity-v1.2.3.arm64_sonoma.bottle.tar.gz"
            linux_file.write_bytes(b"linux")
            mac_file.write_bytes(b"mac")
            json_file = temp_path / "bottle.json"
            json_file.write_text(
                json.dumps({"ethernity": {"bottle": {"cellar": "/opt/homebrew/Cellar"}}}),
                encoding="utf-8",
            )

            block = _MODULE._build_bottle_block(
                "owner/tap",
                "ethernity-v1.2.3",
                [linux_file, mac_file],
                [json_file],
            )

        self.assertIn(
            'root_url "https://github.com/owner/tap/releases/download/ethernity-v1.2.3"',
            block,
        )
        self.assertLess(block.index("arm64_sonoma"), block.index("x86_64_linux"))
        self.assertIn(hashlib.sha256(b"mac").hexdigest(), block)
        self.assertIn(hashlib.sha256(b"linux").hexdigest(), block)
        self.assertIn('cellar: "/opt/homebrew/Cellar"', block)

    def test_insert_or_replace_bottle_block_replaces_existing_block(self) -> None:
        formula = """class Ethernity < Formula
  desc "Ethernity"
  homepage "https://example.com"
  license "GPL-3.0-or-later"

  bottle do
    root_url "https://example.com/old"
    sha256 cellar: :any_skip_relocation, arm64_sonoma: "old"
  end
end
"""
        bottle_block = """  bottle do
    root_url "https://example.com/new"
    sha256 cellar: :any_skip_relocation, arm64_sonoma: "new"
  end
"""

        updated = _MODULE._insert_or_replace_bottle_block(formula, bottle_block)

        self.assertIn('root_url "https://example.com/new"', updated)
        self.assertNotIn('root_url "https://example.com/old"', updated)
        self.assertEqual(updated.count("  bottle do"), 1)
