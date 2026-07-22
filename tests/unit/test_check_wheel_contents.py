import importlib.util
import tarfile
import tempfile
import tomllib
import unittest
import unittest.mock
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "check_wheel_contents.py"
_SPEC = importlib.util.spec_from_file_location("check_wheel_contents", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class TestCheckWheelContents(unittest.TestCase):
    def test_package_configuration_only_includes_canonical_kit_bundles(self) -> None:
        with (_PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
            pyproject = tomllib.load(handle)

        setuptools_config = pyproject["tool"]["setuptools"]
        package_entries = setuptools_config["package-data"]["ethernity"]
        kit_entries = {entry for entry in package_entries if entry.startswith("resources/kit/")}

        self.assertFalse(setuptools_config["include-package-data"])
        self.assertEqual(
            kit_entries,
            {
                "resources/kit/recovery_kit.bundle.html",
                "resources/kit/recovery_kit.scanner.bundle.html",
            },
        )
        self.assertEqual(
            (_PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines(),
            [
                "recursive-exclude src/ethernity/resources/kit *.html",
                "include src/ethernity/resources/kit/recovery_kit.bundle.html",
                "include src/ethernity/resources/kit/recovery_kit.scanner.bundle.html",
                (
                    "recursive-include tests/fixtures/v1_2/extension_golden/raw/"
                    "gzip_replacement_chain/chain *.pdf"
                ),
            ],
        )

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

    def test_expected_source_entries_only_requires_canonical_kit_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "src" / "ethernity"
            kit_root = package_root / "resources" / "kit"
            kit_root.mkdir(parents=True)
            canonical_names = (
                "recovery_kit.bundle.html",
                "recovery_kit.scanner.bundle.html",
            )
            for name in canonical_names:
                (kit_root / name).write_text("canonical\n", encoding="utf-8")
            for name in (
                "recovery_kit.gzip.bundle.html",
                "recovery_kit.brotli.bundle.html",
                "recovery_kit.scanner.gzip.bundle.html",
                "recovery_kit.scanner.brotli.bundle.html",
            ):
                (kit_root / name).write_text("noncanonical\n", encoding="utf-8")

            self.assertEqual(
                _MODULE.expected_source_entries(package_root),
                {f"resources/kit/{name}" for name in canonical_names},
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

    def test_sdist_package_entries_returns_relative_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "sample-1.0.0" / "src" / "ethernity"
            source_root.mkdir(parents=True)
            (source_root / "module.py").write_text("x = 1\n", encoding="utf-8")
            (source_root / "resources").mkdir()
            (source_root / "resources" / "config.toml").write_text(
                "name='x'\n",
                encoding="utf-8",
            )
            sdist_path = temp_path / "sample-1.0.0.tar.gz"
            with tarfile.open(sdist_path, "w:gz") as archive:
                archive.add(temp_path / "sample-1.0.0", arcname="sample-1.0.0")

            self.assertEqual(
                _MODULE.sdist_package_entries(sdist_path),
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
