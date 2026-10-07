from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from ethernity.workflows.add_files.errors import AddFilesIssue
from ethernity.workflows.add_files.planning import (
    AppendParent,
    AppendSigningKey,
    ResolvedAddFilesPlan,
    ResolvedAddFilesState,
)
from ethernity.workflows.add_files.request import AddFilesRequest
from ethernity.workflows.add_files.service import (
    AddFilesAssessment,
    AddFilesExecutionResult,
)

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "ethernity"
WORKFLOW_ROOT = PACKAGE_ROOT / "workflows"
PROJECT_ROOT = Path(__file__).parents[2]

_FORBIDDEN_WORKFLOW_IMPORT_PREFIXES = (
    "ethernity.app",
    "ethernity.cli",
    "ethernity.run",
    "ethernity.tasks",
    "click",
    "rich",
    "textual",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _import_sites(path: Path) -> tuple[tuple[int, str], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            sites.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            sites.append((node.lineno, node.module))
    return tuple(sites)


def test_workflows_do_not_depend_on_adapter_or_presentation_layers() -> None:
    violations: list[str] = []
    for path in sorted(WORKFLOW_ROOT.rglob("*.py")):
        for line, module in _import_sites(path):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in _FORBIDDEN_WORKFLOW_IMPORT_PREFIXES
            ):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{line}: {module}")

    assert not violations, "workflow dependency violations:\n" + "\n".join(violations)


def test_add_files_request_has_adapter_neutral_field_names() -> None:
    names = {field.name for field in fields(AddFilesRequest)}

    assert {
        "config_path",
        "paper_size",
        "scan_paths",
        "frames",
        "output_dir",
        "input_paths",
    } <= names
    assert {"config", "paper", "publish_root", "root_dir", "input", "input_dir"}.isdisjoint(names)


def test_add_files_workflow_returns_typed_issues_and_results() -> None:
    request = AddFilesRequest(input_paths=("example.txt",))
    issue = AddFilesIssue(code="EXAMPLE", message="example")
    assessment = AddFilesAssessment(request=request, issues=(issue,))
    result = AddFilesExecutionResult(assessment=assessment)

    assert assessment.issues == (issue,)
    assert result.issues == (issue,)
    assert "issues" not in {field.name for field in fields(AddFilesExecutionResult)}
    assert issue.to_dict() == {"code": "EXAMPLE", "message": "example", "details": {}}


def test_add_files_execution_plan_keeps_domain_facts_typed() -> None:
    assert [field.name for field in fields(ResolvedAddFilesPlan)] == [
        "diff",
        "parent",
        "signing_key",
        "update_mode",
    ]
    assert [field.name for field in fields(AppendParent)] == [
        "root_doc_hash",
        "head_index",
        "head_doc_hash",
    ]
    assert [field.name for field in fields(AppendSigningKey)] == ["signing_seed"]
    assert "issues" not in {field.name for field in fields(ResolvedAddFilesState)}


def test_add_files_preparation_does_not_parse_inspection_payload_keys() -> None:
    path = PACKAGE_ROOT / "workflows" / "add_files" / "prepare.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parsed_string_keys = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }

    assert {"changed_paths", "new_paths", "unchanged_paths", "missing_paths"}.isdisjoint(
        parsed_string_keys
    )


def test_add_files_execution_modules_do_not_consume_inspection_objects() -> None:
    executable_paths = (
        PACKAGE_ROOT / "workflows" / "add_files" / "prepare.py",
        PACKAGE_ROOT / "workflows" / "add_files" / "execution.py",
        PACKAGE_ROOT / "workflows" / "add_files" / "output_settings.py",
    )

    for path in executable_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Attribute) and node.attr == "inspection" for node in ast.walk(tree)
        ), path


def test_add_files_source_import_reuses_recovery_instead_of_publication_layout() -> None:
    imports: set[str] = set()
    for path in (WORKFLOW_ROOT / "add_files").glob("*.py"):
        imports.update(_imported_modules(path))

    assert "ethernity.workflows.recovery.planning" in imports
    assert "ethernity.extensions.published" not in imports
    assert "ethernity.extensions.discovery" not in imports
    assert "ethernity.workflows.add_files.published_recovery_validation" not in imports


def test_add_files_workflow_does_not_redeclare_shared_issue_codes() -> None:
    declarations: list[str] = []
    for path in (WORKFLOW_ROOT / "add_files").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    declarations.append(f"{path.name}:{target.id}")

    assert not declarations, "use workflows.shared.issue_codes:\n" + "\n".join(declarations)


def test_add_files_task_depends_only_on_public_workflow_modules() -> None:
    imports = _imported_modules(PACKAGE_ROOT / "tasks" / "add_files.py")
    workflow_imports = {
        module for module in imports if module.startswith("ethernity.workflows.add_files")
    }

    assert workflow_imports == {
        "ethernity.workflows.add_files.errors",
        "ethernity.workflows.add_files.request",
        "ethernity.workflows.add_files.service",
    }


def test_click_adapter_does_not_import_add_files_workflow() -> None:
    imports = _imported_modules(PACKAGE_ROOT / "run" / "commands" / "add_files.py")

    assert not any(module.startswith("ethernity.workflows.add_files") for module in imports)


def test_legacy_cli_implementation_is_removed() -> None:
    assert not any((PACKAGE_ROOT / "cli").rglob("*.py"))


def test_add_files_scope_reuses_shared_input_scope_types() -> None:
    path = WORKFLOW_ROOT / "add_files" / "scope.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assigned_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else (node.target,))
        if isinstance(target, ast.Name)
    }

    assert {"SelectedInputScope", "InputScopeDiff"}.isdisjoint(assigned_names)


def test_extension_builder_uses_one_input_scope_protocol_name() -> None:
    path = PACKAGE_ROOT / "extensions" / "build.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    protocols = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases)
    }

    assert protocols == {"ExtensionInputFile", "ExtensionInputScope"}


def test_browser_manifest_root_label_has_one_validator_owner() -> None:
    definitions = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "kit").rglob("*.js")
        if "function validateManifestRootLabel" in path.read_text(encoding="utf-8")
    ]

    assert definitions == ["kit/lib/path_validation.js"]
