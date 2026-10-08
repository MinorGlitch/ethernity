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
from unittest import mock

from tooling.document_inspector_app import bootstrap, gui, styles


class TestDocumentInspectorAppSupport(unittest.TestCase):
    def test_bootstrap_exports_repo_roots_and_inserts_src_path(self) -> None:
        self.assertEqual(bootstrap.SRC_ROOT, bootstrap.REPO_ROOT / "src")
        self.assertIn(str(bootstrap.SRC_ROOT), sys.path)

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
