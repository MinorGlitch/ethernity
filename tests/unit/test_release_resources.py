import io
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import unittest.mock
import zipfile
from pathlib import Path

import pytest
from tooling import release_resources as _MODULE

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestReleaseResources(unittest.TestCase):
    def test_package_configuration_only_includes_required_kit_bundles(self) -> None:
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
                "resources/kit/recovery_kit.assembler.html",
            },
        )
        self.assertEqual(
            (_PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines(),
            [
                "include tooling/__init__.py",
                "include tooling/release_resources.py",
                (
                    "recursive-include tests/fixtures/v1_2/extension_golden/base64/"
                    "gzip_replacement_chain/chain *.pdf"
                ),
            ],
        )

    def test_expected_source_entries_ignores_python_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "src" / "ethernity"
            (package_root / "__pycache__").mkdir(parents=True)
            (package_root / "resources").mkdir()
            (package_root / "module.py").write_text("x = 1\n", encoding="utf-8")
            (package_root / "__pycache__" / "module.cpython-311.pyc").write_bytes(b"pyc")
            (package_root / ".DS_Store").write_bytes(b"junk")
            (package_root / "resources" / "config").mkdir()
            (package_root / "resources" / "config" / "defaults.toml").write_text(
                "name='x'\n", encoding="utf-8"
            )
            (package_root / "STYLING.md").write_text("internal guide", encoding="utf-8")

            self.assertEqual(
                _MODULE.expected_source_entries(package_root),
                {"module.py", "resources/config/defaults.toml"} | _MODULE.REQUIRED_KIT_ENTRIES,
            )

    def test_expected_source_entries_only_requires_required_kit_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "src" / "ethernity"
            kit_root = package_root / "resources" / "kit"
            kit_root.mkdir(parents=True)
            published_names = (
                "recovery_kit.bundle.html",
                "recovery_kit.scanner.bundle.html",
                "recovery_kit.assembler.html",
            )
            for name in published_names:
                (kit_root / name).write_text("required\n", encoding="utf-8")
            for name in (
                "recovery_kit.gzip.bundle.html",
                "recovery_kit.brotli.bundle.html",
                "recovery_kit.scanner.gzip.bundle.html",
                "recovery_kit.scanner.brotli.bundle.html",
            ):
                (kit_root / name).write_text("extra\n", encoding="utf-8")

            self.assertEqual(
                _MODULE.expected_source_entries(package_root),
                {f"resources/kit/{name}" for name in published_names},
            )

    def test_wheel_package_entries_returns_relative_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel_path = Path(temp_dir) / "sample.whl"
            with zipfile.ZipFile(wheel_path, "w") as archive:
                archive.writestr("ethernity/module.py", "x = 1\n")
                archive.writestr("ethernity/resources/config.toml", "name='x'\n")
                archive.writestr("ethernity-1.0.0.dist-info/METADATA", "metadata")

            self.assertEqual(
                set(_MODULE.wheel_package_sizes(wheel_path)),
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
                set(_MODULE.sdist_package_sizes(sdist_path)),
                {"module.py", "resources/config.toml"},
            )

    def test_main_fails_for_missing_package_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            package_root = temp_path / "src" / "ethernity"
            package_root.mkdir(parents=True)
            (package_root / "module.py").write_text("x = 1\n", encoding="utf-8")
            (package_root / "resources").mkdir()
            (package_root / "resources" / "config").mkdir()
            (package_root / "resources" / "config" / "defaults.toml").write_text(
                "name='x'\n", encoding="utf-8"
            )

            wheel_path = temp_path / "sample.whl"
            with zipfile.ZipFile(wheel_path, "w") as archive:
                archive.writestr("ethernity/module.py", "x = 1\n")

            argv = [
                "release_resources",
                "--package-root",
                str(package_root),
                str(wheel_path),
            ]
            with unittest.mock.patch("sys.argv", argv):
                self.assertEqual(_MODULE.main(), 1)


@pytest.fixture
def bundle_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "kit"
    directory.mkdir()
    for name in _MODULE.REQUIRED_KIT_NAMES:
        (directory / name).write_bytes(b"x" * _MODULE.MIN_BUNDLE_BYTES)
    return directory


def test_generated_bundle_inventory_passes(bundle_directory: Path) -> None:
    _MODULE.require_kit_bundles(bundle_directory)


@pytest.mark.parametrize("size", [0, 1, 999])
def test_generated_bundle_rejects_small_files(bundle_directory: Path, size: int) -> None:
    name = sorted(_MODULE.REQUIRED_KIT_NAMES)[0]
    (bundle_directory / name).write_bytes(b"x" * size)
    with pytest.raises(ValueError, match="kit bundle too small"):
        _MODULE.require_kit_bundles(bundle_directory)


def test_generated_bundle_rejects_missing_files(bundle_directory: Path) -> None:
    name = sorted(_MODULE.REQUIRED_KIT_NAMES)[0]
    (bundle_directory / name).unlink()
    with pytest.raises(ValueError, match="missing kit bundle"):
        _MODULE.require_kit_bundles(bundle_directory)


def test_generated_bundle_rejects_unexpected_html(bundle_directory: Path) -> None:
    (bundle_directory / "optional.brotli.bundle.html").write_bytes(b"x" * 1000)
    with pytest.raises(ValueError, match="unexpected kit bundle"):
        _MODULE.require_kit_bundles(bundle_directory)


def test_missing_generated_directory_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing kit bundle"):
        _MODULE.require_kit_bundles(tmp_path / "missing")


def test_directory_in_place_of_bundle_fails(bundle_directory: Path) -> None:
    path = bundle_directory / sorted(_MODULE.REQUIRED_KIT_NAMES)[0]
    path.unlink()
    path.mkdir()
    with pytest.raises(ValueError, match="kit bundle too small"):
        _MODULE.require_kit_bundles(bundle_directory)


def test_bundle_check_ignores_non_html_resources(bundle_directory: Path) -> None:
    (bundle_directory / "notes.txt").write_text("not a bundle", encoding="utf-8")
    _MODULE.require_kit_bundles(bundle_directory)


def _write_package(path: Path, entries: dict[str, bytes]) -> None:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(f"ethernity/{name}", data)
    else:
        with tarfile.open(path, "w:gz") as archive:
            for name, data in entries.items():
                member = tarfile.TarInfo(f"sample-1.0/src/ethernity/{name}")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
@pytest.mark.parametrize("problem", [None, "missing", "empty", "small", "extra", "source_missing"])
def test_archive_uses_bundle_policy(
    tmp_path: Path, suffix: str, problem: str | None, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    package_root = tmp_path / "source"
    package_root.mkdir()
    entries = {entry: b"x" * 1000 for entry in _MODULE.REQUIRED_KIT_ENTRIES}
    name = sorted(entries)[0]
    if problem in {"missing", "source_missing"}:
        del entries[name]
    elif problem in {"empty", "small"}:
        entries[name] = b"" if problem == "empty" else b"x" * 999
    elif problem == "extra":
        entries["resources/kit/optional.brotli.bundle.html"] = b"x" * 1000

    if problem != "source_missing":
        for entry in _MODULE.REQUIRED_KIT_ENTRIES:
            source_path = package_root / entry
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"x" * 1000)
    archive = tmp_path / f"sample{suffix}"
    _write_package(archive, entries)
    monkeypatch.setattr(
        sys, "argv", ["release_resources", "--package-root", str(package_root), str(archive)]
    )
    assert _MODULE.main() == (0 if problem is None else 1)
    if problem is not None:
        message = "missing" if problem == "source_missing" else problem
        if problem in {"empty", "small"}:
            message = "too small"
        elif problem == "extra":
            message = "unexpected"
        assert message in capsys.readouterr().err


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
def test_archive_rejects_corrupt_input(
    tmp_path: Path, suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / f"corrupt{suffix}"
    archive.write_bytes(b"not an archive")
    monkeypatch.setattr(sys, "argv", ["release_resources", str(archive)])
    assert _MODULE.main() == 1


def test_directory_cli_works_without_installed_package(
    bundle_directory: Path, tmp_path: Path
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(_PROJECT_ROOT / "tooling" / "release_resources.py"),
            "--kit-directory",
            str(bundle_directory),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cli_requires_something_to_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["release_resources"])
    with pytest.raises(SystemExit) as error:
        _MODULE.main()
    assert error.value.code == 2
