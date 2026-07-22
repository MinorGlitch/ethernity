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

import hashlib
import io
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fpdf import FPDF

from ethernity.cli.features.extension_reporting import CliExtensionReporter
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL
from ethernity.cli.shared.input_scope import InputScopeDiff
from ethernity.cli.shared.ndjson import ndjson_session
from ethernity.cli.shared.types import InputFile
from ethernity.config import ExtendDefaults
from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.sharding import ShardPayload, encode_shard_payload
from ethernity.crypto.signing import AuthPayload, derive_public_key
from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.extensions.chain import (
    _VALIDATED_CHAIN_STATE_SEAL,
    LogicalFileState,
    ValidatedChainState,
    build_chain_available_chunks,
)
from ethernity.extensions.recovery import ImportedRecoveryDocument
from ethernity.extensions.staging import (
    ExtensionPublishPolicy,
    create_staged_extension_artifact_plan as _create_staged_extension_artifact_plan,
)
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.render.proofs import RenderProofError, build_render_artifact_proof
from ethernity.render.types import RenderFallbackProof, RenderInputs, RenderResult
from ethernity.workflows.extension import execution as extend_execution
from ethernity.workflows.extension.errors import ExtensionIssue, ExtensionWorkflowError
from ethernity.workflows.extension.main_carrier_validation import (
    expected_recovery_kit_index_component_ids,
    validate_single_main_carrier as _validate_single_main_carrier,
    validate_single_recovery_document_carrier as _validate_single_recovery_document_carrier,
    validate_staged_main_carrier as _validate_staged_main_carrier,
    validate_staged_recovery_kit_index_document as _validate_staged_recovery_kit_index_document,
)
from ethernity.workflows.extension.models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    RenderedExtensionArtifacts,
    ReuseRootPassphraseShards,
    SigningKeyNotStored,
)
from ethernity.workflows.extension.planning import (
    ExtendInspection,
    ResolvedExtendState,
    ResolvedExtensionPlan,
    ValidatedAppendAuthority,
    ValidatedChainLineage,
)
from ethernity.workflows.extension.published_recovery_validation import (
    validate_published_recovery_document_carrier as _validate_published_recovery_document_carrier,
)
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.runtime import (
    ensure_extend_layout_debug_dir_allowed,
    resolve_extend_layout_debug_dir,
    resolve_extend_policy,
)
from ethernity.workflows.extension.scope import SelectedExtendScope
from ethernity.workflows.extension.service import (
    EXTENSION_INPUT_REQUIRED,
    EXTENSION_INVALID_POLICY,
    EXTENSION_MAIN_CARRIER_INVALID,
    EXTENSION_NO_CHANGES,
    EXTENSION_SHARD_CARRIER_INVALID,
    assemble_prepared_extension_document,
    encrypt_prepared_extension_document,
    execute_prepared_extend,
    execute_staged_extension_publish,
    prepare_extend_run,
    prepare_extend_run_from_state,
    prepare_staged_extension_publish,
    resolve_extend_runtime,
    run_extend,
    validate_prepared_extend_render,
)
from ethernity.workflows.extension.shard_validation import (
    validate_rendered_shard_carrier as _validate_rendered_shard_carrier,
)
from ethernity.workflows.recovery.frame_inputs import FrameInputResult


def _inspection(
    *,
    diff_summary: dict[str, object] | None,
    blocking_issues: tuple[dict[str, object], ...] = (),
) -> ExtendInspection:
    return ExtendInspection(
        doc_id="deadbeef",
        root_dir="/tmp/root",
        input_label="Backup root directory",
        input_detail="/tmp/root",
        input_kind="standalone_root",
        source_summary=None,
        frame_counts={"main": 0, "auth": 0, "shard": 0},
        root_doc_id="deadbeef",
        root_doc_hash="cafebabe",
        chain_id="feedface",
        auth_status="verified",
        unlock={
            "mode": "passphrase",
            "passphrase_provided": True,
            "validated_shard_count": 0,
            "required_shard_threshold": None,
            "shard_share_count": None,
            "satisfied": True,
        },
        discovered_extension_dirs=(),
        validated_head_index=0,
        validated_head_doc_hash="cafebabe",
        available_extensions=(),
        validated_head_auth_status=None,
        validated_head_root_authority_verified=None,
        ancestry_valid=True,
        signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
        selected_scope={"files": ["/tmp/root/example.txt"], "directories": [], "base_dir": "/tmp"},
        diff_summary=diff_summary,
        blocking_issues=tuple(ExtensionIssue.from_mapping(issue) for issue in blocking_issues),
    )


def _published_recovery_document() -> ImportedRecoveryDocument:
    ciphertext = b"published extension ciphertext"
    doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    auth_frame = Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=b"auth",
    )
    return ImportedRecoveryDocument.from_ciphertext(
        ciphertext=ciphertext,
        auth_frames=(auth_frame,),
        source_label="published recovery test",
    )


def _resolved_state(
    *,
    diff_summary: dict[str, object] | None,
    blocking_issues: tuple[dict[str, object], ...] = (),
    root_passphrase_shard_threshold: int | None = None,
    root_passphrase_shard_count: int = 0,
    input_files: tuple[InputFile, ...] | None = None,
    current_state: tuple[LogicalFileState, ...] = (),
    available_chunks: tuple[tuple[bytes, bytes], ...] = (),
    chain_document_count: int = 1,
    chain_ciphertext_bytes: int = 0,
    chain_decoded_chunk_bytes: int = 0,
) -> ResolvedExtendState:
    chunking = ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=64 * 1024,
        min_size=16 * 1024,
        max_size=256 * 1024,
    )
    trusted_chunks = build_chain_available_chunks(current_state, chunking)
    trusted_chunks.update(dict(available_chunks))
    validated_chain_state = object.__new__(ValidatedChainState)
    object.__setattr__(validated_chain_state, "root_doc_hash", b"\x22" * 32)
    object.__setattr__(validated_chain_state, "head_doc_hash", b"\x11" * 32)
    object.__setattr__(validated_chain_state, "head_index", 1)
    object.__setattr__(validated_chain_state, "chunking", chunking)
    object.__setattr__(validated_chain_state, "logical_state", current_state)
    object.__setattr__(
        validated_chain_state,
        "available_chunks",
        tuple(sorted(trusted_chunks.items())),
    )
    object.__setattr__(validated_chain_state, "_seal", _VALIDATED_CHAIN_STATE_SEAL)
    scope = SelectedExtendScope(
        raw_files=("/tmp/root/example.txt",),
        raw_directories=(),
        base_dir_arg="/tmp/root",
        input_files=input_files
        or (
            InputFile(
                source_path=None,
                relative_path="updated.txt",
                data=b"updated",
                mtime=1,
            ),
            InputFile(
                source_path=None,
                relative_path="new.txt",
                data=b"new",
                mtime=2,
            ),
        ),
        base_dir=None,
        input_origin="file",
        input_roots=(),
        exact_paths=("updated.txt", "new.txt"),
        directory_prefixes=(),
    )
    issues = tuple(ExtensionIssue.from_mapping(issue) for issue in blocking_issues)
    diff = (
        None
        if diff_summary is None
        else InputScopeDiff(
            new_paths=tuple(diff_summary.get("new_paths", ())),
            changed_paths=tuple(diff_summary.get("changed_paths", ())),
            unchanged_paths=tuple(diff_summary.get("unchanged_paths", ())),
            missing_paths=tuple(diff_summary.get("missing_paths", ())),
        )
    )
    lineage = ValidatedChainLineage(
        root_doc_id="deadbeef",
        root_doc_hash=b"\x22" * 32,
        chain_id=b"\x44" * 32,
        head_index=1,
        head_doc_hash=b"\x11" * 32,
        ancestry_valid=True,
        head_auth_status="verified",
        head_root_authority_verified=True,
        extensions=(),
    )
    authority = ValidatedAppendAuthority(signing_seed=b"\x33" * 32, source="embedded_seed")
    plan = (
        ResolvedExtensionPlan(diff=diff, lineage=lineage, authority=authority, issues=issues)
        if diff is not None
        else None
    )
    return ResolvedExtendState(
        inspection=_inspection(diff_summary=diff_summary, blocking_issues=blocking_issues),
        plan=plan,
        diff=diff,
        lineage=lineage,
        authority=authority,
        issues=issues,
        loaded_scope=scope,
        current_state=current_state,
        validated_chain_state=validated_chain_state,
        chain_document_count=chain_document_count,
        chain_ciphertext_bytes=chain_ciphertext_bytes,
        chain_decoded_chunk_bytes=chain_decoded_chunk_bytes,
        resolved_passphrase="secret",
        root_doc_hash=b"\x22" * 32,
        parent_doc_hash=b"\x11" * 32,
        next_index=2,
        signing_seed=b"\x33" * 32,
        chunking=chunking,
        root_passphrase_shard_threshold=root_passphrase_shard_threshold,
        root_passphrase_shard_count=root_passphrase_shard_count,
    )


def _shard_payload(
    *,
    share_index: int,
    threshold: int,
    share_count: int,
    key_type: str,
    doc_hash: bytes = b"\x22" * 32,
    sign_pub: bytes = b"\x44" * 32,
) -> ShardPayload:
    return ShardPayload(
        share_index=share_index,
        threshold=threshold,
        share_count=share_count,
        key_type=key_type,
        share=bytes([share_index]) * 16,
        secret_len=8,
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=b"\x55" * 64,
        shard_set_id=b"\x66" * 16,
    )


def _render_result_for_inputs(inputs: RenderInputs) -> RenderResult:
    sections = tuple(inputs.fallback_sections or ())
    fallback_proof = None
    if sections:
        fallback_proof = RenderFallbackProof(
            section_frame_digests=tuple(
                hashlib.sha256(encode_frame(section.frame)).hexdigest() for section in sections
            ),
            section_titles=tuple(
                section.label.strip()
                for section in sections
                if isinstance(section.label, str) and section.label.strip()
            ),
            expected_section_count=len(sections),
            emitted_block_count=len(sections),
            emitted_line_count=len(sections),
            consumed_section_count=len(sections),
            fully_consumed=True,
            emitted_fallback_lines=tuple(
                section.label.strip()
                for section in sections
                if isinstance(section.label, str) and section.label.strip()
            ),
        )
    qr_payload_count = len(inputs.qr_payloads or inputs.frames)
    physical_qr_payload_indexes = tuple(range(qr_payload_count)) if inputs.render_qr else ()
    return RenderResult(
        artifact_proof=build_render_artifact_proof(
            inputs,
            encoded_payload_count=qr_payload_count,
            physical_qr_count=len(physical_qr_payload_indexes),
            physical_qr_payload_indexes=physical_qr_payload_indexes,
            page_count=1,
            fallback_proof=fallback_proof,
        ),
        fallback_proof=fallback_proof,
    )


def _kit_index_pdf_lines(inputs: RenderInputs) -> list[str]:
    lines = ["Recovery Kit Index"]
    rows = inputs.context.get("inventory_rows")
    if not isinstance(rows, list):
        return lines
    for row in rows:
        if isinstance(row, dict):
            lines.append(str(row.get("component_id", "")))
            lines.append(str(row.get("detail", "")))
    return lines


def _config_with_no_shard_defaults(path: Path) -> Path:
    path.write_text('[defaults.backup]\nqr_payload_codec = "raw"\n', encoding="utf-8")
    return path


def _config_with_reuse_root_default(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                "[defaults.backup]",
                'qr_payload_codec = "raw"',
                "[defaults.extend]",
                'unlock_policy = "reuse-root"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


class TestExtendService(unittest.TestCase):
    def test_prepare_extend_run_requires_explicit_scope(self) -> None:
        with self.assertRaises(ExtensionWorkflowError) as ctx:
            prepare_extend_run(ExtensionRequest(publish_root="/tmp/root"))
        self.assertEqual(ctx.exception.code, EXTENSION_INPUT_REQUIRED)

    def test_prepare_extend_run_surfaces_first_blocking_issue(self) -> None:
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary=None,
                blocking_issues=(
                    {
                        "code": "SEALED_ROOT_NOT_EXTENDABLE",
                        "message": "sealed roots are terminal in v1 and cannot be extended",
                        "details": {},
                    },
                ),
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                prepare_extend_run(
                    ExtensionRequest(
                        publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]
                    )
                )
        self.assertEqual(ctx.exception.code, "SEALED_ROOT_NOT_EXTENDABLE")

    def test_prepare_extend_run_preserves_recovery_head_untrusted_details(self) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required MAIN documents",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 1,
            "validated_head_doc_hash": "aa" * 32,
            "validated_head_auth_status": "verified",
            "validated_head_root_authority_verified": True,
            "explicit_selection": False,
        }

        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary=None,
                blocking_issues=(
                    {
                        "code": "RECOVERY_HEAD_UNTRUSTED",
                        "message": (
                            "latest supplied recovery head could not be trusted: "
                            "missing required MAIN documents"
                        ),
                        "details": trust_details,
                    },
                ),
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                prepare_extend_run(
                    ExtensionRequest(
                        publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]
                    )
                )

        self.assertEqual(ctx.exception.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(
            str(ctx.exception),
            "latest supplied recovery head could not be trusted: missing required MAIN documents",
        )
        self.assertEqual(ctx.exception.details, trust_details)

    def test_prepare_extend_run_rejects_noop_diffs(self) -> None:
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary={
                    "new_paths": [],
                    "changed_paths": [],
                    "unchanged_paths": ["example.txt"],
                    "missing_paths": [],
                },
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                prepare_extend_run(
                    ExtensionRequest(
                        publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]
                    )
                )
        self.assertEqual(ctx.exception.code, EXTENSION_NO_CHANGES)

    def test_prepare_extend_run_consumes_typed_diff_without_presentation_keys(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": [],
                "unchanged_paths": ["same.txt"],
                "missing_paths": [],
            },
        )

        prepared = prepare_extend_run_from_state(
            ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]),
            resolved,
        )

        self.assertIs(prepared.plan, resolved.plan)
        self.assertEqual(prepared.new_paths, ("new.txt",))
        self.assertEqual(prepared.unchanged_paths, ("same.txt",))

    def test_prepare_extend_run_from_state_rejects_missing_paths_without_planning_issue(
        self,
    ) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": [],
                "unchanged_paths": [],
                "missing_paths": ["removed.txt"],
            },
        )

        with self.assertRaises(ExtensionWorkflowError) as ctx:
            prepare_extend_run_from_state(
                ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]),
                resolved,
            )

        self.assertEqual(ctx.exception.code, "DELETE_NOT_SUPPORTED")
        self.assertEqual(ctx.exception.details, {"missing_paths": ["removed.txt"]})

    def test_prepare_extend_run_ignores_mutated_presentation_metadata(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": [],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        resolved = replace(
            resolved,
            inspection=replace(
                resolved.inspection,
                root_doc_id=None,
                chain_id=None,
                selected_scope=None,
            ),
        )

        prepared = prepare_extend_run_from_state(
            ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]),
            resolved,
        )

        self.assertEqual(prepared.plan.lineage.root_doc_id, "deadbeef")
        self.assertEqual(prepared.changed_paths, ("updated.txt",))

    def test_prepare_extend_run_returns_changed_and_new_paths(self) -> None:
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=_resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": ["same.txt"],
                    "missing_paths": [],
                },
            ),
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"])
            )

        self.assertEqual(prepared.next_index, 2)
        self.assertEqual(prepared.new_paths, ("new.txt",))
        self.assertEqual(prepared.changed_paths, ("updated.txt",))
        self.assertEqual(prepared.unchanged_paths, ("same.txt",))

    def test_resolve_extend_policy_applies_extend_defaults_for_self_contained(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=None,
            root_passphrase_shard_count=0,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ExtensionPassphraseShards(threshold=2, share_count=3),
        )
        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )
        self.assertTrue(policy.require_recovery_kit_index)
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 3)
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 3)

    def test_resolve_extend_policy_uses_not_stored_signing_key_mode(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(signing_key_mode="not-stored"),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=None,
            root_passphrase_shard_count=0,
            require_recovery_kit_index=False,
        )

        self.assertEqual(policy.signing_key, SigningKeyNotStored())
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 0)

    def test_resolve_extend_policy_treats_explicit_signing_key_shards_as_sharded(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="not-stored",
            ),
            root_passphrase_shard_threshold=None,
            root_passphrase_shard_count=0,
            require_recovery_kit_index=False,
        )

        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 3)

    def test_resolve_extend_policy_rejects_not_stored_with_signing_key_shards(self) -> None:
        with self.assertRaises(ExtensionWorkflowError) as ctx:
            resolve_extend_policy(
                args=ExtensionRequest(
                    signing_key_mode="not-stored",
                    signing_key_shard_threshold=2,
                    signing_key_shard_count=3,
                ),
                defaults=ExtendDefaults(shard_threshold=2, shard_count=3),
                root_passphrase_shard_threshold=None,
                root_passphrase_shard_count=0,
                require_recovery_kit_index=False,
            )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("signing authority shard options require", str(ctx.exception))

    def test_resolve_extend_policy_rejects_unknown_signing_key_mode(self) -> None:
        with self.assertRaises(ExtensionWorkflowError) as ctx:
            resolve_extend_policy(
                args=ExtensionRequest(signing_key_mode="embedded"),  # type: ignore[arg-type]
                defaults=ExtendDefaults(
                    shard_threshold=2,
                    shard_count=3,
                    signing_key_mode="sharded",
                    signing_key_shard_threshold=2,
                    signing_key_shard_count=3,
                ),
                root_passphrase_shard_threshold=None,
                root_passphrase_shard_count=0,
                require_recovery_kit_index=False,
            )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("signing_key_mode", str(ctx.exception))

    def test_resolve_extend_policy_rejects_shard_counts_above_shamir_limit(self) -> None:
        for args in (
            ExtensionRequest(shard_threshold=1, shard_count=256),
            ExtensionRequest(
                signing_key_mode="sharded",
                signing_key_shard_threshold=1,
                signing_key_shard_count=256,
            ),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    resolve_extend_policy(
                        args=args,
                        defaults=ExtendDefaults(shard_threshold=2, shard_count=3),
                        root_passphrase_shard_threshold=None,
                        root_passphrase_shard_count=0,
                        require_recovery_kit_index=False,
                    )

                self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
                self.assertIn("must be <= 255", str(ctx.exception))

    def test_resolve_extend_policy_rejects_self_contained_without_shards(self) -> None:
        with self.assertRaises(ExtensionWorkflowError) as ctx:
            resolve_extend_policy(
                args=ExtensionRequest(),
                defaults=ExtendDefaults(shard_threshold=0, shard_count=0),
                root_passphrase_shard_threshold=None,
                root_passphrase_shard_count=0,
                require_recovery_kit_index=False,
            )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("self-contained requires extension passphrase shards", str(ctx.exception))
        self.assertIn("--unlock-policy reuse-root", str(ctx.exception))

    def test_resolve_extend_policy_rejects_explicit_zero_for_self_contained(self) -> None:
        with self.assertRaises(ExtensionWorkflowError) as ctx:
            resolve_extend_policy(
                args=ExtensionRequest(shard_count=0),
                defaults=ExtendDefaults(shard_threshold=2, shard_count=3),
                root_passphrase_shard_threshold=None,
                root_passphrase_shard_count=0,
                require_recovery_kit_index=False,
            )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("self-contained requires extension passphrase shards", str(ctx.exception))

    def test_resolve_extend_policy_allows_explicit_zero_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(unlock_policy="reuse-root", shard_count=0),
            defaults=ExtendDefaults(shard_threshold=2, shard_count=3),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=3,
            require_recovery_kit_index=False,
        )

        self.assertEqual(policy.passphrase, ReuseRootPassphraseShards(threshold=2, share_count=3))
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 0)

    def test_extend_layout_debug_dir_rejects_extension_inventory_paths(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = root_dir / "extensions" / "01"

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                ensure_extend_layout_debug_dir_allowed(debug_dir, root_dir=str(root_dir))

            self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
            self.assertIn("must not be inside", str(ctx.exception))
            self.assertFalse(debug_dir.exists())

    def test_extend_layout_debug_dir_rejects_scan_publish_root_paths(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = root_dir / "layout-debug"

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                ensure_extend_layout_debug_dir_allowed(
                    debug_dir,
                    root_dir=str(root_dir),
                    scan=True,
                )

            self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
            self.assertIn("managed extension publish paths", str(ctx.exception))
            self.assertEqual(ctx.exception.details["scan"], True)
            self.assertFalse(debug_dir.exists())

    def test_extend_layout_debug_dir_resolves_outside_extension_inventory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = Path(tmpdir) / "layout-debug"

            resolved = resolve_extend_layout_debug_dir(str(debug_dir), root_dir=str(root_dir))

            self.assertEqual(resolved, str(debug_dir.resolve()))
            self.assertTrue(debug_dir.is_dir())

    def test_extend_layout_debug_dir_can_validate_without_creating_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = Path(tmpdir) / "layout-debug"

            resolved = resolve_extend_layout_debug_dir(
                str(debug_dir),
                root_dir=str(root_dir),
                create=False,
            )

            self.assertEqual(resolved, str(debug_dir.resolve()))
            self.assertFalse(debug_dir.exists())

    def test_extend_layout_debug_dir_create_false_rejects_non_directory_parent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            parent_file = Path(tmpdir) / "not-a-dir"
            parent_file.write_text("nope", encoding="utf-8")

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                resolve_extend_layout_debug_dir(
                    str(parent_file / "layout-debug"),
                    root_dir=str(root_dir),
                    create=False,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("--layout-debug-dir is not usable", str(ctx.exception))

    def test_resolve_extend_policy_uses_validated_unlock_policy_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(unlock_policy="reuse-root"),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=2,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ReuseRootPassphraseShards(threshold=2, share_count=2),
        )
        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 0)
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 3)
        self.assertTrue(policy.require_recovery_kit_index)

    def test_resolve_extend_policy_uses_defaulted_unlock_policy_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(),
            defaults=ExtendDefaults(
                unlock_policy="reuse-root",
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=2,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ReuseRootPassphraseShards(threshold=2, share_count=2),
        )
        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 0)
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 3)
        self.assertTrue(policy.require_recovery_kit_index)

    def test_resolve_extend_policy_allows_explicit_not_stored_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(unlock_policy="reuse-root", signing_key_mode="not-stored"),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=2,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ReuseRootPassphraseShards(threshold=2, share_count=2),
        )
        self.assertEqual(policy.signing_key, SigningKeyNotStored())
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 0)

    def test_resolve_extend_policy_allows_sharded_signing_key_mode_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(unlock_policy="reuse-root", signing_key_mode="sharded"),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=2,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.passphrase,
            ReuseRootPassphraseShards(threshold=2, share_count=2),
        )
        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )
        self.assertEqual(policy.to_publish_policy().passphrase_shard_count, 0)
        self.assertEqual(policy.to_publish_policy().signing_key_shard_count, 3)

    def test_resolve_extend_policy_infers_signing_key_shards_for_reuse_root(self) -> None:
        policy = resolve_extend_policy(
            args=ExtensionRequest(
                unlock_policy="reuse-root",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
            defaults=ExtendDefaults(
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="not-stored",
            ),
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=2,
            require_recovery_kit_index=True,
        )

        self.assertEqual(
            policy.signing_key,
            ExtensionSigningKeyShards(threshold=2, share_count=3),
        )

    def test_run_extend_fails_closed_before_artifact_creation_on_untrusted_latest_head(
        self,
    ) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required MAIN documents",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 1,
            "validated_head_doc_hash": "aa" * 32,
            "validated_head_auth_status": "verified",
            "validated_head_root_authority_verified": True,
            "explicit_selection": False,
        }

        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            (existing_head / "keep.txt").write_text("keep", encoding="utf-8")

            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=_resolved_state(
                    diff_summary=None,
                    blocking_issues=(
                        {
                            "code": "RECOVERY_HEAD_UNTRUSTED",
                            "message": (
                                "latest supplied recovery head could not be trusted: "
                                "missing required MAIN documents"
                            ),
                            "details": trust_details,
                        },
                    ),
                ),
            ):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    run_extend(
                        ExtensionRequest(
                            publish_root=str(root_dir),
                            input_paths=["/tmp/root/example.txt"],
                        ),
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

        self.assertEqual(ctx.exception.code, "RECOVERY_HEAD_UNTRUSTED")
        self.assertEqual(ctx.exception.details, trust_details)
        self.assertFalse((root_dir / "extensions" / "02").exists())
        self.assertEqual(list((root_dir / "extensions").glob(".staging-*")), [])

    def test_assemble_prepared_extension_document_uses_changed_and_new_paths(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"])
            )
            built = assemble_prepared_extension_document(
                prepared,
                chunker=lambda data, _profile: ((0, len(data)),),
            )

        self.assertEqual(built.document.header.index, 2)
        self.assertEqual(built.document.header.parent_doc_hash, b"\x11" * 32)
        self.assertEqual(built.document.header.root_doc_hash, b"\x22" * 32)
        self.assertFalse(hasattr(built.document.header, "parent_index"))
        self.assertFalse(hasattr(built.document.header, "signing_seed"))
        self.assertEqual([item.path for item in built.document.files], ["new.txt", "updated.txt"])

    def test_assemble_rejects_append_past_complete_chain_document_limit(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
            chain_document_count=128,
        )
        prepared = prepare_extend_run_from_state(
            ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"]),
            resolved,
        )

        with self.assertRaisesRegex(ValueError, "Rebuild the latest logical state"):
            assemble_prepared_extension_document(
                prepared,
                chunker=lambda data, _profile: ((0, len(data)),),
            )

    def test_assemble_does_not_trust_superseded_chunk_id_without_authenticated_bytes(self) -> None:
        superseded_bytes = b"root version"
        latest_bytes = b"latest version"
        superseded_chunk_id = hashlib.sha256(superseded_bytes).digest()
        latest_chunk_id = hashlib.sha256(latest_bytes).digest()
        resolved = _resolved_state(
            diff_summary={
                "new_paths": [],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
            input_files=(
                InputFile(
                    source_path=None,
                    relative_path="updated.txt",
                    data=superseded_bytes,
                    mtime=3,
                ),
            ),
            current_state=(
                LogicalFileState(
                    path="updated.txt",
                    size=len(latest_bytes),
                    sha256=latest_chunk_id,
                    mtime=2,
                    data=latest_bytes,
                ),
            ),
            available_chunks=((latest_chunk_id, latest_bytes),),
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"])
            )
            built = assemble_prepared_extension_document(
                prepared,
                chunker=lambda data, _profile: ((0, len(data)),),
            )

        self.assertEqual(built.stats.new_chunks, 1)
        self.assertEqual(built.stats.reused_chunks, 0)
        self.assertEqual(len(built.document.chunks), 1)
        self.assertEqual(
            built.document.files[0].chunk_refs[0].chunk_id,
            superseded_chunk_id,
        )

    def test_encrypt_prepared_extension_document_returns_ciphertext_and_ids(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(publish_root="/tmp/root", input_paths=["/tmp/root/example.txt"])
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
            ):
                encrypted = encrypt_prepared_extension_document(
                    prepared,
                    chunker=lambda data, _profile: ((0, len(data)),),
                )
        expected_doc_id, expected_doc_hash = doc_id_and_hash_from_ciphertext(encrypted.ciphertext)
        self.assertEqual(encrypted.ciphertext[:4], b"enc:")
        self.assertEqual(encrypted.doc_id, expected_doc_id)
        self.assertEqual(encrypted.doc_hash, expected_doc_hash)
        self.assertEqual(encrypted.built.document.header.index, 2)

    def test_prepare_staged_extension_publish_plans_canonical_targets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=1,
                root_passphrase_shard_count=1,
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(
                            require_recovery_kit_index=True,
                            passphrase_shard_count=2,
                            signing_key_shard_count=1,
                        ),
                    )

        self.assertEqual(publish.encrypted.built.document.header.index, 2)
        self.assertEqual(publish.artifacts.staging_dir.name, ".staging-2-abc123")
        self.assertEqual(publish.artifacts.final_dir.name, "02")
        expected_qr_path = (
            root_dir
            / "extensions"
            / ".staging-2-abc123"
            / f"qr_document-02-{publish.encrypted.doc_id.hex()}.pdf"
        )
        self.assertEqual(
            publish.artifacts.qr_document_path,
            expected_qr_path,
        )
        self.assertEqual(
            publish.artifacts.recovery_document_path.name,
            f"recovery_document-02-{publish.encrypted.doc_id.hex()}.pdf",
        )
        self.assertNotIn("ROOT-SHARDS", expected_recovery_kit_index_component_ids(publish))
        self.assertIn(
            "ROOT-SHARDS",
            expected_recovery_kit_index_component_ids(
                publish,
                root_passphrase_shards_required=True,
            ),
        )
        self.assertEqual(
            publish.artifacts.recovery_kit_index_path.name
            if publish.artifacts.recovery_kit_index_path
            else None,
            f"recovery_kit_index-02-{publish.encrypted.doc_id.hex()}.pdf",
        )
        self.assertEqual(
            [path.name for path in publish.artifacts.shard_paths],
            [
                f"shard-02-{publish.encrypted.doc_id.hex()}-1-of-2.pdf",
                f"shard-02-{publish.encrypted.doc_id.hex()}-2-of-2.pdf",
            ],
        )
        self.assertEqual(
            [path.name for path in publish.artifacts.signing_key_shard_paths],
            [f"signing-key-shard-02-{publish.encrypted.doc_id.hex()}-1-of-1.pdf"],
        )

    def test_execute_staged_extension_publish_promotes_valid_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(
                            require_recovery_kit_index=True,
                            passphrase_shard_count=2,
                        ),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")
                if plan.artifacts.recovery_kit_index_path is not None:
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", size=12)
                    pdf.multi_cell(
                        w=0,
                        text="\n".join(
                            [
                                "Recovery Kit Index",
                                "EXT-02-QR-DOC-01",
                                "EXT-02-RECOVERY-DOC-01",
                                "EXT-02-SHARD-01",
                                "EXT-02-SHARD-02",
                            ]
                        ),
                    )
                    pdf.output(str(plan.artifacts.recovery_kit_index_path))
                for path in plan.artifacts.shard_paths:
                    path.write_bytes(b"shard")

            buffer = io.StringIO()
            with (
                mock.patch(
                    "ethernity.workflows.extension.execution.resolve_extend_state",
                    return_value=resolved,
                ),
                ndjson_session(stream=buffer),
            ):
                result = execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=lambda _plan, _result: None,
                    reporter=CliExtensionReporter(),
                )

            events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(
                [event["id"] for event in events if event["type"] == "phase"],
                ["render", "validate", "publish"],
            )

            self.assertEqual(result.index, 2)
            self.assertEqual(result.final_dir.name, "02")
            self.assertTrue(result.qr_document_path.exists())
            self.assertTrue(result.recovery_document_path.exists())
            self.assertTrue(result.recovery_kit_index_path.exists())
            self.assertEqual(
                [path.name for path in result.shard_paths],
                [
                    f"shard-02-{publish.encrypted.doc_id.hex()}-1-of-2.pdf",
                    f"shard-02-{publish.encrypted.doc_id.hex()}-2-of-2.pdf",
                ],
            )
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_validate_prepared_extend_render_uses_temporary_no_publish_workspace(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        shard_threshold=1,
                        shard_count=1,
                    )
                )
                runtime = resolve_extend_runtime(prepared, create_layout_debug_dir=False)
                encrypted = encrypt_prepared_extension_document(
                    prepared,
                    chunker=lambda data, _profile: ((0, len(data)),),
                )

            rendered_paths: list[Path] = []

            def _fake_render(inputs: RenderInputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                rendered_paths.append(output_path)
                return _render_result_for_inputs(inputs)

            with (
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.validate_staged_main_carrier"
                ) as validate_main,
                mock.patch(
                    "ethernity.workflows.extension.execution.validate_staged_shard_carriers"
                ) as validate_shards,
                mock.patch(
                    "ethernity.workflows.extension.execution."
                    "validate_staged_chain_bound_kit_carrier"
                ) as validate_kit,
                mock.patch(
                    "ethernity.workflows.extension.execution."
                    "validate_staged_recovery_kit_index_document"
                ) as validate_index,
            ):
                validate_prepared_extend_render(
                    prepared,
                    runtime=runtime,
                    encrypted=encrypted,
                    nonce="preview",
                )

            self.assertGreaterEqual(len(rendered_paths), 2)
            self.assertFalse(any(path.exists() for path in rendered_paths))
            self.assertEqual(list((root_dir / "extensions").glob("*")), [])
            validate_main.assert_called_once()
            validate_shards.assert_called_once()
            validate_kit.assert_called_once()
            validate_index.assert_called_once()
            self.assertFalse(validate_index.call_args.kwargs["root_passphrase_shards_required"])

    def test_validate_prepared_extend_render_requires_root_shards_for_defaulted_reuse_root(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            config_path = _config_with_reuse_root_default(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=3,
            )
            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        signing_key_mode="not-stored",
                    )
                )
                runtime = resolve_extend_runtime(prepared, create_layout_debug_dir=False)
                encrypted = encrypt_prepared_extension_document(
                    prepared,
                    chunker=lambda data, _profile: ((0, len(data)),),
                )

            def _fake_render(inputs: RenderInputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                return _render_result_for_inputs(inputs)

            with (
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch("ethernity.workflows.extension.execution.validate_staged_main_carrier"),
                mock.patch(
                    "ethernity.workflows.extension.execution.validate_staged_shard_carriers"
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution."
                    "validate_staged_chain_bound_kit_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution."
                    "validate_staged_recovery_kit_index_document"
                ) as validate_index,
            ):
                validate_prepared_extend_render(
                    prepared,
                    runtime=runtime,
                    encrypted=encrypted,
                    nonce="preview",
                )

            validate_index.assert_called_once()
            self.assertTrue(validate_index.call_args.kwargs["root_passphrase_shards_required"])

    def test_validate_prepared_extend_render_uses_scan_mode_loose_preview_layout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "publish-target"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        scan_paths=["/tmp/root.pdf"],
                        input_paths=["/tmp/root/example.txt"],
                        shard_threshold=1,
                        shard_count=1,
                    )
                )
                runtime = resolve_extend_runtime(prepared, create_layout_debug_dir=False)
                encrypted = encrypt_prepared_extension_document(
                    prepared,
                    chunker=lambda data, _profile: ((0, len(data)),),
                )

            def _fake_render(inputs: RenderInputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                return _render_result_for_inputs(inputs)

            with (
                mock.patch(
                    "ethernity.workflows.extension.execution.create_staged_extension_artifact_plan",
                    wraps=_create_staged_extension_artifact_plan,
                ) as create_plan,
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch("ethernity.workflows.extension.execution.validate_staged_main_carrier"),
                mock.patch(
                    "ethernity.workflows.extension.execution.validate_staged_shard_carriers"
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution."
                    "validate_staged_chain_bound_kit_carrier"
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution."
                    "validate_staged_recovery_kit_index_document"
                ),
            ):
                validate_prepared_extend_render(
                    prepared,
                    runtime=runtime,
                    encrypted=encrypted,
                    nonce="preview",
                )

            create_plan.assert_called_once()
            self.assertEqual(create_plan.call_args.kwargs["publish_layout"], "loose")
            self.assertTrue(create_plan.call_args.kwargs["allow_missing_root"])
            self.assertTrue(create_plan.call_args.kwargs["require_empty_root"])

    def test_execute_staged_extension_publish_rejects_changed_published_head(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")

            assert resolved.lineage is not None
            current = replace(
                resolved,
                lineage=replace(resolved.lineage, head_doc_hash=b"\x99" * 32),
            )
            with (
                mock.patch(
                    "ethernity.workflows.extension.execution.resolve_extend_state",
                    return_value=current,
                ),
                self.assertRaises(ExtensionWorkflowError) as ctx,
            ):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=lambda _plan, _result: None,
                )

            self.assertEqual(ctx.exception.code, api_codes.CHAIN_INVALID)
            self.assertIn("chain head changed", str(ctx.exception))
            self.assertFalse(publish.artifacts.staging_dir.exists())
            self.assertFalse(publish.artifacts.final_dir.exists())

    def test_validate_staged_recovery_kit_index_document_rejects_invalid_pdf(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            publish.artifacts.recovery_kit_index_path.write_bytes(b"not-a-pdf")

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_staged_recovery_kit_index_document(publish)

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("recovery_kit_index artifact is invalid", str(ctx.exception))

    def test_validate_staged_recovery_kit_index_document_accepts_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(
                w=0,
                text="\n".join(
                    [
                        "Recovery Kit Index",
                        publish.encrypted.doc_id.hex(),
                        "Extension 02",
                        "ROOT-BACKUP",
                        "EXT-02-QR-DOC-01",
                        "EXT-02-RECOVERY-DOC-01",
                    ]
                ),
            )
            pdf.output(str(publish.artifacts.recovery_kit_index_path))

            _validate_staged_recovery_kit_index_document(publish)

    def test_validate_staged_recovery_kit_index_document_rejects_wrong_doc_identity(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(
                w=0,
                text="\n".join(
                    [
                        "Recovery Kit Index",
                        "wrong-doc-id",
                        "Extension 02",
                        "EXT-02-QR-DOC-01",
                        "EXT-02-RECOVERY-DOC-01",
                    ]
                ),
            )
            pdf.output(str(publish.artifacts.recovery_kit_index_path))

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_staged_recovery_kit_index_document(publish)

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("missing expected inventory rows", str(ctx.exception))

    def test_validate_staged_recovery_kit_index_document_rejects_missing_inventory_rows(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                    )

            assert publish.artifacts.recovery_kit_index_path is not None
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.cell(text="Recovery Kit Index")
            pdf.output(str(publish.artifacts.recovery_kit_index_path))

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_staged_recovery_kit_index_document(publish)

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("missing expected inventory rows", str(ctx.exception))

    def test_execute_staged_extension_publish_discards_failed_staging_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr-only")

            with self.assertRaisesRegex(ValueError, "missing required MAIN artifacts"):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=lambda _plan, _result: None,
                )

            self.assertFalse(publish.artifacts.staging_dir.exists())

    def test_execute_staged_extension_publish_rejects_post_validation_file_swap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")

            def _post_validate(plan, _render_result) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"swapped regular file")

            with self.assertRaisesRegex(ValueError, "artifacts changed before promotion"):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=_post_validate,
                )

            self.assertFalse(publish.artifacts.staging_dir.exists())

    def test_execute_staged_extension_publish_rejects_loose_root_mutation_before_promotion(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "scan-output"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        scan_paths=["/tmp/root.pdf"],
                        input_paths=["/tmp/root/example.txt"],
                        shard_threshold=1,
                        shard_count=1,
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")

            def _post_validate(plan, _render_result) -> None:
                (plan.artifacts.publish_root / "unexpected.txt").write_text(
                    "changed",
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                ValueError,
                "scan-mode extension publish target changed before promotion",
            ):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=_post_validate,
                )

            self.assertFalse(publish.artifacts.staging_dir.exists())

    def test_execute_staged_extension_publish_rejects_extensions_dir_swap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            moved_extensions_dir = root_dir / "extensions-old"

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")

            def _post_validate(plan, _render_result) -> None:
                extensions_dir = root_dir / "extensions"
                extensions_dir.rename(moved_extensions_dir)
                replacement_staging_dir = extensions_dir / plan.artifacts.staging_dir.name
                replacement_staging_dir.mkdir(parents=True)
                (replacement_staging_dir / plan.artifacts.qr_document_path.name).write_bytes(b"qr")
                (replacement_staging_dir / plan.artifacts.recovery_document_path.name).write_bytes(
                    b"recovery"
                )

            with self.assertRaisesRegex(
                ValueError,
                "extensions directory changed before promotion",
            ):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=_post_validate,
                )

            self.assertTrue((moved_extensions_dir / publish.artifacts.staging_dir.name).is_dir())
            self.assertTrue((root_dir / "extensions" / publish.artifacts.staging_dir.name).is_dir())

    def test_execute_staged_extension_publish_rejects_root_dir_swap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )

            moved_root_dir = Path(tmpdir) / "root-old"

            def _renderer(plan) -> None:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")

            def _post_validate(plan, _render_result) -> None:
                root_dir.rename(moved_root_dir)
                replacement_staging_dir = root_dir / "extensions" / plan.artifacts.staging_dir.name
                replacement_staging_dir.mkdir(parents=True)
                (replacement_staging_dir / plan.artifacts.qr_document_path.name).write_bytes(b"qr")
                (replacement_staging_dir / plan.artifacts.recovery_document_path.name).write_bytes(
                    b"recovery"
                )

            with self.assertRaisesRegex(
                ValueError,
                "extension publish root changed before promotion",
            ):
                execute_staged_extension_publish(
                    publish,
                    renderer=_renderer,
                    post_validate=_post_validate,
                )

            self.assertTrue(
                (moved_root_dir / "extensions" / publish.artifacts.staging_dir.name).is_dir()
            )
            self.assertTrue((root_dir / "extensions" / publish.artifacts.staging_dir.name).is_dir())

    def test_execute_prepared_extend_discards_layout_debug_sidecars_on_render_failure(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = Path(tmpdir) / "layout-debug"
            root_dir.mkdir(exist_ok=True)
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        layout_debug_directory=str(debug_dir),
                        shard_threshold=1,
                        shard_count=1,
                    )
                )

            def _render_failure(_plan, *, runtime, **_kwargs):
                assert runtime.layout_debug_dir is not None
                self.assertNotEqual(Path(runtime.layout_debug_dir), debug_dir)
                Path(runtime.layout_debug_dir, "qr_document.layout.json").write_text(
                    "unpublished debug",
                    encoding="utf-8",
                )
                raise ValueError("render failed")

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.render_extension_artifacts",
                    side_effect=_render_failure,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "render failed"):
                    execute_prepared_extend(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

            self.assertTrue(debug_dir.exists())
            self.assertFalse((debug_dir / "qr_document.layout.json").exists())
            self.assertEqual(list(debug_dir.iterdir()), [])

    def test_execute_prepared_extend_preflights_publish_target_before_encryption(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            (root_dir / "extensions" / "02").mkdir(parents=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            resolved = replace(
                resolved,
                inspection=replace(resolved.inspection, root_dir=str(root_dir)),
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )

            with (
                mock.patch(
                    "ethernity.workflows.extension.execution._runtime_impl.resolve_extend_runtime"
                ) as resolve_runtime,
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_prepared_extension_document"
                ) as encrypt,
            ):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    execute_prepared_extend(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                    )

        self.assertEqual(ctx.exception.code, api_codes.EXTENSION_PUBLISH_TARGET_INVALID)
        self.assertEqual(ctx.exception.details, {"stage": "publish_target"})
        resolve_runtime.assert_called_once_with(prepared, include_layout_debug_dir=False)
        encrypt.assert_not_called()

    def test_execute_prepared_extend_preflights_publish_target_before_layout_debug_creation(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            root_dir = tmp_path / "root"
            debug_dir = tmp_path / "layout-debug"
            (root_dir / "extensions" / "02").mkdir(parents=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            resolved = replace(
                resolved,
                inspection=replace(resolved.inspection, root_dir=str(root_dir)),
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        layout_debug_directory=str(debug_dir),
                        shard_threshold=1,
                        shard_count=1,
                    )
                )

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                execute_prepared_extend(prepared, chunker=lambda data, _profile: ((0, len(data)),))

            self.assertEqual(ctx.exception.code, api_codes.EXTENSION_PUBLISH_TARGET_INVALID)
            self.assertFalse(debug_dir.exists())

    def test_execute_prepared_extend_rejects_scan_layout_debug_inside_publish_root(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            root_dir = tmp_path / "scan-output"
            debug_dir = root_dir / "layout-debug"
            config_path = _config_with_no_shard_defaults(tmp_path / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            resolved = replace(
                resolved,
                inspection=replace(resolved.inspection, root_dir=str(root_dir)),
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        scan_paths=["/tmp/root.pdf"],
                        input_paths=["/tmp/root/example.txt"],
                        layout_debug_directory=str(debug_dir),
                        shard_threshold=1,
                        shard_count=1,
                    )
                )

            with mock.patch(
                "ethernity.workflows.extension.prepare.encrypt_prepared_extension_document"
            ) as encrypt:
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    execute_prepared_extend(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

            self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
            self.assertFalse(root_dir.exists())
            encrypt.assert_not_called()

    def test_execute_prepared_extend_discards_extension_staging_on_layout_debug_setup_failure(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = Path(tmpdir) / "layout-debug"
            root_dir.mkdir(exist_ok=True)
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        layout_debug_directory=str(debug_dir),
                        shard_threshold=1,
                        shard_count=1,
                    )
                )

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution._runtime_with_staged_layout_debug",
                    side_effect=OSError("debug staging failed"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "debug staging failed"):
                    execute_prepared_extend(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

            extensions_dir = root_dir / "extensions"
            self.assertTrue(extensions_dir.exists())
            remaining_staging_dirs = [
                path.name for path in extensions_dir.iterdir() if path.name.startswith(".staging-")
            ]
            self.assertEqual(
                remaining_staging_dirs,
                [],
            )

    def test_execute_prepared_extend_promotes_layout_debug_sidecars_after_publish(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = Path(tmpdir) / "layout-debug"
            root_dir.mkdir(exist_ok=True)
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        layout_debug_directory=str(debug_dir),
                        shard_threshold=1,
                        shard_count=1,
                    )
                )

            def _fake_render(_plan, *, runtime, **_kwargs):
                assert runtime.layout_debug_dir is not None
                self.assertNotEqual(Path(runtime.layout_debug_dir), debug_dir)
                Path(runtime.layout_debug_dir, "qr_document.layout.json").write_text(
                    "published debug",
                    encoding="utf-8",
                )
                return RenderedExtensionArtifacts(
                    passphrase_shards=(),
                    signing_key_shards=(),
                    recovery_document_fallback_frames=(),
                    recovery_document_fallback_proof=None,
                )

            def _fake_publish(publish, *, renderer, **_kwargs):
                renderer(publish)
                return mock.Mock(
                    index=2,
                    doc_id=publish.encrypted.doc_id,
                    doc_hash=publish.encrypted.doc_hash,
                    final_dir=publish.artifacts.final_dir,
                    qr_document_path=publish.artifacts.final_dir / "qr.pdf",
                    recovery_document_path=publish.artifacts.final_dir / "recovery.pdf",
                    recovery_kit_index_path=None,
                    shard_paths=(),
                    signing_key_shard_paths=(),
                    root_passphrase_shard_threshold=None,
                    root_passphrase_shard_count=0,
                )

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.render_extension_artifacts",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.execute_staged_extension_publish",
                    side_effect=_fake_publish,
                ),
            ):
                execute_prepared_extend(
                    prepared,
                    chunker=lambda data, _profile: ((0, len(data)),),
                    nonce="abc123",
                )

            self.assertEqual(
                (debug_dir / "qr_document.layout.json").read_text(encoding="utf-8"),
                "published debug",
            )
            self.assertEqual(
                [path.name for path in debug_dir.iterdir()],
                ["qr_document.layout.json"],
            )

    def test_execute_prepared_extend_warns_when_layout_debug_publish_fails_after_publish(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            debug_dir = Path(tmpdir) / "layout-debug"
            root_dir.mkdir(exist_ok=True)
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        layout_debug_directory=str(debug_dir),
                        shard_threshold=1,
                        shard_count=1,
                    )
                )

            def _fake_render(_plan, *, runtime, **_kwargs):
                assert runtime.layout_debug_dir is not None
                Path(runtime.layout_debug_dir, "qr_document.layout.json").write_text(
                    "published debug",
                    encoding="utf-8",
                )
                return RenderedExtensionArtifacts(
                    passphrase_shards=(),
                    signing_key_shards=(),
                    recovery_document_fallback_frames=(),
                    recovery_document_fallback_proof=None,
                )

            def _fake_publish(publish, *, renderer, **_kwargs):
                renderer(publish)
                return mock.Mock(
                    index=2,
                    doc_id=publish.encrypted.doc_id,
                    doc_hash=publish.encrypted.doc_hash,
                    final_dir=publish.artifacts.final_dir,
                    qr_document_path=publish.artifacts.final_dir / "qr.pdf",
                    recovery_document_path=publish.artifacts.final_dir / "recovery.pdf",
                    recovery_kit_index_path=None,
                    shard_paths=(),
                    signing_key_shard_paths=(),
                    root_passphrase_shard_threshold=None,
                    root_passphrase_shard_count=0,
                )

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.render_extension_artifacts",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.execute_staged_extension_publish",
                    side_effect=_fake_publish,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution._replace_layout_debug_sidecars",
                    side_effect=OSError("debug move failed"),
                ),
            ):
                reporter = mock.Mock()
                executed = execute_prepared_extend(
                    prepared,
                    chunker=lambda data, _profile: ((0, len(data)),),
                    nonce="abc123",
                    reporter=reporter,
                )

            self.assertEqual(executed.result.index, 2)
            self.assertFalse((debug_dir / "qr_document.layout.json").exists())
            self.assertEqual(list(debug_dir.iterdir()), [])
            reporter.warning.assert_called_once()
            self.assertIn("Extension published", reporter.warning.call_args.args[0])
            self.assertEqual(
                Path(reporter.warning.call_args.kwargs["details"]["layout_debug_dir"]),
                debug_dir.resolve(),
            )

    def test_publish_staged_layout_debug_warns_when_final_dir_identity_changes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "layout-debug"
            final_dir.mkdir()
            expected_identity = extend_execution._layout_debug_dir_identity(final_dir)
            staging_dir = Path(tmpdir) / "layout-staging"
            staging_dir.mkdir()
            (staging_dir / "qr_document.layout.json").write_text(
                "debug",
                encoding="utf-8",
            )
            moved_dir = Path(tmpdir) / "layout-debug-old"
            final_dir.rename(moved_dir)
            final_dir.mkdir()

            reporter = mock.Mock()
            extend_execution._publish_staged_layout_debug(
                staging_dir,
                str(final_dir),
                expected_final_dir_identity=expected_identity,
                reporter=reporter,
            )

            self.assertFalse(staging_dir.exists())
            self.assertFalse((final_dir / "qr_document.layout.json").exists())
            reporter.warning.assert_called_once()
            self.assertIn(
                "layout debug sidecar promotion failed",
                reporter.warning.call_args.args[0],
            )
            self.assertIn(
                "changed before sidecar promotion",
                reporter.warning.call_args.kwargs["details"]["error"],
            )

    def test_run_extend_promotes_rendered_extension_with_validated_unlock_shards(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            (existing_head / "qr_document-01-existing.pdf").write_bytes(b"existing")
            (root_dir / "recovery_kit_index.pdf").write_bytes(b"root-index")
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=2,
            )
            rendered_inputs: dict[str, object] = {}
            shard_frames_by_path: dict[str, list[Frame]] = {}
            main_frames_by_path: dict[str, list[Frame]] = {}
            auth_frame: Frame | None = None

            def _fake_render(inputs) -> RenderResult:
                nonlocal auth_frame
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                rendered_inputs[output_path.name] = inputs
                if output_path.name.startswith("recovery_kit_index-"):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", size=12)
                    pdf.multi_cell(w=0, text="\n".join(_kit_index_pdf_lines(inputs)))
                    pdf.output(str(output_path))
                else:
                    output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    main_frames_by_path[str(output_path)] = list(inputs.frames)
                if output_path.name.startswith("qr_document-"):
                    auth_frame = next(
                        (frame for frame in inputs.frames if frame.frame_type == FrameType.AUTH),
                        None,
                    )
                if output_path.name.startswith(("shard-", "signing-key-shard-")):
                    shard_frames_by_path[str(output_path)] = list(inputs.frames)
                return _render_result_for_inputs(inputs)

            def _scan_main_carrier(paths, **_kwargs):
                frames = list(main_frames_by_path[str(paths[0])])
                if (
                    auth_frame is not None
                    and Path(paths[0]).name.startswith("recovery_document-")
                    and not any(frame.frame_type == FrameType.AUTH for frame in frames)
                ):
                    frames.append(auth_frame)
                return FrameInputResult(frames=tuple(frames))

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_validation.shard_frames_from_scan",
                    side_effect=lambda paths, **_kwargs: shard_frames_by_path[str(paths[0])],
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_validation.validate_pdf_has_pages",
                    return_value=object(),
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_validation.validate_fallback_text_in_pdf"
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                    side_effect=_scan_main_carrier,
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "_validate_recovery_document_pdf",
                    return_value=None,
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "validate_fallback_text_in_pdf",
                ),
            ):
                result = run_extend(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        signing_key_mode="sharded",
                        signing_key_shard_threshold=1,
                        signing_key_shard_count=1,
                    ),
                    chunker=lambda data, _profile: ((0, len(data)),),
                    nonce="abc123",
                )

            self.assertEqual(result.final_dir.name, "02")
            self.assertTrue(result.qr_document_path.exists())
            self.assertTrue(result.recovery_document_path.exists())
            self.assertEqual(len(result.shard_paths), 2)
            self.assertEqual(len(result.signing_key_shard_paths), 1)
            self.assertIsNotNone(result.recovery_kit_index_path)
            self.assertTrue(existing_head.exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())
            qr_inputs = rendered_inputs[result.qr_document_path.name]
            recovery_inputs = rendered_inputs[result.recovery_document_path.name]
            kit_index_inputs = rendered_inputs[result.recovery_kit_index_path.name]
            self.assertEqual(qr_inputs.lineage.kind, "extension")
            self.assertEqual(qr_inputs.lineage.extension_index, 2)
            self.assertEqual(recovery_inputs.lineage.kind, "extension")
            self.assertEqual(kit_index_inputs.lineage.kind, "extension")
            self.assertEqual(
                sum(1 for frame in qr_inputs.frames if frame.frame_type == FrameType.AUTH),
                1,
            )
            self.assertEqual(tuple(kit_index_inputs.frames), ())
            self.assertEqual(tuple(kit_index_inputs.qr_payloads or ()), ())
            self.assertFalse(kit_index_inputs.render_qr)
            self.assertEqual(
                kit_index_inputs.context["kit_qr_chunk_count"],
                len(qr_inputs.frames),
            )
            self.assertIn(
                {
                    "component_id": "ROOT-BACKUP",
                    "detail": (
                        "Requires matching root backup QR and recovery documents "
                        "for root document deadbeef"
                    ),
                    "status": "External",
                },
                kit_index_inputs.context["inventory_rows"],
            )
            self.assertEqual(
                [section.label for section in recovery_inputs.fallback_sections or ()],
                [AUTH_FALLBACK_LABEL, "Main Frame"],
            )

    def test_run_extend_keeps_previous_head_when_main_validation_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            marker = existing_head / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            captured: dict[str, list[Frame]] = {}

            def _fake_render(inputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = list(inputs.frames)
                return _render_result_for_inputs(inputs)

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: FrameInputResult(
                        frames=(
                            Frame(
                                version=VERSION,
                                frame_type=FrameType.MAIN_DOCUMENT,
                                doc_id=captured["frames"][0].doc_id,
                                index=0,
                                total=1,
                                data=b"wrong",
                            ),
                        )
                    ),
                ),
            ):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    run_extend(
                        ExtensionRequest(
                            publish_root=str(root_dir),
                            input_paths=["/tmp/root/example.txt"],
                            shard_threshold=1,
                            shard_count=1,
                        ),
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertTrue(existing_head.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((root_dir / "extensions" / "02").exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_run_extend_keeps_previous_head_when_recovery_document_validation_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            marker = existing_head / "keep.txt"
            marker.write_text("keep", encoding="utf-8")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        publish_root=str(root_dir), input_paths=["/tmp/root/example.txt"]
                    )
                )
                with mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ):
                    publish = prepare_staged_extension_publish(
                        prepared,
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                        publish_policy=ExtensionPublishPolicy(),
                    )
            qr_frames = [
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=publish.encrypted.doc_id,
                    index=0,
                    total=1,
                    data=publish.encrypted.ciphertext,
                ),
                Frame(
                    version=VERSION,
                    frame_type=FrameType.AUTH,
                    doc_id=publish.encrypted.doc_id,
                    index=0,
                    total=1,
                    data=b"auth",
                ),
            ]
            invalid_recovery_frames = (
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=publish.encrypted.doc_id,
                    index=0,
                    total=1,
                    data=b"wrong",
                ),
            )
            rendered = RenderedExtensionArtifacts(
                passphrase_shards=(),
                signing_key_shards=(),
                recovery_document_fallback_frames=invalid_recovery_frames,
            )

            def _renderer(plan) -> RenderedExtensionArtifacts:
                plan.artifacts.qr_document_path.write_bytes(b"qr")
                plan.artifacts.recovery_document_path.write_bytes(b"recovery")
                plan.artifacts.recovery_kit_path.write_bytes(b"kit")
                return rendered

            def _post_validate(plan, result) -> None:
                _validate_staged_main_carrier(plan, result)

            with (
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                    return_value=FrameInputResult(frames=tuple(qr_frames)),
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation._validate_recovery_document_pdf",
                    return_value=None,
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "validate_fallback_text_in_pdf",
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "resolve_required_auth_payload",
                    return_value=(
                        AuthPayload(
                            version=1,
                            doc_hash=publish.encrypted.doc_hash,
                            sign_pub=derive_public_key(resolved.signing_seed),
                            signature=b"\x77" * 64,
                        ),
                        "verified",
                    ),
                ),
            ):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    execute_staged_extension_publish(
                        publish,
                        renderer=_renderer,
                        post_validate=_post_validate,
                    )

            self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
            self.assertIn("recovery_document-", str(ctx.exception))
            self.assertTrue(existing_head.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((root_dir / "extensions" / "02").exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_run_extend_keeps_previous_head_when_shard_validation_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)
            marker = existing_head / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            (root_dir / "shard-root-1.pdf").write_bytes(b"root-shard-1")

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            captured: dict[str, list[Frame]] = {}

            def _fake_render(inputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = list(inputs.frames)
                return _render_result_for_inputs(inputs)

            invalid_payload = _shard_payload(
                share_index=1,
                threshold=1,
                share_count=1,
                key_type="passphrase",
                doc_hash=b"\x99" * 32,
            )
            invalid_frame = Frame(
                version=VERSION,
                frame_type=FrameType.KEY_DOCUMENT,
                doc_id=b"\x00" * 16,
                index=0,
                total=1,
                data=encode_shard_payload(invalid_payload),
            )

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_validation.shard_frames_from_scan",
                    return_value=[invalid_frame],
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: FrameInputResult(
                        frames=tuple(captured["frames"])
                    ),
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "_validate_recovery_document_pdf",
                    return_value=None,
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "validate_fallback_text_in_pdf",
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "resolve_required_auth_payload",
                    return_value=(
                        AuthPayload(
                            version=1,
                            doc_hash=b"\x22" * 32,
                            sign_pub=derive_public_key(resolved.signing_seed),
                            signature=b"\x77" * 64,
                        ),
                        "verified",
                    ),
                ),
            ):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    run_extend(
                        ExtensionRequest(
                            publish_root=str(root_dir),
                            input_paths=["/tmp/root/example.txt"],
                            shard_threshold=1,
                            shard_count=1,
                        ),
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

            self.assertEqual(ctx.exception.code, EXTENSION_SHARD_CARRIER_INVALID)
            self.assertTrue(existing_head.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((root_dir / "extensions" / "02").exists())
            self.assertFalse((root_dir / "extensions" / ".staging-2-abc123").exists())

    def test_validate_rendered_shard_carrier_accepts_repeated_identical_qr_payloads(
        self,
    ) -> None:
        path = Path("/tmp/shard-01-deadbeef-1-of-1.pdf")
        expected_doc_id = b"\x22" * 16
        expected_doc_hash = b"\x33" * 32
        expected_payload = _shard_payload(
            share_index=1,
            threshold=1,
            share_count=1,
            key_type="passphrase",
            doc_hash=expected_doc_hash,
        )
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=expected_doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(expected_payload),
        )

        with (
            mock.patch(
                "ethernity.workflows.extension.shard_validation.shard_frames_from_scan",
                return_value=[frame, frame],
            ),
            mock.patch(
                "ethernity.workflows.extension.shard_validation.verify_shard",
                return_value=True,
            ),
            mock.patch(
                "ethernity.workflows.extension.shard_validation.validate_pdf_has_pages",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.workflows.extension.shard_validation.validate_fallback_text_in_pdf"
            ),
        ):
            _validate_rendered_shard_carrier(
                path=path,
                expected_payload=expected_payload,
                expected_doc_id=expected_doc_id,
                expected_doc_hash=expected_doc_hash,
                quiet=True,
                secret_label="passphrase shard",
            )

    def test_validate_rendered_shard_carrier_rejects_invalid_signature(self) -> None:
        path = Path("/tmp/shard-01-deadbeef-1-of-1.pdf")
        expected_doc_id = b"\x22" * 16
        expected_doc_hash = b"\x33" * 32
        expected_payload = _shard_payload(
            share_index=1,
            threshold=1,
            share_count=1,
            key_type="passphrase",
            doc_hash=expected_doc_hash,
        )
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=expected_doc_id,
            index=0,
            total=1,
            data=encode_shard_payload(expected_payload),
        )

        with (
            mock.patch(
                "ethernity.workflows.extension.shard_validation.shard_frames_from_scan",
                return_value=[frame],
            ),
            mock.patch(
                "ethernity.workflows.extension.shard_validation.verify_shard",
                return_value=False,
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_rendered_shard_carrier(
                    path=path,
                    expected_payload=expected_payload,
                    expected_doc_id=expected_doc_id,
                    expected_doc_hash=expected_doc_hash,
                    quiet=True,
                    secret_label="passphrase shard",
                )

        self.assertEqual(ctx.exception.code, EXTENSION_SHARD_CARRIER_INVALID)
        self.assertIn("signature verification failed", str(ctx.exception))

    def test_run_extend_reuse_root_unlock_policy_emits_no_extension_shards(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            config_path = _config_with_reuse_root_default(Path(tmpdir) / "config.toml")
            existing_head = root_dir / "extensions" / "01"
            existing_head.mkdir(parents=True)

            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=2,
            )
            captured: dict[str, list[Frame]] = {}
            rendered_inputs: dict[str, object] = {}

            def _fake_render(inputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if output_path.name.startswith("recovery_kit_index-"):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Helvetica", size=12)
                    pdf.multi_cell(w=0, text="\n".join(_kit_index_pdf_lines(inputs)))
                    pdf.output(str(output_path))
                else:
                    output_path.write_bytes(output_path.name.encode("utf-8"))
                rendered_inputs[output_path.name] = inputs
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = list(inputs.frames)
                return _render_result_for_inputs(inputs)

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: FrameInputResult(
                        frames=tuple(captured["frames"])
                    ),
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "_validate_recovery_document_pdf",
                    return_value=None,
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "validate_fallback_text_in_pdf",
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation."
                    "resolve_required_auth_payload",
                    return_value=(
                        AuthPayload(
                            version=1,
                            doc_hash=b"\x22" * 32,
                            sign_pub=derive_public_key(resolved.signing_seed),
                            signature=b"\x77" * 64,
                        ),
                        "verified",
                    ),
                ),
            ):
                result = run_extend(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                    ),
                    chunker=lambda data, _profile: ((0, len(data)),),
                    nonce="abc123",
                )

            self.assertEqual(result.final_dir.name, "02")
            self.assertEqual(len(result.shard_paths), 0)
            self.assertEqual(len(result.signing_key_shard_paths), 0)
            self.assertEqual(result.root_passphrase_shard_threshold, 2)
            self.assertEqual(result.root_passphrase_shard_count, 2)
            self.assertIsNotNone(result.recovery_kit_index_path)
            recovery_inputs = rendered_inputs[result.recovery_document_path.name]
            self.assertIsNone(recovery_inputs.recovery_meta.passphrase)
            self.assertEqual(recovery_inputs.recovery_meta.quorum_value, "2 of 2")
            self.assertEqual(recovery_inputs.recovery_meta.quorum_label, "Root Shard Quorum")
            self.assertIn(
                "Passphrase recovery depends on the root backup shard documents.",
                recovery_inputs.key_lines,
            )
            self.assertIn(
                "Recover with 2 of 2 root shard documents.",
                recovery_inputs.key_lines,
            )
            self.assertIn(
                "Signing private key not stored in this extension document.",
                recovery_inputs.key_lines,
            )
            self.assertNotIn("Passphrase:", recovery_inputs.key_lines)
            self.assertNotIn(
                "Signing private key stored in main document.",
                recovery_inputs.key_lines,
            )
            kit_index_inputs = rendered_inputs[result.recovery_kit_index_path.name]
            self.assertIn(
                {
                    "component_id": "ROOT-BACKUP",
                    "detail": (
                        "Requires matching root backup QR and recovery documents "
                        "for root document deadbeef"
                    ),
                    "status": "External",
                },
                kit_index_inputs.context["inventory_rows"],
            )
            self.assertIn(
                {
                    "component_id": "ROOT-SHARDS",
                    "detail": "Requires root passphrase shard quorum 2 of 2",
                    "status": "External",
                },
                kit_index_inputs.context["inventory_rows"],
            )

    def test_run_extend_reuse_root_unlock_policy_requires_root_passphrase_shards(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )

        with (
            mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                run_extend(
                    ExtensionRequest(
                        publish_root="/tmp/root",
                        input_paths=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                    ),
                    chunker=lambda data, _profile: ((0, len(data)),),
                    nonce="abc123",
                )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn(
            "requires a published or supplied root passphrase shard policy", str(ctx.exception)
        )

    def test_resolve_extend_runtime_self_contained_inherits_validated_unlock_shard_policy(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
                root_passphrase_shard_threshold=2,
                root_passphrase_shard_count=3,
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                    )
                )

            runtime = resolve_extend_runtime(prepared)

        self.assertEqual(runtime.passphrase, ExtensionPassphraseShards(threshold=2, share_count=3))

    def test_resolve_extend_runtime_self_contained_without_shards_is_rejected(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        shard_count=0,
                    )
                )

            with (
                mock.patch(
                    "ethernity.workflows.extension.runtime.published_root_passphrase_shard_policy",
                    side_effect=AssertionError("root shard scan should not run"),
                ),
                self.assertRaises(ExtensionWorkflowError) as ctx,
            ):
                resolve_extend_runtime(prepared)

        self.assertIn("self-contained requires extension passphrase shards", str(ctx.exception))

    def test_resolve_extend_runtime_self_contained_uses_published_root_policy_when_inherited(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                    )
                )

            with mock.patch(
                "ethernity.workflows.extension.runtime.published_root_passphrase_shard_policy",
                return_value=(2, 5),
            ):
                runtime = resolve_extend_runtime(prepared)

        self.assertEqual(runtime.passphrase, ExtensionPassphraseShards(threshold=2, share_count=5))

    def test_resolve_extend_runtime_defaulted_reuse_root_scans_published_root_policy(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_reuse_root_default(Path(tmpdir) / "config.toml")
            resolved = replace(
                _resolved_state(
                    diff_summary={
                        "new_paths": ["new.txt"],
                        "changed_paths": ["updated.txt"],
                        "unchanged_paths": [],
                        "missing_paths": [],
                    },
                ),
                unlock_passphrase_shard_threshold=2,
                unlock_passphrase_shard_count=3,
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                    )
                )

            with mock.patch(
                "ethernity.workflows.extension.runtime.published_root_passphrase_shard_policy",
                return_value=(2, 5),
            ) as scanner:
                runtime = resolve_extend_runtime(prepared)

        scanner.assert_called_once()
        self.assertEqual(runtime.passphrase, ReuseRootPassphraseShards(threshold=2, share_count=5))

    def test_resolve_extend_runtime_reuse_root_requires_validated_unlock_shard_policy(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            config_path = _config_with_no_shard_defaults(Path(tmpdir) / "config.toml")
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            with mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ):
                prepared = prepare_extend_run(
                    ExtensionRequest(
                        config_path=str(config_path),
                        publish_root=str(root_dir),
                        input_paths=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                    )
                )

            with self.assertRaises(ExtensionWorkflowError) as ctx:
                resolve_extend_runtime(prepared)

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn(
            "requires a published or supplied root passphrase shard policy", str(ctx.exception)
        )

    def test_resolve_extend_runtime_rejects_explicit_zero_qr_chunk_size(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(
                    publish_root="/tmp/root",
                    input_paths=["/tmp/root/example.txt"],
                    qr_chunk_size=0,
                    shard_threshold=1,
                    shard_count=1,
                )
            )

        with self.assertRaises(ExtensionWorkflowError) as ctx:
            resolve_extend_runtime(prepared)

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("qr_chunk_size must be a positive integer", str(ctx.exception))

    def test_resolve_extend_runtime_emits_kit_index_when_design_supports_it(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(
                    publish_root="/tmp/root",
                    input_paths=["/tmp/root/example.txt"],
                    shard_threshold=1,
                    shard_count=1,
                )
            )

        with (
            mock.patch(
                "ethernity.workflows.extension.runtime.resolve_recovery_kit_index_style",
                return_value="forge",
            ),
        ):
            runtime = resolve_extend_runtime(prepared)

        self.assertTrue(runtime.to_publish_policy().require_recovery_kit_index)
        self.assertEqual(runtime.kit_index_style, "forge")

    def test_resolve_extend_runtime_omits_kit_index_when_style_lacks_support(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(
                    publish_root="/tmp/root",
                    input_paths=["/tmp/root/example.txt"],
                    shard_threshold=1,
                    shard_count=1,
                )
            )

        with (
            mock.patch(
                "ethernity.workflows.extension.runtime.resolve_recovery_kit_index_style",
                return_value=None,
            ),
        ):
            runtime = resolve_extend_runtime(prepared)

        self.assertFalse(runtime.to_publish_policy().require_recovery_kit_index)
        self.assertIsNone(runtime.kit_index_style)

    def test_resolve_extend_runtime_reuse_root_rejects_explicit_zero_qr_chunk_size(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
            root_passphrase_shard_threshold=2,
            root_passphrase_shard_count=3,
        )
        with mock.patch(
            "ethernity.workflows.extension.prepare.resolve_extend_state",
            return_value=resolved,
        ):
            prepared = prepare_extend_run(
                ExtensionRequest(
                    publish_root="/tmp/root",
                    input_paths=["/tmp/root/example.txt"],
                    unlock_policy="reuse-root",
                    qr_chunk_size=0,
                )
            )

        with self.assertRaises(ExtensionWorkflowError) as ctx:
            resolve_extend_runtime(prepared)

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("qr_chunk_size must be a positive integer", str(ctx.exception))

    def test_run_extend_reuse_root_unlock_policy_rejects_explicit_shard_overrides(self) -> None:
        resolved = _resolved_state(
            diff_summary={
                "new_paths": ["new.txt"],
                "changed_paths": ["updated.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
        )

        with (
            mock.patch(
                "ethernity.workflows.extension.prepare.resolve_extend_state",
                return_value=resolved,
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                run_extend(
                    ExtensionRequest(
                        publish_root="/tmp/root",
                        input_paths=["/tmp/root/example.txt"],
                        unlock_policy="reuse-root",
                        shard_count=0,
                    ),
                    chunker=lambda data, _profile: ((0, len(data)),),
                    nonce="abc123",
                )

        self.assertEqual(ctx.exception.code, EXTENSION_INVALID_POLICY)
        self.assertIn("unlock_policy=reuse-root", str(ctx.exception))

    def test_run_extend_rejects_missing_extension_auth(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir(exist_ok=True)
            resolved = _resolved_state(
                diff_summary={
                    "new_paths": ["new.txt"],
                    "changed_paths": ["updated.txt"],
                    "unchanged_paths": [],
                    "missing_paths": [],
                },
            )
            captured: dict[str, list[Frame]] = {}

            def _fake_render(inputs) -> RenderResult:
                output_path = Path(inputs.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_path.name.encode("utf-8"))
                if output_path.name.startswith(("qr_document-", "recovery_document-")):
                    captured["frames"] = [
                        frame
                        for frame in inputs.frames
                        if frame.frame_type == FrameType.MAIN_DOCUMENT
                    ]
                return _render_result_for_inputs(inputs)

            with (
                mock.patch(
                    "ethernity.workflows.extension.prepare.resolve_extend_state",
                    return_value=resolved,
                ),
                mock.patch(
                    "ethernity.workflows.extension.prepare.encrypt_bytes_with_passphrase",
                    side_effect=lambda data, *, passphrase: (b"enc:" + data, passphrase),
                ),
                mock.patch(
                    "ethernity.workflows.extension.execution.render_module.render_frames_to_pdf",
                    side_effect=_fake_render,
                ),
                mock.patch(
                    "ethernity.workflows.extension.rendering.validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.shard_rendering."
                    "validate_rendered_fallback_artifact"
                ),
                mock.patch(
                    "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                    side_effect=lambda *_args, **_kwargs: FrameInputResult(
                        frames=tuple(captured["frames"])
                    ),
                ),
            ):
                with self.assertRaises(ExtensionWorkflowError) as ctx:
                    run_extend(
                        ExtensionRequest(
                            publish_root=str(root_dir),
                            input_paths=["/tmp/root/example.txt"],
                            shard_threshold=1,
                            shard_count=1,
                        ),
                        chunker=lambda data, _profile: ((0, len(data)),),
                        nonce="abc123",
                    )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("missing auth payload", str(ctx.exception))

    def test_validate_single_main_carrier_rejects_missing_auth_for_recovery_document_scan(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )

        with mock.patch(
            "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
            return_value=FrameInputResult(frames=(main_frame,)),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_single_main_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("missing auth payload", str(ctx.exception))

    def test_validate_single_recovery_document_carrier_uses_render_contract_frames(self) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )
        reader = object()

        with (
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "_validate_recovery_document_pdf",
                return_value=reader,
            ),
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "validate_fallback_text_in_pdf",
            ) as validate_fallback_text_in_pdf,
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "resolve_required_auth_payload",
                return_value=(
                    AuthPayload(
                        version=1,
                        doc_hash=doc_hash,
                        sign_pub=b"\x44" * 32,
                        signature=b"\x55" * 64,
                    ),
                    "verified",
                ),
            ),
        ):
            _validate_single_recovery_document_carrier(
                path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                frames=(auth_frame, main_frame),
                fallback_proof=RenderFallbackProof(
                    section_frame_digests=tuple(
                        hashlib.sha256(encode_frame(frame)).hexdigest()
                        for frame in (auth_frame, main_frame)
                    ),
                    section_titles=(AUTH_FALLBACK_LABEL, "Main Frame"),
                    expected_section_count=2,
                    emitted_block_count=2,
                    emitted_line_count=2,
                    consumed_section_count=2,
                    fully_consumed=True,
                    emitted_fallback_lines=("auth-line", "main-line"),
                ),
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=b"\x44" * 32,
                require_auth=True,
                quiet=True,
            )

        validate_fallback_text_in_pdf.assert_called_once()
        self.assertEqual(validate_fallback_text_in_pdf.call_args.kwargs["reader"], reader)

    def test_validate_single_recovery_document_carrier_validates_pdf_fallback_text(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )
        fallback_proof = RenderFallbackProof(
            section_frame_digests=tuple(
                hashlib.sha256(encode_frame(frame)).hexdigest()
                for frame in (auth_frame, main_frame)
            ),
            section_titles=(AUTH_FALLBACK_LABEL, "Main Frame"),
            expected_section_count=2,
            emitted_block_count=2,
            emitted_line_count=2,
            consumed_section_count=2,
            fully_consumed=True,
            emitted_fallback_lines=("auth-payload-line", "main-payload-line"),
        )
        reader = object()

        with (
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "_validate_recovery_document_pdf",
                return_value=reader,
            ),
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "validate_fallback_text_in_pdf",
            ) as validate_fallback_text_in_pdf,
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "resolve_required_auth_payload",
                return_value=(
                    AuthPayload(
                        version=1,
                        doc_hash=doc_hash,
                        sign_pub=b"\x44" * 32,
                        signature=b"\x55" * 64,
                    ),
                    "verified",
                ),
            ),
        ):
            _validate_single_recovery_document_carrier(
                path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                frames=(auth_frame, main_frame),
                fallback_proof=fallback_proof,
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=b"\x44" * 32,
                require_auth=True,
                quiet=True,
            )

        validate_fallback_text_in_pdf.assert_called_once_with(
            artifact_label="rendered recovery document recovery_document-01-deadbeefcafebabe.pdf",
            reader=reader,
            fallback_sections=mock.ANY,
            fallback_proof=fallback_proof,
        )

    def test_validate_single_recovery_document_carrier_requires_render_proof(self) -> None:
        ciphertext = b"enc:extension"
        doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )

        with mock.patch(
            "ethernity.workflows.extension.main_carrier_validation._validate_recovery_document_pdf",
            return_value=None,
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_single_recovery_document_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    frames=(main_frame,),
                    fallback_proof=None,
                    expected_doc_id=doc_id,
                    expected_doc_hash=_doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("missing fallback render proof", str(ctx.exception))

    def test_validate_published_recovery_document_carrier_checks_pdf_and_fallback(
        self,
    ) -> None:
        path = Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf")
        document = _published_recovery_document()

        with (
            mock.patch(
                "ethernity.workflows.extension.published_recovery_validation."
                "validate_pdf_has_pages",
                return_value=object(),
            ) as validate_pdf_has_pages,
            mock.patch(
                "ethernity.workflows.extension.published_recovery_validation."
                "validate_fallback_text_in_pdf"
            ) as validate_fallback_text,
        ):
            _validate_published_recovery_document_carrier(path=path, document=document)

        validate_pdf_has_pages.assert_called_once_with(
            path,
            artifact_label="published recovery document recovery_document-01-deadbeefcafebabe.pdf",
        )
        validate_fallback_text.assert_called_once_with(
            artifact_label="published recovery document recovery_document-01-deadbeefcafebabe.pdf",
            reader=mock.ANY,
            fallback_sections=mock.ANY,
        )

    def test_validate_published_recovery_document_carrier_wraps_pdf_errors(
        self,
    ) -> None:
        path = Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf")
        document = _published_recovery_document()

        with (
            mock.patch(
                "ethernity.workflows.extension.published_recovery_validation."
                "validate_pdf_has_pages",
                side_effect=RenderProofError("published recovery document is invalid"),
            ),
            self.assertRaises(ExtensionWorkflowError) as ctx,
        ):
            _validate_published_recovery_document_carrier(path=path, document=document)

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("published recovery document is invalid", str(ctx.exception))

    def test_validate_published_recovery_document_carrier_wraps_fallback_errors(
        self,
    ) -> None:
        path = Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf")
        with (
            mock.patch(
                "ethernity.workflows.extension.published_recovery_validation."
                "validate_pdf_has_pages",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.workflows.extension.published_recovery_validation."
                "validate_fallback_text_in_pdf",
                side_effect=RenderProofError("fallback mismatch"),
            ),
            self.assertRaises(ExtensionWorkflowError) as ctx,
        ):
            _validate_published_recovery_document_carrier(
                path=path,
                document=_published_recovery_document(),
            )

        self.assertIn("fallback mismatch", str(ctx.exception))

    def test_validate_single_main_carrier_rejects_mismatched_auth_for_recovery_document_scan(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=ciphertext,
        )
        auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )

        with (
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
                return_value=FrameInputResult(frames=(main_frame, auth_frame)),
            ),
            mock.patch(
                "ethernity.workflows.extension.main_carrier_validation."
                "resolve_required_auth_payload",
                return_value=(
                    AuthPayload(
                        version=1,
                        doc_hash=doc_hash,
                        sign_pub=b"\x99" * 32,
                        signature=b"\x55" * 64,
                    ),
                    "verified",
                ),
            ),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_single_main_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("root-derived signing authority", str(ctx.exception))

    def test_validate_single_main_carrier_rejects_recovery_scan_with_no_qr(
        self,
    ) -> None:
        ciphertext = b"enc:extension"
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)

        with mock.patch(
            "ethernity.workflows.extension.main_carrier_validation.recovery_frames_from_scan",
            side_effect=ValueError("scan failed: no QR codes found in scan inputs"),
        ):
            with self.assertRaises(ExtensionWorkflowError) as ctx:
                _validate_single_main_carrier(
                    path=Path("/tmp/recovery_document-01-deadbeefcafebabe.pdf"),
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=b"\x44" * 32,
                    require_auth=True,
                    quiet=True,
                )

        self.assertEqual(ctx.exception.code, EXTENSION_MAIN_CARRIER_INVALID)
        self.assertIn("no QR codes found", str(ctx.exception))
