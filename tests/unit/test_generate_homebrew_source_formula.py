import hashlib
import importlib.util
import re
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate_homebrew_source_formula.py"
)
_SPEC = importlib.util.spec_from_file_location("generate_homebrew_source_formula", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _target(system: str, architecture: str):
    return next(
        target
        for target in _MODULE._HOMEBREW_TARGETS
        if (target.system, target.architecture) == (system, architecture)
    )


def _wheel(tags: str) -> dict[str, str]:
    filename = f"example-1.0-{tags}.whl"
    return {
        "url": f"https://example.com/{filename}",
        "hash": "sha256:" + hashlib.sha256(filename.encode()).hexdigest(),
    }


class TestGenerateHomebrewSourceFormula(unittest.TestCase):
    def test_wheel_selection_rejects_incompatible_python_abis(self) -> None:
        platform = "macosx_11_0_arm64"
        ordinary = {"url": f"https://example.com/example-1.0-cp313-cp313-{platform}.whl"}
        package = {
            "wheels": [
                {"url": f"https://example.com/example-1.0-{tag}-{platform}.whl"}
                for tag in ("cp313-cp313t", "cp313-cp313d", "cp314-cp314", "cp314-abi3")
            ]
        }
        target = _target("darwin", "arm64")
        self.assertIsNone(_MODULE._choose_wheel(package, target))
        package["wheels"].append(ordinary)
        self.assertEqual(_MODULE._choose_wheel(package, target), ordinary)

    def test_wheel_selection_preserves_stable_abi_and_pure_python_support(self) -> None:
        for tag in ("cp39-abi3", "cp313-abi3", "py3-none", "py2.py3-none", "py39-none"):
            with self.subTest(tag=tag):
                wheel = {"url": f"https://example.com/example-1.0-{tag}-any.whl"}
                for target in _MODULE._HOMEBREW_TARGETS:
                    self.assertEqual(_MODULE._choose_wheel({"wheels": [wheel]}, target), wheel)

    def test_wheel_selection_checks_platform_architecture_and_minimum_version(self) -> None:
        cases = (
            ("darwin", "arm64", "macosx_11_0_arm64", True),
            ("darwin", "arm64", "macosx_13_0_arm64", True),
            ("darwin", "arm64", "macosx_14_0_arm64", False),
            ("darwin", "arm64", "macosx_10_12_x86_64", False),
            ("darwin", "x86_64", "macosx_11_0_arm64", False),
            ("darwin", "x86_64", "macosx_26_0_x86_64", False),
            ("darwin", "x86_64", "manylinux_2_17_x86_64", False),
            ("linux", "x86_64", "macosx_10_12_x86_64", False),
            ("linux", "x86_64", "manylinux_2_28_x86_64", True),
            ("linux", "x86_64", "manylinux_2_35_x86_64", True),
            ("linux", "x86_64", "manylinux_2_36_x86_64", False),
            ("linux", "x86_64", "manylinux_2_17_aarch64", False),
            ("linux", "x86_64", "musllinux_1_2_x86_64", False),
            ("linux", "x86_64", "linux_x86_64", False),
            ("linux", "x86_64", "win_amd64", False),
            ("linux", "x86_64", "manylinux2010_x86_64", True),
            ("linux", "aarch64", "manylinux2010_aarch64", False),
            ("linux", "aarch64", "manylinux2014_aarch64", True),
            ("linux", "aarch64", "manylinux_2_28_aarch64", True),
        )
        for system, architecture, platform, compatible in cases:
            with self.subTest(system=system, architecture=architecture, platform=platform):
                wheel = _wheel(f"cp313-cp313-{platform}")
                selected = _MODULE._choose_wheel({"wheels": [wheel]}, _target(system, architecture))
                self.assertEqual(selected, wheel if compatible else None)

    def test_universal_and_compressed_tags_work_for_both_mac_architectures(self) -> None:
        for platform in (
            "macosx_10_9_universal2",
            "macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2",
        ):
            with self.subTest(platform=platform):
                wheel = _wheel(f"cp39-abi3-{platform}")
                for target in _MODULE._HOMEBREW_TARGETS:
                    selected = _MODULE._choose_wheel({"wheels": [wheel]}, target)
                    self.assertEqual(selected, wheel if target.system == "darwin" else None)

    def test_selection_prefers_native_wheel_and_preserves_locked_hash(self) -> None:
        pure = _wheel("py3-none-any")
        native = _wheel("cp313-cp313-macosx_11_0_arm64")
        stable = _wheel("cp39-abi3-macosx_11_0_arm64")
        for wheels in ([pure, stable, native], [native, stable, pure]):
            with self.subTest(wheels=wheels):
                package = {
                    "wheels": wheels,
                    "sdist": {
                        "url": "https://example.com/source.tar.gz",
                        "hash": "sha256:" + "a" * 64,
                    },
                }
                self.assertEqual(
                    _MODULE._choose_package_file_for_resource(package, _target("darwin", "arm64")),
                    (native["url"], native["hash"].removeprefix("sha256:")),
                )

    def test_incompatible_wheel_falls_back_to_locked_source(self) -> None:
        package = {
            "wheels": [
                {"url": "https://example.com/example-1.0-cp313-cp313t-macosx_11_0_arm64.whl"}
            ],
            "sdist": {
                "url": "https://example.com/example-1.0.tar.gz",
                "hash": "sha256:" + "a" * 64,
            },
        }
        self.assertEqual(
            _MODULE._choose_package_file_for_resource(package, _target("darwin", "arm64")),
            ("https://example.com/example-1.0.tar.gz", "a" * 64),
        )

    def test_resource_generation_rejects_missing_or_duplicate_placeholder(self) -> None:
        for count in (0, 2):
            with self.subTest(count=count):
                formula = (
                    "class Ethernity < Formula\n"
                    + "  # @locked-python-resources@\n" * count
                    + "end\n"
                )
                with self.assertRaisesRegex(ValueError, "exactly one locked resource placeholder"):
                    _MODULE._render_resources_from_lock(formula, {})

    def test_resource_generation_fails_when_target_has_no_locked_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "example on darwin/x86_64"):
            _MODULE._render_resource(
                "example", {"wheels": [_wheel("cp313-cp313-macosx_11_0_arm64")]}
            )

    def test_resource_generation_rejects_unverified_or_insecure_files(self) -> None:
        for source in (False, True):
            for change in (
                {"hash": "sha256:1234"},
                {"hash": "md5:" + "a" * 32},
                {"url": "http://example.com/source.tar.gz"},
            ):
                with self.subTest(source=source, change=change):
                    file = _wheel("py3-none-any")
                    file.update(change)
                    package = {"sdist": file} if source else {"wheels": [file]}
                    with self.assertRaises(ValueError):
                        _MODULE._render_resource("example", package)

    def test_shared_wheel_is_emitted_once(self) -> None:
        wheel = _wheel("py3-none-any")
        rendered = _MODULE._render_resource("example", {"wheels": [wheel]})
        self.assertEqual(rendered.count('resource "example"'), 1)
        self.assertNotIn("if ", rendered)
        self.assertIn(wheel["url"], rendered)

    def test_runtime_resources_are_generated_from_transitive_lock_dependencies(self) -> None:
        lock = {
            "ethernity-paper": {"dependencies": [{"name": "direct"}]},
            "direct": {
                "dependencies": [{"name": "transitive"}],
                "wheels": [_wheel("py3-none-any")],
            },
            "transitive": {"wheels": [_wheel("py3-none-any")]},
            "dev-only": {"wheels": [_wheel("py3-none-any")]},
        }
        rendered = _MODULE._render_resources_from_lock("  # @locked-python-resources@\n", lock)
        self.assertEqual(re.findall(r'resource "([^"]+)"', rendered), ["direct", "transitive"])

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

        self.assertIn(f'depends_on "python@3.{_MODULE._HOMEBREW_PYTHON_MINOR}"', rendered)
        self.assertNotIn('depends_on "pillow"', rendered)
        self.assertIn('resource "pillow"', rendered)
        self.assertNotIn("-cp313t-", rendered)
        self.assertNotIn("-cp314-", rendered)
        self.assertNotIn('resource "colorama"', rendered)

        for target in _MODULE._HOMEBREW_TARGETS:
            for name in ("pydantic-core", "psutil", "pycryptodome", "pyrage", "cbor2"):
                with self.subTest(target=target, package=name):
                    url, sha = _MODULE._choose_package_file_for_resource(
                        lock_packages[name], target
                    )
                    source_only = name == "cbor2" and (target.system, target.architecture) == (
                        "darwin",
                        "x86_64",
                    )
                    self.assertTrue(url.endswith(".tar.gz" if source_only else ".whl"), url)
                    files = [*lock_packages[name]["wheels"], lock_packages[name]["sdist"]]
                    self.assertIn(
                        {"url": url, "hash": "sha256:" + sha},
                        [{"url": file["url"], "hash": file["hash"]} for file in files],
                    )
                    self.assertIn(url, rendered)
