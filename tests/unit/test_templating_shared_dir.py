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

import tempfile
import unittest
from pathlib import Path

from ethernity.render.templating import render_template


class TestTemplatingSharedDir(unittest.TestCase):
    def test_sibling_shared_dir_is_used_for_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "design").mkdir(parents=True, exist_ok=True)
            (root / "_shared").mkdir(parents=True, exist_ok=True)

            (root / "_shared" / "shared_macro.j2").write_text(
                "{% macro greeting() %}SENTINEL{% endmacro %}",
                encoding="utf-8",
            )
            (root / "design" / "main.html.j2").write_text(
                "{% from 'shared_macro.j2' import greeting %}{{ greeting() }}",
                encoding="utf-8",
            )

            rendered = render_template(root / "design" / "main.html.j2", {})
            self.assertIn("SENTINEL", rendered)


if __name__ == "__main__":
    unittest.main()
