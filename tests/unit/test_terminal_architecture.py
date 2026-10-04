from __future__ import annotations

import ast
import re
from pathlib import Path

from pydantic import BaseModel

from ethernity.app.application import EthernityApp
from ethernity.app.workflow_registry import WORKFLOWS
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState

NEW_LAYER_ROOTS = (
    Path("src/ethernity/app"),
    Path("src/ethernity/run"),
    Path("src/ethernity/tasks"),
)
APP_ROOT = Path("src/ethernity/app")
WORKFLOW_WIDGET_ROOT = Path("src/ethernity/app/widgets/workflow")

FORBIDDEN_IMPORT_PATTERNS = (
    re.compile(r"^\s*(?:from|import)\s+typer\b", re.MULTILINE),
    re.compile(r"^\s*(?:from|import)\s+questionary\b", re.MULTILINE),
    re.compile(r"^\s*(?:from|import)\s+prompt_toolkit\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.bootstrap\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.bootstrap\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.features\.[^.]+\.command\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.features\.[^.]+\.command\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.shared\.ui\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.shared\.ui\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.shared\.ui_api\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.shared\.ui_api\b", re.MULTILINE),
    re.compile(r"^\s*from\s+ethernity\.cli\.shared\.recovery_prompts\b", re.MULTILINE),
    re.compile(r"^\s*import\s+ethernity\.cli\.shared\.recovery_prompts\b", re.MULTILINE),
)


def test_new_terminal_layer_does_not_import_old_interactive_cli() -> None:
    violations: list[str] = []
    for root in NEW_LAYER_ROOTS:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_IMPORT_PATTERNS:
                if pattern.search(source):
                    violations.append(f"{path}: {pattern.pattern}")

    assert violations == []


def test_source_tree_no_longer_imports_questionary_or_prompt_toolkit() -> None:
    violations: list[str] = []
    patterns = (
        re.compile(r"^\s*(?:from|import)\s+typer\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+questionary\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+prompt_toolkit\b", re.MULTILINE),
    )
    for path in sorted(Path("src/ethernity").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern.search(source):
                violations.append(f"{path}: {pattern.pattern}")

    assert violations == []


def test_old_prompt_and_typer_source_files_are_removed() -> None:
    removed_paths = (
        Path("src/ethernity/cli/bootstrap/app.py"),
        Path("src/ethernity/cli/bootstrap/__init__.py"),
        Path("src/ethernity/cli/bootstrap/entrypoint.py"),
        Path("src/ethernity/cli/bootstrap/registry.py"),
        Path("src/ethernity/cli/bootstrap/root_command.py"),
        Path("src/ethernity/cli/bootstrap/startup.py"),
        Path("src/ethernity/cli/__main__.py"),
        Path("src/ethernity/cli/shared/common.py"),
        Path("src/ethernity/cli/shared/recovery_prompts.py"),
        Path("src/ethernity/cli/shared/ui/home.py"),
        Path("src/ethernity/cli/shared/ui/picker.py"),
        Path("src/ethernity/cli/shared/ui/prompts.py"),
        Path("src/ethernity/cli/shared/ui/prompts_core.py"),
        Path("src/ethernity/cli/shared/ui/workspace.py"),
    )
    removed_globs = (
        Path("src/ethernity/cli/features").glob("*/command.py"),
        Path("src/ethernity/cli/features").glob("*/workspace.py"),
        Path("src/ethernity/cli/features").glob("*/wizard.py"),
        Path("src/ethernity/cli/features").glob("*/orchestrator.py"),
        Path("src/ethernity/cli/features").glob("*/input_collection.py"),
    )

    leftovers = [str(path) for path in removed_paths if path.exists()]
    for paths in removed_globs:
        leftovers.extend(str(path) for path in paths)

    assert sorted(leftovers) == []


def test_terminal_package_roots_are_empty_package_markers() -> None:
    package_roots = (
        Path("src/ethernity/app/__init__.py"),
        Path("src/ethernity/app/screens/__init__.py"),
        Path("src/ethernity/app/widgets/__init__.py"),
        Path("src/ethernity/run/__init__.py"),
        Path("src/ethernity/run/commands/__init__.py"),
        Path("src/ethernity/tasks/__init__.py"),
    )
    forbidden_snippets = ("__all__", "__getattr__", "import_module", "from ethernity.")

    violations: list[str] = []
    for path in package_roots:
        source = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                violations.append(f"{path}: {snippet}")

    assert violations == []


def test_terminal_forwarding_modules_are_removed() -> None:
    assert not Path("src/ethernity/app/main.py").exists()
    assert not any(Path("src/ethernity/cli").rglob("*.py"))


def test_terminal_theme_uses_textual_palette_variables() -> None:
    stylesheet = "\n".join(path.read_text(encoding="utf-8") for path in EthernityApp.CSS_PATH)

    assert re.findall(r"#[0-9a-fA-F]{6,8}", stylesheet) == []
    for token in ("$background", "$surface", "$text", "$border"):
        assert token in stylesheet


def test_terminal_styles_have_one_manifest_and_no_embedded_overrides() -> None:
    paths = EthernityApp.CSS_PATH
    assert len(paths) == len(set(paths))
    assert set(paths) == {path.resolve() for path in APP_ROOT.glob("*.tcss")}
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assignments = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        assert "DEFAULT_CSS" not in assignments, path
        assert "CSS" not in assignments, path


def test_workflow_registry_owns_every_task_state_factory(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text("", encoding="utf-8")
    expected: dict[str, type[BaseModel]] = {
        "backup": BackupTaskState,
        "restore": RestoreTaskState,
        "add_files": AddFilesTaskState,
        "rebuild": RebuildTaskState,
        "replace_recovery_docs": ReplaceRecoveryDocsTaskState,
        "kit": PrintKitTaskState,
        "settings": SettingsTaskState,
    }

    assert {workflow.key for workflow in WORKFLOWS} == set(expected)
    for workflow in WORKFLOWS:
        state = workflow.fresh_state(settings_config_path=settings_path)
        assert type(state) is expected[workflow.key]

    assert "_TASK_STATE_FACTORIES" not in Path("src/ethernity/app/app_state.py").read_text(
        encoding="utf-8"
    )


def test_guided_workflow_controls_share_one_action_message() -> None:
    message_classes: list[tuple[str, str]] = []
    for path in sorted(WORKFLOW_WIDGET_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        message_classes.extend(
            (path.name, node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("ActionRequested")
        )

    assert message_classes == [("controls.py", "WorkspaceActionRequested")]


def test_interface_uses_one_choice_dto_and_one_keyed_radio_control() -> None:
    radio_controls: list[tuple[str, str]] = []
    for path in Path("src/ethernity/app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        radio_controls.extend(
            (path.as_posix(), node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and any(isinstance(base, ast.Name) and base.id == "RadioSet" for base in node.bases)
        )

    presentation_models = Path("src/ethernity/tasks/presentation/models.py").read_text(
        encoding="utf-8"
    )
    assert radio_controls == [("src/ethernity/app/widgets/workflow/controls.py", "KeyedRadioSet")]
    assert "class ChoicePresentation:" in presentation_models
    assert "class WorkspaceChoice:" not in presentation_models


def test_running_task_state_has_one_production_owner() -> None:
    owners = {
        path
        for path in Path("src/ethernity/app").rglob("*.py")
        if "_running_task" in path.read_text(encoding="utf-8")
    }

    assert owners == {Path("src/ethernity/app/execution_controller.py")}


def test_recovery_key_compatibility_adapter_is_removed() -> None:
    removed_module = "ethernity.workflows.recovery.key_recovery"
    assert not Path("src/ethernity/workflows/recovery/key_recovery.py").exists()

    importers: list[str] = []
    for path in Path("src/ethernity").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                continue
            if removed_module in modules:
                importers.append(str(path))

    assert importers == []


def test_recovery_workflows_share_one_notice_dto() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/ethernity/workflows/recovery").rglob("*.py")
    )
    assert "FrameInputNotice" not in source
    assert "RecoveryInspectionNotice" not in source
    assert "RecoveryKeyNotice" not in source

    notices = Path("src/ethernity/workflows/shared/notices.py").read_text(encoding="utf-8")
    assert notices.count("class WorkflowNotice:") == 1


def test_recovery_checks_and_print_estimates_remain_presentation_neutral() -> None:
    for path in (
        Path("src/ethernity/tasks/recovery_check.py"),
        Path("src/ethernity/tasks/backup_estimate.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        assert not any(module.startswith(("textual", "ethernity.app")) for module in modules)
