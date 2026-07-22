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

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

from ethernity.cli.shared.shard_rendering import render_shard_document
from ethernity.crypto.sharding import ShardPayload
from ethernity.encoding.framing import FrameType
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_RAW
from ethernity.render.types import RenderLineage


class TestShardRendering(unittest.TestCase):
    @mock.patch("ethernity.cli.shared.shard_rendering.validate_rendered_pdf_artifact")
    @mock.patch("ethernity.cli.shared.shard_rendering.render_module.render_frames_to_pdf")
    @mock.patch(
        "ethernity.cli.shared.shard_rendering.sharding_module.encode_shard_payload",
        return_value=b"encoded-shard",
    )
    def test_render_shard_document_builds_and_validates_owned_artifact(
        self,
        _encode_shard_payload: mock.MagicMock,
        render_frames_to_pdf: mock.MagicMock,
        validate_artifact: mock.MagicMock,
    ) -> None:
        shard = cast(
            ShardPayload,
            SimpleNamespace(share_index=1, share_count=3, threshold=2),
        )
        render_service = mock.MagicMock()
        render_inputs = mock.sentinel.render_inputs
        render_result = mock.sentinel.render_result
        render_service.shard_inputs.return_value = render_inputs
        render_service.build_qr_payloads.return_value = ("qr-payload",)
        render_frames_to_pdf.return_value = render_result
        doc_id = b"\x11" * 16

        output_path = render_shard_document(
            shard,
            doc_id=doc_id,
            output_dir="/tmp/output",
            render_service=render_service,
            filename_prefix="shard",
            layout_debug_json_path="/tmp/debug/shard.layout.json",
            qr_payload_codec=QR_PAYLOAD_CODEC_RAW,
            lineage=RenderLineage(kind="minted_shard_set"),
        )

        self.assertEqual(
            output_path,
            str(Path(f"/tmp/output/shard-{doc_id.hex()}-1-of-3.pdf")),
        )
        shard_frame = render_service.shard_inputs.call_args.args[0]
        self.assertEqual(shard_frame.frame_type, FrameType.KEY_DOCUMENT)
        self.assertEqual(shard_frame.doc_id, doc_id)
        self.assertEqual(shard_frame.data, b"encoded-shard")
        self.assertEqual(
            render_service.shard_inputs.call_args.kwargs["layout_debug_json_path"],
            "/tmp/debug/shard.layout.json",
        )
        validate_artifact.assert_called_once_with(
            inputs=render_inputs,
            result=render_result,
            artifact_label="rendered shard artifact",
        )


if __name__ == "__main__":
    unittest.main()
