import argparse
import tempfile
import unittest
from pathlib import Path

from ethernity import cli
from ethernity.cli.io.frames import _frames_from_fallback
from ethernity.encoding.chunking import frame_to_fallback_lines
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from tests.test_support import suppress_output


class TestCliRecoverValidation(unittest.TestCase):
    def test_conflicting_fallback_and_frames(self) -> None:
        args = argparse.Namespace(
            fallback_file="fallback.txt",
            payloads_file="frames.txt",
            scan=[],
            passphrase="pass",
            shard_fallback_file=[],
            auth_fallback_file=None,
            auth_payloads_file=None,
            shard_payloads_file=[],
            output=None,
            allow_unsigned=False,
            assume_yes=True,
            quiet=True,
        )
        with self.assertRaises(ValueError):
            cli.run_recover_command(args)

    def test_conflicting_scan_and_fallback(self) -> None:
        args = argparse.Namespace(
            fallback_file="fallback.txt",
            payloads_file=None,
            scan=["scan.png"],
            passphrase="pass",
            shard_fallback_file=[],
            auth_fallback_file=None,
            auth_payloads_file=None,
            shard_payloads_file=[],
            output=None,
            allow_unsigned=False,
            assume_yes=True,
            quiet=True,
        )
        with self.assertRaises(ValueError):
            cli.run_recover_command(args)

    def test_labeled_fallback_sections_parse(self) -> None:
        doc_id = b"\x10" * DOC_ID_LEN
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth-payload",
        )
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        auth_lines = frame_to_fallback_lines(auth_frame, line_length=80, line_count=None)
        main_lines = frame_to_fallback_lines(main_frame, line_length=80, line_count=None)
        lines = [
            cli.AUTH_FALLBACK_LABEL,
            *auth_lines,
            "",
            cli.MAIN_FALLBACK_LABEL,
            *main_lines,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            frames = _frames_from_fallback(
                str(path),
                allow_invalid_auth=False,
                quiet=True,
            )
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)
        self.assertEqual(frames[0].data, main_frame.data)
        self.assertEqual(frames[1].frame_type, FrameType.AUTH)
        self.assertEqual(frames[1].data, auth_frame.data)

    def test_labeled_fallback_missing_auth_section(self) -> None:
        doc_id = b"\x20" * DOC_ID_LEN
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        main_lines = frame_to_fallback_lines(main_frame, line_length=80, line_count=None)
        lines = [cli.MAIN_FALLBACK_LABEL, *main_lines]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            frames = _frames_from_fallback(
                str(path),
                allow_invalid_auth=False,
                quiet=True,
            )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)
        self.assertEqual(frames[0].data, main_frame.data)

    def test_labeled_fallback_invalid_auth_strict(self) -> None:
        doc_id = b"\x30" * DOC_ID_LEN
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        main_lines = frame_to_fallback_lines(main_frame, line_length=80, line_count=None)
        lines = [
            cli.AUTH_FALLBACK_LABEL,
            "not-a-valid-line!",
            "",
            cli.MAIN_FALLBACK_LABEL,
            *main_lines,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            with suppress_output():
                with self.assertRaises(ValueError):
                    _frames_from_fallback(
                        str(path),
                        allow_invalid_auth=False,
                        quiet=True,
                    )

    def test_labeled_fallback_invalid_auth_allowed(self) -> None:
        doc_id = b"\x40" * DOC_ID_LEN
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        main_lines = frame_to_fallback_lines(main_frame, line_length=80, line_count=None)
        lines = [
            cli.AUTH_FALLBACK_LABEL,
            "not-a-valid-line!",
            "",
            cli.MAIN_FALLBACK_LABEL,
            *main_lines,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            with suppress_output():
                frames = _frames_from_fallback(
                    str(path),
                    allow_invalid_auth=True,
                    quiet=True,
                )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)


if __name__ == "__main__":
    unittest.main()
