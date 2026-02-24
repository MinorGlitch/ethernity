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

import unittest

from ethernity.render.template_model import (
    DocModel,
    FallbackBlockModel,
    InstructionsModel,
    PageModel,
    QrGridModel,
    QrItemModel,
    QrOutlineModel,
    QrSequenceLabelModel,
    QrSequenceLineModel,
    QrSequenceModel,
    RecoveryModel,
    TemplateContext,
)


class TestTemplateModel(unittest.TestCase):
    def test_template_context_serialization_shape_is_stable(self) -> None:
        context = TemplateContext(
            page_size_css="A4",
            page_width_mm=210.0,
            page_height_mm=297.0,
            margin_mm=14.0,
            usable_width_mm=182.0,
            doc_id="deadbeef" * 4,
            created_timestamp_utc="2026-01-01 00:00 UTC",
            doc=DocModel(title="Recovery Document", subtitle="Keys + Text Fallback"),
            instructions=InstructionsModel(
                label="Instructions",
                lines=("A", "B"),
                scan_hint="Start at the top-left and follow each row.",
            ),
            pages=(
                PageModel(
                    page_num=1,
                    page_label="Page 1 / 1",
                    show_instructions=True,
                    instructions_full_page=False,
                    qr_items=(QrItemModel(index=1, data_uri="data:image/png;base64,AA=="),),
                    qr_grid=QrGridModel(
                        size_mm=50.0,
                        gap_x_mm=2.0,
                        gap_y_mm=2.0,
                        cols=3,
                        rows=1,
                        count=1,
                        x_mm=14.0,
                        y_mm=60.0,
                    ),
                    fallback_blocks=(
                        FallbackBlockModel(
                            title="AUTH FRAME",
                            lines=("line-01", "line-02"),
                            line_offset=0,
                            y_mm=90.0,
                            height_mm=10.0,
                        ),
                    ),
                    divider_y_mm=30.0,
                    instructions_y_mm=40.0,
                    qr_outline=QrOutlineModel(
                        x_mm=14.0,
                        y_mm=60.0,
                        width_mm=50.0,
                        height_mm=50.0,
                    ),
                    sequence=QrSequenceModel(
                        lines=(QrSequenceLineModel(x1=1.0, y1=2.0, x2=3.0, y2=4.0),),
                        labels=(QrSequenceLabelModel(x=2.0, y=1.0, text="1"),),
                    ),
                    fallback_line_capacity=12,
                    fallback_row_height_mm=5.8,
                ),
            ),
            fallback_width_mm=182.0,
            recovery=RecoveryModel(
                passphrase="alpha beta",
                passphrase_lines=("alpha beta",),
                quorum_value="2 of 3",
                signing_pub_lines=("abcd ef01",),
            ),
        )

        payload = context.to_template_dict()

        self.assertEqual(
            sorted(payload.keys()),
            sorted(
                [
                    "created_timestamp_utc",
                    "doc",
                    "doc_id",
                    "fallback",
                    "instructions",
                    "margin_mm",
                    "page_height_mm",
                    "page_size_css",
                    "page_width_mm",
                    "pages",
                    "recovery",
                    "usable_width_mm",
                ]
            ),
        )
        self.assertEqual(payload["doc"]["title"], "Recovery Document")
        self.assertEqual(payload["instructions"]["lines"], ["A", "B"])
        self.assertEqual(payload["recovery"]["quorum_value"], "2 of 3")
        self.assertEqual(payload["recovery"]["signing_pub_lines"], ["abcd ef01"])
        self.assertEqual(payload["pages"][0]["qr_items"][0]["index"], 1)
        self.assertEqual(payload["pages"][0]["fallback_blocks"][0]["line_offset"], 0)
        self.assertEqual(payload["pages"][0]["sequence"]["labels"][0]["text"], "1")


if __name__ == "__main__":
    unittest.main()
