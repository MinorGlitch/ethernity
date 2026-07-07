from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from ethernity.config import get_api_config_snapshot
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.presentation.builder import build_task_presentation
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState


@pytest.mark.parametrize(
    "state_type",
    [
        BackupTaskState,
        RestoreTaskState,
        AddFilesTaskState,
        RebuildTaskState,
        ReplaceRecoveryDocsTaskState,
        PrintKitTaskState,
        DoctorTaskState,
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
        "BACKUP_OUTPUT_REQUIRED",
    ]
    assert [(section.key, section.status) for section in validation.sections] == [
        ("files", "missing"),
        ("recovery", "ready"),
        ("output", "missing"),
        ("layout", "ready"),
        ("advanced", "ready"),
    ]


def test_backup_task_preview_uses_beginner_language() -> None:
    state = BackupTaskState(input_paths=[Path("secrets.txt")], output_dir=Path("backup-out"))

    preview = state.preview()

    assert preview.title == "Documents to create"
    assert [item.label for item in preview.items] == [
        "Main backup document",
        "Recovery guide",
        "3 recovery documents",
        "Recovery kit index",
    ]
    assert preview.warnings[0].message == "Nothing will be written until final review."
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
    assert presentation.workspace_groups[0].empty_label == "No files selected"
    assert [issue.code for issue in presentation.outcome.blockers] == [
        "BACKUP_FILES_REQUIRED",
        "BACKUP_OUTPUT_REQUIRED",
    ]
    assert presentation.outcome.warnings == ()
    assert [item.label for item in presentation.outcome.items] == [
        "Main backup document",
        "Recovery guide",
        "3 recovery documents",
        "Recovery kit index",
    ]
    assert not presentation.primary_action.enabled


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
    assert presentation.outcome.blockers == ()
    assert presentation.workspace_groups[0].values[0].value == "secrets.txt"


def test_non_settings_task_presentations_have_task_specific_workspace_groups() -> None:
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
            ("source", "unlock", "target", "authentication", "output"),
        ),
        (
            "add_files",
            "Add files to a backup",
            AddFilesTaskState(),
            ("backup", "files", "unlock", "options", "advanced"),
        ),
        (
            "rebuild",
            "Rebuild a backup",
            RebuildTaskState(),
            ("source", "unlock", "output"),
        ),
        (
            "replace_recovery_docs",
            "Replace recovery documents",
            ReplaceRecoveryDocsTaskState(),
            ("source", "unlock", "recovery", "signing-key-recovery", "output"),
        ),
        (
            "kit",
            "Recovery kit",
            PrintKitTaskState(),
            ("print", "output"),
        ),
        (
            "doctor",
            "Setup check",
            DoctorTaskState(),
            ("checks",),
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


def test_compact_workspace_action_labels_stay_in_presentation_model() -> None:
    cases = [
        (
            "restore",
            RestoreTaskState(),
            "source",
            {
                "workspace-restore-source": "Scans",
                "workspace-restore-recovery-text": "Text",
                "workspace-restore-payloads": "Payloads",
            },
        ),
        (
            "add_files",
            AddFilesTaskState(source_paths=[Path("scan.pdf")]),
            "backup",
            {
                "workspace-add-files-freshness": "Accept",
                "workspace-add-files-fingerprint": "Hash",
            },
        ),
        (
            "rebuild",
            RebuildTaskState(source_paths=[Path("scan.pdf")]),
            "source",
            {
                "workspace-rebuild-source": "Source",
                "workspace-rebuild-freshness": "Accept",
                "workspace-rebuild-fingerprint": "Hash",
            },
        ),
        (
            "replace_recovery_docs",
            ReplaceRecoveryDocsTaskState(source_paths=[Path("scan.pdf")]),
            "source",
            {
                "workspace-replace-source": "Scans",
                "workspace-replace-recovery-text": "Text",
                "workspace-replace-payloads": "Payloads",
                "workspace-replace-freshness": "Accept",
                "workspace-replace-fingerprint": "Hash",
            },
        ),
    ]

    for task_key, state, group_key, expected_labels in cases:
        presentation = build_task_presentation(
            task_key=task_key,
            title=task_key,
            state=state,
            validation=state.validate_task(),
            preview=state.preview(),
            primary_label=f"Review {task_key}",
            diagnostics_available=False,
        )
        group = next(group for group in presentation.workspace_groups if group.key == group_key)

        labels = {action.key: action.label for action in group.actions}
        for key, label in expected_labels.items():
            assert labels[key] == label


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
    signing_seed_block = next(
        block for block in diagnostics.blocks if block.title == "Signing Private Key (hex)"
    )

    assert diagnostics.title == "Backup internals"
    assert diagnostics.has_sensitive_values
    assert "<masked chars=" in secret_block.display_content(reveal_sensitive=False)
    assert secret_block.display_content(reveal_sensitive=True) == "Passphrase\nsuper secret"
    assert "Secret Material" in block_titles
    assert "Manifest JSON" in block_titles
    assert "Input entries" in block_titles
    assert "Payload Preview (hex)" in block_titles
    assert "Envelope Preview (hex)" in block_titles
    assert "Payload Preview (z-base-32)" in block_titles
    assert signing_seed_block.display_content(reveal_sensitive=False).startswith("<masked bytes=")
    assert signing_seed_block.display_content(reveal_sensitive=True)


def test_backup_task_rejects_invalid_custom_shard_counts() -> None:
    with pytest.raises(ValidationError):
        BackupTaskState(recovery_method="custom_shards", shard_threshold=3, shard_count=2)


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
    assert "signing key any 3 of 5" in validation.sections[-1].summary
    assert [item.label for item in preview.items] == [
        "Main backup document",
        "Recovery guide",
        "3 recovery documents",
        "5 signing key recovery documents",
        "Recovery kit index",
        "QR chunk size",
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
    assert preview.title == "Restore preview"
    assert [item.label for item in preview.items] == [
        "Backup source",
        "Expected latest",
        "Unlock method",
        "Restore target",
        "Authentication",
        "Auth material",
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

    auth_item = next(item for item in preview.items if item.label == "Authentication")

    assert auth_item.detail == "Allow unsigned legacy recovery"
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
    assert next(item.detail for item in preview.items if item.label == "Auth material") == (
        "Authentication text: auth.txt"
    )
    assert args.auth_fallback_file == "auth.txt"
    assert args.auth_payloads_file is None


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
    ]
    assert str(state.execution_plan().output_paths[0]) == "recovery_kit_qr.pdf"


def test_print_kit_task_rejects_invalid_chunk_size() -> None:
    with pytest.raises(ValidationError):
        PrintKitTaskState(chunk_size=0)


def test_doctor_task_runs_without_requiring_user_input() -> None:
    state = DoctorTaskState()

    validation = state.validate_task()
    preview = state.preview()
    result = state.execute()

    assert validation.ready
    assert preview.title == "Setup check"
    assert not preview.writes_files
    assert result.message.startswith("Setup check")


def test_add_files_task_reports_missing_required_sections() -> None:
    state = AddFilesTaskState()

    validation = state.validate_task()

    assert not validation.ready
    assert [issue.code for issue in validation.issues] == [
        "ADD_FILES_BACKUP_REQUIRED",
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
    assert "New recovery any 3 of 5" in validation.sections[-1].summary
    assert [item.label for item in preview.items] == [
        "Backup folder",
        "Files to add",
        "Unlock method",
        "Recovery documents",
        "Signing key",
        "New update documents",
        "QR chunk size",
    ]
    assert args.base_dir == "."
    assert args.shard_threshold == 3
    assert args.shard_count == 5
    assert args.signing_key_mode == "sharded"
    assert args.signing_key_shard_threshold == 2
    assert args.signing_key_shard_count == 4
    assert args.qr_chunk_size == 384


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
    args = state.to_compact_args()
    assert args.root_dir == "backup-out"
    assert args.output_dir == "rebuilt"


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
    assert next(item.detail for item in preview.items if item.label == "Auth material") == (
        "Authentication payloads: auth-payloads.json"
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
    assert next(item.detail for item in preview.items if item.label == "QR chunk size") == (
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
    assert preview.title == "Replacement recovery documents to create"
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
    assert any(item.label == "Signing key recovery payloads" for item in preview.items)


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

    assert any(item.label == "Signing key recovery documents" for item in preview.items)
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
