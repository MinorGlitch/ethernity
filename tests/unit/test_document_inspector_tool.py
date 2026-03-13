from __future__ import annotations

import json
import unittest
from pathlib import Path

import tooling.document_inspector as inspector

_REPO_ROOT = Path(__file__).resolve().parents[2]
_V1_0_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64"
_V1_1_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_1" / "golden" / "base64"
_V1_0_PASSPHRASE = "stable-v1-baseline-passphrase"
_V1_1_PASSPHRASE = "stable-v1_1-golden-passphrase"


def _backup_shards(scenario_root: Path) -> list[Path]:
    return sorted((scenario_root / "backup").glob("shard-*.pdf"))


class TestDocumentInspectorTool(unittest.TestCase):
    def test_inspect_main_payloads_exposes_round_trip_views(self) -> None:
        payload_text = (_V1_0_FIXTURES_ROOT / "file_no_shard" / "main_payloads.txt").read_text(
            encoding="utf-8"
        )

        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=_V1_0_PASSPHRASE,
            source_label="fixture main payloads",
        )

        self.assertEqual(result.input_mode, inspector.MODE_PAYLOADS)
        self.assertEqual(result.parsed_frame_count, 3)
        self.assertIn("MAIN FRAME", result.combined_fallback_text)
        self.assertIn("AUTH FRAME", result.combined_fallback_text)
        self.assertIsNotNone(result.manifest_json_text)
        self.assertEqual(len(result.files), 1)
        self.assertIn("format_version", result.manifest_json_text or "")

    def test_inspect_shard_payloads_recovers_passphrase(self) -> None:
        payload_text = (
            _V1_1_FIXTURES_ROOT / "sharded_embedded" / "shard_payloads_threshold.txt"
        ).read_text(encoding="utf-8")

        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=None,
            source_label="fixture shard payloads",
        )

        self.assertEqual(result.parsed_frame_count, 2)
        self.assertEqual(len(result.recovered_secrets), 1)
        secret = result.recovered_secrets[0]
        self.assertEqual(secret.label, "passphrase")
        self.assertEqual(secret.status, "recoverable")
        self.assertIn(_V1_1_PASSPHRASE, secret.detail_text)

    def test_collect_scan_files_recurses_directory(self) -> None:
        files = inspector._collect_scan_files([_V1_0_FIXTURES_ROOT / "file_no_shard" / "backup"])

        self.assertGreaterEqual(len(files), 2)
        self.assertTrue(any(path.name == "qr_document.pdf" for path in files))
        self.assertTrue(all(path.suffix.lower() == ".pdf" for path in files))

    def test_payload_text_from_scan_paths_decodes_fixture_pdf(self) -> None:
        payload_text, warnings = inspector._payload_text_from_scan_paths(
            [_V1_0_FIXTURES_ROOT / "file_no_shard" / "backup" / "qr_document.pdf"]
        )

        self.assertEqual(warnings, [])
        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=_V1_0_PASSPHRASE,
            source_label="fixture qr document",
        )
        self.assertEqual(result.parsed_frame_count, 3)

    def test_payload_text_from_multiple_shard_pdfs_reaches_quorum(self) -> None:
        scenario_root = _V1_1_FIXTURES_ROOT / "sharded_embedded"
        shard_paths = _backup_shards(scenario_root)
        payload_text, warnings = inspector._payload_text_from_scan_paths(shard_paths[:2])

        self.assertEqual(warnings, [])
        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=None,
            source_label="fixture shard pdfs",
        )

        self.assertEqual(result.parsed_frame_count, 2)
        self.assertEqual(len(result.recovered_secrets), 1)
        self.assertEqual(result.recovered_secrets[0].status, "recoverable")

    def test_combined_backup_and_shards_auto_decrypts_from_recovered_passphrase(self) -> None:
        scenario_root = _V1_1_FIXTURES_ROOT / "sharded_embedded"
        shard_paths = _backup_shards(scenario_root)
        payload_text, warnings = inspector._payload_text_from_scan_paths(
            [scenario_root / "backup" / "qr_document.pdf", *shard_paths[:2]]
        )

        self.assertEqual(warnings, [])
        result = inspector.inspect_pasted_text(
            payload_text,
            selected_mode=inspector.MODE_AUTO,
            passphrase=None,
            source_label="fixture backup plus shards",
        )

        self.assertIsNotNone(result.manifest_json_text)
        self.assertGreaterEqual(len(result.files), 1)
        self.assertIn("Decrypted via: recovered passphrase shards", result.summary_text)

    def test_build_batch_report_includes_success_and_error_entries(self) -> None:
        entries = [
            inspector.BatchReportEntry(
                source_label="good",
                source_path="/tmp/good.pdf",
                frame_count=3,
                doc_ids=("abcd",),
                frame_types=("AUTH", "MAIN_DOCUMENT"),
                warnings=("warn-1",),
                error=None,
            ),
            inspector.BatchReportEntry(
                source_label="bad",
                source_path="/tmp/bad.pdf",
                frame_count=0,
                doc_ids=(),
                frame_types=(),
                warnings=(),
                error="scan failed",
            ),
        ]

        text, json_text = inspector.build_batch_report(entries)
        decoded = json.loads(json_text)

        self.assertIn("/tmp/good.pdf", text)
        self.assertIn("ERROR - scan failed", text)
        self.assertEqual(len(decoded["entries"]), 2)


if __name__ == "__main__":
    unittest.main()
