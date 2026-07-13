from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from ethernity.config import get_api_config_snapshot
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.presentation.builder import build_task_presentation
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState


def _fallback_text_frame(frame_type: FrameType = FrameType.MAIN_DOCUMENT) -> str:
    frame = Frame(
        version=1,
        frame_type=frame_type,
        doc_id=b"\x11" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"payload",
    )
    return encode_zbase32(encode_frame(frame))


@pytest.mark.parametrize(
    "state_type",
    [
        BackupTaskState,
        RestoreTaskState,
        AddFilesTaskState,
        RebuildTaskState,
        ReplaceRecoveryDocsTaskState,
        PrintKitTaskState,
        SettingsTaskState,
    ],
)
def test_user_facing_task_states_reject_unknown_fields(state_type) -> None:
    with pytest.raises(ValidationError) as exc_info:
        state_type(made_up_feature=True)

    assert "extra_forbidden" in str(exc_info.value)


def test_backup_task_reports_missing_required_sections() -> None:
    state = BackupTaskState()

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "BACKUP_FILES_REQUIRED",
    ]
    assert [(section.key, section.status) for section in validation.sections] == [
        ("files", "missing"),
        ("recovery", "ready"),
        ("output", "ready"),
        ("advanced", "optional"),
    ]
    output_section = next(section for section in validation.sections if section.key == "output")
    assert output_section.summary == "Automatic folder named for backup ID"


def test_backup_task_preview_uses_beginner_language() -> None:
    state = BackupTaskState(input_paths=[Path("secrets.txt")], output_dir=Path("backup-out"))

    preview = state.preview()

    assert preview.title == "Documents to create"
    assert [item.label for item in preview.items] == [
        "Main backup document",
        "Recovery guide",
        "3 recovery sheets",
        "Kit index",
    ]
    assert preview.warnings == ()
    assert state.validate_task().ready


def test_backup_task_presentation_owns_workspace_and_outcome_copy() -> None:
    state = BackupTaskState()
    validation = state.validate_task()
    presentation = build_task_presentation(
        task_key="backup",
        title="Create a backup",
        state=state,
        validation=validation,
        preview=state.preview(),
        primary_label="Review backup",
        diagnostics_available=state.diagnostics_available(),
    )

    assert [group.key for group in presentation.workspace_groups] == [
        "files",
        "recovery",
        "destination",
        "advanced",
    ]
    assert presentation.workspace_groups[0].empty_label == "No files selected."
    assert [issue.code for issue in presentation.summary.blockers] == [
        "BACKUP_FILES_REQUIRED",
    ]
    assert presentation.summary.warnings == ()
    assert [item.label for item in presentation.summary.items] == [
        "Main backup document",
        "Recovery guide",
        "3 recovery sheets",
        "Kit index",
    ]
    assert not presentation.primary_action.enabled
    assert presentation.primary_action.label == "Review backup"


def test_ready_backup_task_presentation_enables_review_without_blockers() -> None:
    state = BackupTaskState(input_paths=[Path("secrets.txt")], output_dir=Path("backup-out"))
    validation = state.validate_task()
    presentation = build_task_presentation(
        task_key="backup",
        title="Create a backup",
        state=state,
        validation=validation,
        preview=state.preview(),
        primary_label="Review backup",
        diagnostics_available=state.diagnostics_available(),
    )

    assert presentation.primary_action.enabled
    assert presentation.summary.blockers == ()
    assert presentation.workspace_groups[0].values[0].value == "secrets.txt"


def test_task_presentations_only_build_workspace_groups_rendered_outside_guided_steps() -> None:
    cases = [
        (
            "backup",
            "Create a backup",
            BackupTaskState(),
            ("files", "recovery", "destination", "advanced"),
        ),
        (
            "restore",
            "Restore files",
            RestoreTaskState(),
            ("authentication",),
        ),
        (
            "add_files",
            "Add files to a backup",
            AddFilesTaskState(),
            ("advanced",),
        ),
        (
            "rebuild",
            "Rebuild a backup",
            RebuildTaskState(),
            ("advanced",),
        ),
        (
            "replace_recovery_docs",
            "Replace recovery documents",
            ReplaceRecoveryDocsTaskState(),
            ("signing-key-recovery",),
        ),
        (
            "kit",
            "Recovery kit",
            PrintKitTaskState(),
            ("variant", "output", "layout", "qr"),
        ),
    ]

    for task_key, title, state, expected_groups in cases:
        validation = state.validate_task()
        presentation = build_task_presentation(
            task_key=task_key,
            title=title,
            state=state,
            validation=validation,
            preview=state.preview(),
            primary_label=f"Review {task_key}",
            diagnostics_available=False,
        )

        assert [group.key for group in presentation.workspace_groups] == list(expected_groups)
        assert all(group.title for group in presentation.workspace_groups)
        assert all(group.kind for group in presentation.workspace_groups)


def test_backup_task_diagnostics_redact_sensitive_values(tmp_path) -> None:
    input_path = tmp_path / "secrets.txt"
    input_path.write_text("hello backup internals", encoding="utf-8")
    state = BackupTaskState(
        input_paths=[input_path],
        output_dir=tmp_path / "backup-out",
        passphrase="super secret",
    )

    diagnostics = state.diagnostics()
    block_titles = {block.title for block in diagnostics.blocks}
    secret_block = next(block for block in diagnostics.blocks if block.title == "Secret Material")
    manifest_block = next(block for block in diagnostics.blocks if block.title == "Manifest JSON")
    envelope_manifest_block = next(
        block for block in diagnostics.blocks if block.title == "Envelope Manifest"
    )
    signing_seed_block = next(
        block for block in diagnostics.blocks if block.title == "Signing Private Key (hex)"
    )

    assert diagnostics.title == "Backup diagnostics"
    assert diagnostics.has_sensitive_values
    assert "<masked chars=" in secret_block.display_content(reveal_sensitive=False)
    assert secret_block.display_content(reveal_sensitive=True) == "Passphrase\nsuper secret"
    assert "Secret Material" in block_titles
    assert "Manifest JSON" in block_titles
    assert "Envelope Manifest" in block_titles
    assert "Input entries" in block_titles
    assert "Payload Preview (hex)" in block_titles
    assert "Envelope Preview (hex)" in block_titles
    assert "Payload Preview (z-base-32)" in block_titles
    assert "<masked bytes=" in manifest_block.display_content(reveal_sensitive=False)
    assert "<masked bytes=" not in manifest_block.display_content(reveal_sensitive=True)
    envelope_manifest_redacted = envelope_manifest_block.display_content(reveal_sensitive=False)
    envelope_manifest_revealed = envelope_manifest_block.display_content(reveal_sensitive=True)
    assert "canonical_cbor_bytes" in envelope_manifest_redacted
    assert '"cbor"' in envelope_manifest_redacted
    assert '"files"' in envelope_manifest_redacted
    assert '"seed": "<masked bytes=' in envelope_manifest_redacted
    assert '"seed": "<masked bytes=' not in envelope_manifest_revealed
    assert '"seed": "' in envelope_manifest_revealed
    assert "00000000" not in envelope_manifest_revealed
    assert signing_seed_block.display_content(reveal_sensitive=False).startswith("<masked bytes=")
    assert signing_seed_block.display_content(reveal_sensitive=True)


def test_backup_task_rejects_invalid_custom_shard_counts() -> None:
    with pytest.raises(ValidationError):
        BackupTaskState(recovery_method="custom_shards", shard_threshold=3, shard_count=2)


def test_backup_task_accepts_zero_count_only_for_passphrase_recovery() -> None:
    state = BackupTaskState(recovery_method="single_phrase", shard_count=0)

    args = state.to_backup_args()

    assert args.shard_threshold is None
    assert args.shard_count is None
    with pytest.raises(ValidationError, match="count must be at least the threshold"):
        BackupTaskState(recovery_method="custom_shards", shard_count=0)
    with pytest.raises(ValidationError, match="count must be at least 1"):
        BackupTaskState(recovery_method="single_phrase", shard_count=-1)


def test_backup_task_rejects_invalid_qr_chunk_size() -> None:
    with pytest.raises(ValidationError):
        BackupTaskState(qr_chunk_size=0)


def test_backup_task_exposes_and_validates_advanced_signing_key_options() -> None:
    state = BackupTaskState(
        input_paths=[Path("secrets.txt")],
        output_dir=Path("backup-out"),
        signing_key_mode="sharded",
        signing_key_shard_threshold=3,
        signing_key_shard_count=5,
        passphrase_words=18,
        base_dir=Path("."),
        qr_chunk_size=384,
    )

    validation = state.validate_task()
    preview = state.preview()
    args = state.to_backup_args()

    assert validation.ready
    assert "5 key sheets, any 3 required" in validation.sections[-1].summary
    assert [item.label for item in preview.items] == [
        "Main backup document",
        "Recovery guide",
        "3 recovery sheets",
        "5 signing-key recovery sheets",
        "Kit index",
        "QR density",
    ]
    assert args.signing_key_mode == "sharded"
    assert args.signing_key_shard_threshold == 3
    assert args.signing_key_shard_count == 5
    assert args.passphrase_words == 18
    assert args.base_dir == "."
    assert args.qr_chunk_size == 384


def test_backup_task_rejects_unsupported_generated_passphrase_word_count() -> None:
    with pytest.raises(ValidationError):
        BackupTaskState(passphrase_words=8)


def test_backup_task_rejects_nonprintable_direct_passphrase_but_allows_sharding() -> None:
    with pytest.raises(ValueError, match="manually enterable printable text"):
        BackupTaskState(recovery_method="single_phrase", passphrase="alpha\nbeta")

    state = BackupTaskState(recovery_method="recommended_shards", passphrase="alpha\nbeta")

    assert state.passphrase == "alpha\nbeta"


def test_task_models_reject_quorum_counts_above_shamir_limit() -> None:
    with pytest.raises(ValidationError):
        BackupTaskState(shard_count=256)
    with pytest.raises(ValidationError):
        BackupTaskState(signing_key_shard_threshold=2, signing_key_shard_count=256)
    with pytest.raises(ValidationError):
        AddFilesTaskState(recovery_document_count=256)
    with pytest.raises(ValidationError):
        AddFilesTaskState(signing_key_recovery_threshold=2, signing_key_recovery_count=256)
    with pytest.raises(ValidationError):
        ReplaceRecoveryDocsTaskState(recovery_document_count=256)
    with pytest.raises(ValidationError):
        ReplaceRecoveryDocsTaskState(
            signing_key_recovery_threshold=2,
            signing_key_recovery_count=256,
        )


def test_backup_task_blocks_incompatible_signing_key_options() -> None:
    state = BackupTaskState(
        input_paths=[Path("secrets.txt")],
        output_dir=Path("backup-out"),
        recovery_method="single_phrase",
        signing_key_mode="sharded",
    )

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "BACKUP_SIGNING_KEY_SHARDS_REQUIRE_RECOVERY_DOCS"
    ]


def test_restore_task_reports_missing_required_sections() -> None:
    state = RestoreTaskState()

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "RESTORE_SOURCE_REQUIRED",
        "RESTORE_UNLOCK_REQUIRED",
        "RESTORE_OUTPUT_REQUIRED",
    ]
    assert [(section.key, section.status) for section in validation.sections] == [
        ("source", "missing"),
        ("unlock", "missing"),
        ("target", "ready"),
        ("output", "missing"),
    ]


def test_restore_task_ready_with_scans_passphrase_and_output() -> None:
    state = RestoreTaskState(
        source_paths=[Path("scans")],
        passphrase="secret",
        output_path=Path("recovered"),
    )

    validation = state.validate_task()
    preview = state.preview()

    assert validation.ready
    assert preview.title == "Files to restore"
    assert [item.label for item in preview.items] == [
        "Backup source",
        "Latest fingerprint",
        "Unlock",
        "Version",
        "Signature check",
        "Verification source",
    ]


def test_restore_task_exposes_unsigned_legacy_recovery_policy() -> None:
    state = RestoreTaskState(
        source_paths=[Path("scans")],
        passphrase="secret",
        output_path=Path("recovered"),
        allow_unsigned=True,
    )

    preview = state.preview()
    args = state.to_recover_args()

    auth_item = next(item for item in preview.items if item.label == "Signature check")

    assert auth_item.detail == "Unsigned legacy backups allowed"
    assert args.allow_unsigned


def test_restore_task_exposes_auth_material_inputs() -> None:
    state = RestoreTaskState(
        source_paths=[Path("scans")],
        passphrase="secret",
        output_path=Path("recovered"),
        auth_text_file=Path("auth.txt"),
    )

    validation = state.validate_task()
    preview = state.preview()
    args = state.to_recover_args()

    assert validation.ready
    assert next(item.detail for item in preview.items if item.label == "Verification source") == (
        "Signature text: auth.txt"
    )
    assert args.auth_fallback_file == "auth.txt"
    assert args.auth_payloads_file is None


def test_restore_task_accepts_pasted_recovery_text() -> None:
    state = RestoreTaskState(
        recovery_text=_fallback_text_frame(),
        passphrase="secret",
        output_path=Path("recovered"),
    )

    validation = state.validate_task()
    args = state.to_recover_args()

    assert validation.ready
    assert args.fallback_file is None
    assert args.frames is not None
    assert len(args.frames) == 1


def test_restore_task_rejects_conflicting_auth_material_inputs() -> None:
    state = RestoreTaskState(
        source_paths=[Path("scans")],
        passphrase="secret",
        output_path=Path("recovered"),
        auth_text_file=Path("auth.txt"),
        auth_payloads_file=Path("auth-payloads.json"),
    )

    validation = state.validate_task()

    assert not validation.ready
    assert "RESTORE_AUTH_MATERIAL_CONFLICT" in [issue.code for issue in validation.issues]


def test_print_kit_task_is_ready_with_default_output() -> None:
    state = PrintKitTaskState()

    validation = state.validate_task()
    preview = state.preview()

    assert validation.ready
    assert preview.title == "Recovery kit to create"
    assert [section.key for section in validation.sections] == [
        "output",
        "layout",
        "variant",
        "qr",
    ]
    assert str(state.execution_plan().output_paths[0]) == "recovery_kit_qr.pdf"


def test_print_kit_task_rejects_invalid_chunk_size() -> None:
    with pytest.raises(ValidationError):
        PrintKitTaskState(chunk_size=0)


def test_add_files_task_reports_missing_required_sections() -> None:
    state = AddFilesTaskState()

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "ADD_FILES_SOURCE_REQUIRED",
        "ADD_FILES_INPUT_REQUIRED",
        "ADD_FILES_UNLOCK_REQUIRED",
    ]


def test_add_files_task_ready_with_folder_files_and_passphrase() -> None:
    state = AddFilesTaskState(
        backup_folder=Path("backup-out"),
        input_paths=[Path("new-file.txt")],
        passphrase="secret",
    )

    validation = state.validate_task()
    preview = state.preview()

    assert validation.ready
    assert preview.title == "Backup update to create"
    args = state.to_extend_args()
    assert args.root_dir == "backup-out"
    assert args.input == ["new-file.txt"]


def test_add_files_task_exposes_advanced_update_options() -> None:
    state = AddFilesTaskState(
        backup_folder=Path("backup-out"),
        input_paths=[Path("new-file.txt")],
        passphrase="secret",
        base_dir=Path("."),
        recovery_document_threshold=3,
        recovery_document_count=5,
        signing_key_mode="sharded",
        signing_key_recovery_threshold=2,
        signing_key_recovery_count=4,
        qr_chunk_size=384,
    )

    validation = state.validate_task()
    preview = state.preview()
    args = state.to_extend_args()

    assert validation.ready
    assert validation.sections[-1].key == "advanced"
    assert "5 recovery sheets; any 3 required" in validation.sections[-1].summary
    assert [item.label for item in preview.items] == [
        "Backup source",
        "Files",
        "Unlock",
        "Destination",
        "Recovery sheets",
        "Signing-key recovery",
        "New documents",
        "QR density",
    ]
    assert args.base_dir == "."
    assert args.shard_threshold == 3
    assert args.shard_count == 5
    assert args.signing_key_mode == "sharded"
    assert args.signing_key_shard_threshold == 2
    assert args.signing_key_shard_count == 4
    assert args.qr_chunk_size == 384


def test_add_files_review_states_update_rules_and_freshness_scope() -> None:
    state = AddFilesTaskState(
        backup_folder=Path("backup-out"),
        input_paths=[Path("new-file.txt")],
        passphrase="secret",
    )

    plan = state.execution_plan()

    assert "Matching paths are replaced" in plan.safety_notes[1]
    assert "not deleted or renamed" in plan.safety_notes[1]
    assert "newest valid version in the material you loaded" in plan.trust_notes[1]
    assert "original backup and enough recovery material" in plan.recovery_notes[3]
    assert "do not add another approval" in plan.recovery_notes[3]


def test_add_files_task_rejects_invalid_qr_chunk_size() -> None:
    with pytest.raises(ValidationError):
        AddFilesTaskState(qr_chunk_size=0)


def test_add_files_task_blocks_invalid_advanced_update_options() -> None:
    reuse_root = AddFilesTaskState(
        backup_folder=Path("backup-out"),
        input_paths=[Path("new-file.txt")],
        passphrase="secret",
        unlock_policy="reuse-root",
        recovery_document_threshold=2,
        recovery_document_count=3,
    )
    invalid_quorum = AddFilesTaskState(
        backup_folder=Path("backup-out"),
        input_paths=[Path("new-file.txt")],
        passphrase="secret",
        recovery_document_threshold=4,
        recovery_document_count=3,
    )

    assert [issue.code for issue in reuse_root.validate_task().issues] == [
        "ADD_FILES_REUSE_ROOT_RECOVERY_OVERRIDE"
    ]
    assert [issue.code for issue in invalid_quorum.validate_task().issues] == [
        "ADD_FILES_RECOVERY_QUORUM_INVALID"
    ]


def test_rebuild_task_reports_missing_required_sections() -> None:
    state = RebuildTaskState()

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "REBUILD_SOURCE_REQUIRED",
        "REBUILD_UNLOCK_REQUIRED",
        "REBUILD_OUTPUT_REQUIRED",
    ]


def test_rebuild_task_ready_with_folder_passphrase_and_output() -> None:
    state = RebuildTaskState(
        backup_folder=Path("backup-out"),
        passphrase="secret",
        output_dir=Path("rebuilt"),
    )

    validation = state.validate_task()
    preview = state.preview()

    assert validation.ready
    assert preview.title == "Rebuilt backup to create"
    credentials = next(item for item in preview.items if item.label == "Credentials")
    assert credentials.detail == "Same passphrase and signing key"
    args = state.to_compact_args()
    assert args.root_dir == "backup-out"
    assert args.output_dir == "rebuilt"

    plan = state.execution_plan()
    assert "newest valid version in the material you loaded" in plan.trust_notes[1]
    assert "passphrase and signing key stay the same" in plan.recovery_notes[2]
    assert "Use Create backup" in plan.recovery_notes[3]


def test_rebuild_task_exposes_auth_material_inputs() -> None:
    state = RebuildTaskState(
        backup_folder=Path("backup-out"),
        passphrase="secret",
        output_dir=Path("rebuilt"),
        auth_payloads_file=Path("auth-payloads.json"),
    )

    validation = state.validate_task()
    preview = state.preview()
    args = state.to_compact_args()

    assert validation.ready
    assert next(item.detail for item in preview.items if item.label == "Verification source") == (
        "Signature payload: auth-payloads.json"
    )
    assert args.auth_fallback_file is None
    assert args.auth_payloads_file == "auth-payloads.json"


def test_rebuild_task_exposes_qr_chunk_size_override() -> None:
    state = RebuildTaskState(
        backup_folder=Path("backup-out"),
        passphrase="secret",
        output_dir=Path("rebuilt"),
        qr_chunk_size=384,
    )

    validation = state.validate_task()
    preview = state.preview()
    args = state.to_compact_args()

    assert validation.ready
    assert next(item.detail for item in preview.items if item.label == "QR density") == (
        "384 bytes"
    )
    assert args.qr_chunk_size == 384


def test_rebuild_task_rejects_invalid_qr_chunk_size() -> None:
    with pytest.raises(ValidationError):
        RebuildTaskState(qr_chunk_size=0)


def test_rebuild_task_rejects_conflicting_auth_material_inputs() -> None:
    state = RebuildTaskState(
        backup_folder=Path("backup-out"),
        passphrase="secret",
        output_dir=Path("rebuilt"),
        auth_text_file=Path("auth.txt"),
        auth_payloads_file=Path("auth-payloads.json"),
    )

    validation = state.validate_task()

    assert not validation.ready
    assert "REBUILD_AUTH_MATERIAL_CONFLICT" in [issue.code for issue in validation.issues]


def test_replace_recovery_docs_task_reports_missing_required_sections() -> None:
    state = ReplaceRecoveryDocsTaskState()

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "REPLACE_RECOVERY_SOURCE_REQUIRED",
        "REPLACE_RECOVERY_UNLOCK_REQUIRED",
        "REPLACE_RECOVERY_OUTPUT_REQUIRED",
    ]


def test_replace_recovery_docs_task_ready_with_scan_passphrase_and_output() -> None:
    state = ReplaceRecoveryDocsTaskState(
        source_paths=[Path("scans")],
        passphrase="secret",
        output_dir=Path("replacement-docs"),
        allow_stale_head=True,
    )

    validation = state.validate_task()
    preview = state.preview()

    assert validation.ready
    assert preview.title == "Replacement recovery sheets to create"
    args = state.to_mint_args()
    assert args.scan == ["scans"]
    assert args.output_dir == "replacement-docs"
    assert args.shard_threshold == 2
    assert args.shard_count == 3
    assert args.mint_passphrase_shards
    assert not args.mint_signing_key_shards


def test_replace_recovery_docs_signing_key_count_enables_signing_key_replacements() -> None:
    state = ReplaceRecoveryDocsTaskState(
        payloads_file=Path("main_payloads.txt"),
        recovery_payload_files=[Path("recovery_payloads.txt")],
        signing_key_recovery_payload_files=[Path("signing_payloads.txt")],
        output_dir=Path("replacement-docs"),
        mint_passphrase_recovery=False,
        signing_key_replacement_count=1,
    )

    args = state.to_mint_args()
    preview = state.preview()

    assert not args.mint_passphrase_shards
    assert args.mint_signing_key_shards
    assert args.signing_key_replacement_count == 1
    assert args.signing_key_shard_payloads_file == ["signing_payloads.txt"]
    assert any(item.label == "Existing key payloads" for item in preview.items)


def test_replace_recovery_docs_accepts_pasted_recovery_text() -> None:
    state = ReplaceRecoveryDocsTaskState(
        recovery_text=_fallback_text_frame(),
        passphrase="secret",
        output_dir=Path("replacement-docs"),
    )

    validation = state.validate_task()
    args = state.to_mint_args()

    assert validation.ready
    assert args.fallback_file is None
    assert args.frames is not None
    assert len(args.frames) == 1
    assert args.input_label == "Pasted recovery text"


def test_replace_recovery_docs_signing_key_recovery_outputs_preview_and_args() -> None:
    state = ReplaceRecoveryDocsTaskState(
        payloads_file=Path("main_payloads.txt"),
        recovery_payload_files=[Path("recovery_payloads.txt")],
        output_dir=Path("replacement-docs"),
        mint_signing_key_recovery=True,
        signing_key_recovery_threshold=3,
        signing_key_recovery_count=5,
    )

    preview = state.preview()
    args = state.to_mint_args()

    assert any(item.label == "Signing-key sheets" for item in preview.items)
    assert args.mint_signing_key_shards
    assert args.signing_key_shard_threshold == 3
    assert args.signing_key_shard_count == 5


def test_settings_task_reports_unsupported_design() -> None:
    snapshot = get_api_config_snapshot(DEFAULT_CONFIG_PATH)
    values = copy.deepcopy(snapshot.values)
    values["render"]["style"] = "unknown"
    state = SettingsTaskState(
        values=values,
        options={"render_styles": ("sentinel",)},
    )

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == ["SETTINGS_UNSUPPORTED_VALUE"]


def test_settings_descriptors_cover_config_api_snapshot_surface() -> None:
    snapshot = get_api_config_snapshot(DEFAULT_CONFIG_PATH)
    state = SettingsTaskState.from_current(DEFAULT_CONFIG_PATH)

    descriptor_paths = {descriptor.path for descriptor in state.descriptors()}

    assert descriptor_paths == _leaf_paths(snapshot.values)


def test_settings_enum_descriptors_reference_config_api_options() -> None:
    snapshot = get_api_config_snapshot(DEFAULT_CONFIG_PATH)
    state = SettingsTaskState.from_current(DEFAULT_CONFIG_PATH)

    for descriptor in state.descriptors():
        if descriptor.kind != "enum":
            continue
        assert descriptor.option_key is not None
        assert descriptor.option_key in snapshot.options
        options = tuple(str(option) for option in snapshot.options[descriptor.option_key])
        value = state.setting_value(descriptor.key)
        if value is not None:
            assert str(value) in options


def test_settings_task_writes_common_defaults(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    state = SettingsTaskState.from_current(config_path)
    state.set_setting_value("render_style", "sentinel")
    state.set_setting_value("page_size", "LETTER")
    state.set_setting_value("backup_output_dir", "backup-out")

    result = state.execute()
    snapshot = get_api_config_snapshot(config_path)

    assert result.message == "Settings saved."
    assert result.output_paths == (config_path,)
    assert snapshot.values["page"]["size"] == "LETTER"
    assert snapshot.values["defaults"]["backup"]["output_dir"] == "backup-out"


def _leaf_paths(value: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(value, dict):
        paths: set[tuple[str, ...]] = set()
        for key, child in value.items():
            paths.update(_leaf_paths(child, (*prefix, str(key))))
        return paths
    return {prefix}
