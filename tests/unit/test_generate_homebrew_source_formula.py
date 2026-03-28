import importlib.util
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate_homebrew_source_formula.py"
)
_SPEC = importlib.util.spec_from_file_location("generate_homebrew_source_formula", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class TestGenerateHomebrewSourceFormula(unittest.TestCase):
    def test_render_resources_from_lock_rejects_missing_runtime_resource_block(self) -> None:
        formula = """
class Ethernity < Formula
  url "https://example.com/source.tar.gz"
  sha256 "abc"
end
"""
        lock_packages = {
            "ethernity-paper": {
                "dependencies": [
                    {
                        "name": "cbor2",
                    }
                ]
            },
            "cbor2": {
                "dependencies": [],
                "sdist": {
                    "url": "https://example.com/cbor2.tar.gz",
                    "hash": "sha256:1234",
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "missing resource blocks"):
            _MODULE._render_resources_from_lock(formula, lock_packages)

    def test_required_runtime_resource_names_skip_windows_only_and_formula_depends_on(self) -> None:
        lock_packages = {
            "ethernity-paper": {
                "dependencies": [
                    {"name": "click"},
                    {"name": "pillow"},
                ]
            },
            "click": {
                "dependencies": [
                    {"name": "colorama", "marker": "sys_platform == 'win32'"},
                    {"name": "rich"},
                ]
            },
            "pillow": {"dependencies": []},
            "colorama": {"dependencies": []},
            "rich": {"dependencies": []},
        }

        required = _MODULE._required_runtime_resource_names(
            lock_packages,
            formula_dependency_names={"pillow"},
        )

        self.assertEqual(required, {"click", "rich"})

    def test_required_runtime_resource_names_include_supported_non_windows_markers(self) -> None:
        lock_packages = {
            "ethernity-paper": {
                "dependencies": [
                    {"name": "click"},
                ]
            },
            "click": {
                "dependencies": [
                    {"name": "jeepney", "marker": "sys_platform == 'linux'"},
                    {"name": "secretstorage", "marker": "sys_platform == 'linux'"},
                    {"name": "colorama", "marker": "sys_platform == 'win32'"},
                ]
            },
            "jeepney": {"dependencies": []},
            "secretstorage": {"dependencies": []},
            "colorama": {"dependencies": []},
        }

        required = _MODULE._required_runtime_resource_names(lock_packages)

        self.assertEqual(required, {"click", "jeepney", "secretstorage"})

    def test_required_runtime_resource_names_skip_non_homebrew_runtime_markers(self) -> None:
        lock_packages = {
            "ethernity-paper": {
                "dependencies": [
                    {"name": "cryptography"},
                ]
            },
            "cryptography": {
                "dependencies": [
                    {"name": "cffi", "marker": "platform_python_implementation != 'PyPy'"},
                    {"name": "pywin32-ctypes", "marker": "sys_platform == 'win32'"},
                    {"name": "pypy-only", "marker": "implementation_name == 'pypy'"},
                ]
            },
            "cffi": {"dependencies": []},
            "pywin32-ctypes": {"dependencies": []},
            "pypy-only": {"dependencies": []},
        }

        required = _MODULE._required_runtime_resource_names(lock_packages)

        self.assertEqual(required, {"cryptography", "cffi"})

    def test_real_formula_matches_real_lockfile(self) -> None:
        root = Path(__file__).resolve().parents[2]
        formula = (root / "scripts" / "homebrew_ethernity_tap.rb").read_text(encoding="utf-8")
        lock_packages = _MODULE._load_lock_packages(root / "uv.lock")

        rendered = _MODULE._render_resources_from_lock(formula, lock_packages)

        self.assertIn('depends_on "pillow"', rendered)
        self.assertNotIn('resource "colorama"', rendered)
