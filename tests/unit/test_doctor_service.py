from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity.artifacts.publish import (
    PublicationTransaction,
    snapshot_artifact_dir,
    write_transaction_metadata,
)
from ethernity.cli.features.doctor.service import reconcile_publication_transactions
from ethernity.workflows.extension.planning import (
    ValidatedAppendAuthority,
    ValidatedChainLineage,
    ValidatedExtensionIdentity,
)


class TestDoctorService(unittest.TestCase):
    def test_inspect_validates_committed_transaction_against_authenticated_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            final_dir = root / "extensions" / "01"
            final_dir.mkdir(parents=True)
            self._write_extension_artifacts(final_dir)
            transaction = PublicationTransaction(
                root_hash="11" * 32,
                expected_parent_hash="11" * 32,
                new_index=1,
                new_hash="33" * 32,
            )
            write_transaction_metadata(
                final_dir,
                transaction,
                snapshot=snapshot_artifact_dir(final_dir),
            )

            with mock.patch(
                "ethernity.cli.features.doctor.service._authenticated_state",
                return_value=self._state(
                    head_index=1, head_hash=transaction.new_hash, next_index=2
                ),
            ):
                result = reconcile_publication_transactions(
                    root,
                    passphrase="secret",
                    repair=False,
                )

            self.assertEqual(result.transactions[0].status, "authenticated committed")
            self.assertEqual(result.transactions[0].action, "none")

    def test_repair_refuses_unjournaled_staging_with_unknown_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            staging = root / "extensions" / ".staging-1-interrupted"
            staging.mkdir(parents=True)
            (staging / "partial.pdf").write_bytes(b"partial")

            with mock.patch(
                "ethernity.cli.features.doctor.service._authenticated_state",
                return_value=self._state(),
            ):
                with self.assertRaisesRegex(ValueError, "may still be active"):
                    reconcile_publication_transactions(
                        root,
                        passphrase="secret",
                        repair=True,
                    )

            self.assertTrue(staging.exists())

    def test_repair_replaces_empty_legacy_lock_directory_with_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_lock = root / "extensions" / ".chain.lock"
            legacy_lock.mkdir(parents=True)

            with mock.patch(
                "ethernity.cli.features.doctor.service._authenticated_state",
                return_value=self._state(),
            ):
                result = reconcile_publication_transactions(
                    root,
                    passphrase="secret",
                    repair=True,
                )

            self.assertTrue(legacy_lock.is_file())
            self.assertEqual(result.transactions[0].status, "obsolete directory lock")
            self.assertEqual(
                result.transactions[0].action,
                "replaced legacy lock directory with persistent lock file",
            )

    def test_repair_quarantines_journaled_staging_instead_of_resuming(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "backup"
            root.mkdir()
            staging = root / "extensions" / ".staging-1-doctor"
            staging.mkdir(parents=True)
            self._write_extension_artifacts(staging)
            transaction = self._transaction()
            write_transaction_metadata(
                staging,
                transaction,
                snapshot=snapshot_artifact_dir(staging),
            )
            state = self._state()

            with (
                mock.patch(
                    "ethernity.cli.features.doctor.service._authenticated_state",
                    return_value=state,
                ),
                mock.patch(
                    "ethernity.cli.features.doctor.service._authenticate_staged_extension"
                ) as authenticate,
            ):
                result = reconcile_publication_transactions(
                    root,
                    passphrase="secret",
                    repair=True,
                )

            final_dir = root / "extensions" / "01"
            quarantine = root.parent / f".{root.name}.ethernity-doctor-quarantine" / staging.name
            self.assertFalse(final_dir.exists())
            self.assertFalse(staging.exists())
            self.assertTrue(quarantine.exists())
            self.assertEqual(
                result.transactions[0].status,
                "journaled staging quarantined; publication not resumed",
            )
            self.assertEqual(result.transactions[0].path, quarantine)
            self.assertEqual(authenticate.call_count, 2)

    def test_repair_removes_duplicate_staging_after_authenticated_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extensions = root / "extensions"
            staging = extensions / ".staging-1-doctor"
            final_dir = extensions / "01"
            staging.mkdir(parents=True)
            final_dir.mkdir()
            self._write_extension_artifacts(staging)
            transaction = self._transaction()
            write_transaction_metadata(
                staging,
                transaction,
                snapshot=snapshot_artifact_dir(staging),
            )
            state = self._state(head_index=1, head_hash=transaction.new_hash, next_index=2)

            with (
                mock.patch(
                    "ethernity.cli.features.doctor.service._authenticated_state",
                    return_value=state,
                ),
                mock.patch(
                    "ethernity.cli.features.doctor.service._authenticate_staged_extension"
                ) as authenticate,
            ):
                result = reconcile_publication_transactions(
                    root,
                    passphrase="secret",
                    repair=True,
                )

            self.assertFalse(staging.exists())
            self.assertTrue(final_dir.exists())
            self.assertEqual(result.transactions[0].status, "already committed")
            self.assertEqual(
                result.transactions[0].action,
                "removed duplicate staging directory",
            )
            authenticate.assert_called_once()

    def test_repair_removes_duplicate_for_an_authenticated_non_head_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            extensions = root / "extensions"
            staging = extensions / ".staging-1-doctor"
            (extensions / "01").mkdir(parents=True)
            (extensions / "02").mkdir()
            staging.mkdir()
            self._write_extension_artifacts(staging)
            transaction = self._transaction()
            write_transaction_metadata(
                staging,
                transaction,
                snapshot=snapshot_artifact_dir(staging),
            )
            state = self._state(
                head_index=2,
                head_hash="55" * 32,
                next_index=3,
                extension_hashes=(transaction.new_hash, "55" * 32),
            )

            with (
                mock.patch(
                    "ethernity.cli.features.doctor.service._authenticated_state",
                    return_value=state,
                ),
                mock.patch(
                    "ethernity.cli.features.doctor.service._authenticate_staged_extension"
                ) as authenticate,
            ):
                result = reconcile_publication_transactions(
                    root,
                    passphrase="secret",
                    repair=True,
                )

            self.assertFalse(staging.exists())
            self.assertEqual(result.transactions[0].status, "already committed")
            authenticate.assert_called_once()

    def test_doctor_rejects_mutated_staging_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            staging = root / "extensions" / ".staging-1-doctor"
            staging.mkdir(parents=True)
            self._write_extension_artifacts(staging)
            write_transaction_metadata(
                staging,
                self._transaction(),
                snapshot=snapshot_artifact_dir(staging),
            )
            (staging / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"changed")

            with mock.patch(
                "ethernity.cli.features.doctor.service._authenticated_state",
                return_value=self._state(),
            ):
                with self.assertRaisesRegex(ValueError, "do not match transaction snapshot"):
                    reconcile_publication_transactions(
                        root,
                        passphrase="secret",
                        repair=True,
                    )

            self.assertTrue(staging.exists())

    @staticmethod
    def _transaction() -> PublicationTransaction:
        return PublicationTransaction(
            root_hash="11" * 32,
            expected_parent_hash="22" * 32,
            new_index=1,
            new_hash="33" * 32,
        )

    @staticmethod
    def _state(
        *,
        head_index: int = 0,
        head_hash: str = "22" * 32,
        next_index: int = 1,
        extension_hashes: tuple[str, ...] | None = None,
    ) -> SimpleNamespace:
        del next_index
        hashes = extension_hashes
        if hashes is None:
            hashes = (head_hash,) if head_index > 0 else ()
        return SimpleNamespace(
            resolved_passphrase="secret",
            issues=(),
            authority=ValidatedAppendAuthority(
                signing_seed=b"\x44" * 32,
                source="embedded_seed",
            ),
            lineage=ValidatedChainLineage(
                root_doc_id="deadbeefcafebabe",
                root_doc_hash=b"\x11" * 32,
                chain_id=b"\x66" * 32,
                head_index=head_index,
                head_doc_hash=bytes.fromhex(head_hash),
                ancestry_valid=True,
                head_auth_status="verified",
                head_root_authority_verified=True,
                extensions=tuple(
                    ValidatedExtensionIdentity(index=index, doc_hash=bytes.fromhex(doc_hash))
                    for index, doc_hash in enumerate(hashes, start=1)
                ),
            ),
        )

    @staticmethod
    def _write_extension_artifacts(staging: Path) -> None:
        for name in (
            "qr_document-01-deadbeefcafebabe.pdf",
            "recovery_document-01-deadbeefcafebabe.pdf",
            "recovery_kit-01-deadbeefcafebabe.pdf",
        ):
            (staging / name).write_bytes(name.encode("ascii"))


if __name__ == "__main__":
    unittest.main()
