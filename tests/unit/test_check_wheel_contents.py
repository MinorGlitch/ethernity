import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_wheel_contents.py"
_SPEC = importlib.util.spec_from_file_location("check_wheel_contents", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class TestCheckWheelContents(unittest.TestCase):
    def test_expected_source_entries_ignores_python_cache_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "src" / "ethernity"
            (package_root / "__pycache__").mkdir(parents=True)
            (package_root / "resources").mkdir()
            (package_root / "module.py").write_text("x = 1\n", encoding="utf-8")
            (package_root / "__pycache__" / "module.cpython-311.pyc").write_bytes(b"pyc")
            (package_root / ".DS_Store").write_bytes(b"junk")
            (package_root / "resources" / "config.toml").write_text("name='x'\n", encoding="utf-8")

            self.assertEqual(
                _MODULE.expected_source_entries(package_root),
                {"module.py", "resources/config.toml"},
            )

    def test_wheel_package_entries_returns_relative_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel_path = Path(temp_dir) / "sample.whl"
            with zipfile.ZipFile(wheel_path, "w") as archive:
                archive.writestr("ethernity/module.py", "x = 1\n")
                archive.writestr("ethernity/resources/config.toml", "name='x'\n")
                archive.writestr("ethernity-1.0.0.dist-info/METADATA", "metadata")

            self.assertEqual(
                _MODULE.wheel_package_entries(wheel_path),
                {"module.py", "resources/config.toml"},
            )

    def test_main_fails_for_missing_package_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_root = temp_path / "src" / "ethernity"
            package_root.mkdir(parents=True)
            (package_root / "module.py").write_text("x = 1\n", encoding="utf-8")
            (package_root / "resources").mkdir()
            (package_root / "resources" / "config.toml").write_text("name='x'\n", encoding="utf-8")

            wheel_path = temp_path / "sample.whl"
            with zipfile.ZipFile(wheel_path, "w") as archive:
                archive.writestr("ethernity/module.py", "x = 1\n")

            argv = [
                "check_wheel_contents.py",
                "--package-root",
                str(package_root),
                str(wheel_path),
            ]
            with unittest.mock.patch("sys.argv", argv):
                self.assertEqual(_MODULE.main(), 1)
