import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.crypto import age_fetch


class _FakeDownload:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __call__(self, _url: str, dest: Path) -> None:
        dest.write_bytes(self._payload)


class _FakeExtract:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __call__(self, _archive_path: Path, dest: Path, _binary_name: str) -> None:
        dest.write_bytes(self._payload)


class TestAgeFetch(unittest.TestCase):
    def test_download_spec_windows_amd64(self) -> None:
        with mock.patch("ethernity.crypto.age_fetch.sys.platform", "win32"):
            with mock.patch("ethernity.crypto.age_fetch.platform.machine", return_value="arm64"):
                name, url, kind = age_fetch._age_download_spec(path_env="ENV_PATH")
        self.assertEqual(kind, "zip")
        self.assertIn("windows-amd64", name)
        self.assertIn(name, url)

    def test_download_spec_unsupported_arch(self) -> None:
        with mock.patch("ethernity.crypto.age_fetch.sys.platform", "linux"):
            with mock.patch("ethernity.crypto.age_fetch.platform.machine", return_value="mips64"):
                with self.assertRaises(RuntimeError) as ctx:
                    age_fetch._age_download_spec(path_env="ENV_PATH")
        self.assertIn("Supported", str(ctx.exception))

    def test_download_age_binary_writes_dest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dest_path = Path(tmpdir) / "age"
            with mock.patch(
                "ethernity.crypto.age_fetch._age_download_spec",
                return_value=("age.zip", "https://example", "zip"),
            ):
                with mock.patch(
                    "ethernity.crypto.age_fetch._download_file",
                    side_effect=_FakeDownload(b"archive"),
                ):
                    with mock.patch(
                        "ethernity.crypto.age_fetch._extract_from_zip",
                        side_effect=_FakeExtract(b"binary"),
                    ) as extract_mock:
                        age_fetch.download_age_binary(
                            dest_path=dest_path,
                            binary_name="age",
                            path_env="ENV_PATH",
                        )
            extract_mock.assert_called_once()
            self.assertTrue(dest_path.exists())
            self.assertEqual(dest_path.read_bytes(), b"binary")


if __name__ == "__main__":
    unittest.main()
