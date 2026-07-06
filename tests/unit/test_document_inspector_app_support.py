# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from tooling.document_inspector_app import bootstrap, gui, models, styles

from ethernity.encoding.framing import Frame, FrameType


class TestDocumentInspectorAppSupport(unittest.TestCase):
    def test_bootstrap_exports_repo_roots_and_inserts_src_path(self) -> None:
        self.assertEqual(bootstrap.SRC_ROOT, bootstrap.REPO_ROOT / "src")
        self.assertIn(str(bootstrap.SRC_ROOT), sys.path)

    def test_models_support_dataclass_instantiation(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"auth-payload",
        )
        frame_record = models.FrameRecord(
            frame=frame,
            detail={"kind": "auth"},
            detail_text="detail",
            raw_text="raw",
            cbor_text="cbor",
            payload_text="payload",
            fallback_text="fallback",
        )
        file_record = models.FileRecord(
            path="docs/notes.txt",
            size=5,
            sha256="ab" * 32,
            preview_kind="text",
            preview="hello",
            data=b"hello",
        )
        secret_record = models.RecoveredSecretRecord(
            label="passphrase",
            status="recoverable",
            summary="ok",
            detail_text="detail",
            export_name="passphrase.txt",
            export_text="secret",
        )
        trust_diagnostic = models.TrustDiagnostic(
            status="refused",
            code="RECOVERY_HEAD_UNTRUSTED",
            message="latest supplied recovery head could not be trusted: test fixture",
            details={"failure_stage": "decode"},
        )
        inspection = models.InspectionResult(
            source_label="clipboard",
            input_mode="payloads",
            parsed_frame_count=1,
            deduped_frame_count=1,
            warnings=(),
            summary_text="summary",
            diagnostics_text="diagnostics",
            normalized_payload_text="payload",
            combined_fallback_text="fallback",
            document_text="document",
            document_json_text='{"kind":"documents"}',
            projection_diagnostics_text="projection",
            frame_records=(frame_record,),
            files=(file_record,),
            recovered_secrets=(secret_record,),
            trust_diagnostic=trust_diagnostic,
            report_json="{}",
        )
        batch_entry = models.BatchReportEntry(
            source_label="batch",
            source_path="/tmp/input.txt",
            frame_count=1,
            doc_ids=("11" * 16,),
            frame_types=("AUTH",),
            warnings=(),
            error=None,
        )

        self.assertEqual(inspection.frame_records[0].frame, frame)
        self.assertEqual(inspection.files[0].data, b"hello")
        self.assertEqual(inspection.recovered_secrets[0].label, "passphrase")
        self.assertEqual(inspection.trust_diagnostic.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(batch_entry.source_path, "/tmp/input.txt")

    def test_detect_system_theme_name_uses_gtk_theme_hint(self) -> None:
        with (
            mock.patch.object(styles.sys, "platform", "linux"),
            mock.patch.dict(styles.os.environ, {"GTK_THEME": "Adwaita:dark"}, clear=False),
        ):
            self.assertEqual(styles._detect_system_theme_name(), "dark")

    def test_detect_system_theme_name_uses_macos_dark_mode(self) -> None:
        completed = mock.Mock(returncode=0, stdout="Dark\n")
        with (
            mock.patch.object(styles.sys, "platform", "darwin"),
            mock.patch(
                "tooling.document_inspector_app.styles.subprocess.run",
                return_value=completed,
            ),
        ):
            self.assertEqual(styles._detect_system_theme_name(), "dark")

    def test_configure_styles_delegates_to_theme_controller(self) -> None:
        root = mock.Mock()
        controller = mock.Mock()
        with mock.patch(
            "tooling.document_inspector_app.styles.ThemeController",
            return_value=controller,
        ) as theme_controller:
            resolved = styles.configure_styles(root)

        theme_controller.assert_called_once_with(root)
        self.assertIs(resolved, controller)

    def test_gui_main_falls_back_to_tk_when_dnd_is_unavailable(self) -> None:
        root = mock.Mock()
        with (
            mock.patch("tooling.document_inspector_app.gui.TkinterDnD", None),
            mock.patch("tooling.document_inspector_app.gui.Tk", return_value=root) as tk_ctor,
            mock.patch("tooling.document_inspector_app.gui.InspectorApp") as inspector_app,
        ):
            exit_code = gui.main()

        tk_ctor.assert_called_once_with()
        inspector_app.assert_called_once_with(root)
        root.mainloop.assert_called_once_with()
        self.assertEqual(exit_code, 0)

    def test_gui_main_prefers_tkinterdnd_when_available(self) -> None:
        root = mock.Mock()
        dnd_module = mock.Mock()
        dnd_module.Tk.return_value = root
        with (
            mock.patch("tooling.document_inspector_app.gui.TkinterDnD", dnd_module),
            mock.patch("tooling.document_inspector_app.gui.Tk") as tk_ctor,
            mock.patch("tooling.document_inspector_app.gui.InspectorApp") as inspector_app,
        ):
            exit_code = gui.main()

        dnd_module.Tk.assert_called_once_with()
        tk_ctor.assert_not_called()
        inspector_app.assert_called_once_with(root)
        root.mainloop.assert_called_once_with()
        self.assertEqual(exit_code, 0)

    def test_gui_session_state_defaults_result_to_none(self) -> None:
        source_path = str(Path("/tmp/input.txt"))
        session = gui.SessionState(
            key="session-1",
            title="Session 1",
            source_label="Clipboard",
            source_paths=(source_path,),
            container=mock.Mock(),
            info_var=mock.Mock(),
            text_widget=mock.Mock(),
        )

        self.assertIsNone(session.result)
        self.assertEqual(session.source_paths, (source_path,))
