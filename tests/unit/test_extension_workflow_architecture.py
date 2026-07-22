from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from ethernity.workflows.extension.errors import ExtensionIssue
from ethernity.workflows.extension.planning import ResolvedExtensionPlan
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.service import (
    ExtensionAssessment,
    ExtensionExecutionResult,
)

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "ethernity"
WORKFLOW_ROOT = PACKAGE_ROOT / "workflows"

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

    assert not violations, "workflow helper boundary violations:\n" + "\n".join(violations)


def test_extension_request_has_adapter_neutral_field_names() -> None:
    names = {field.name for field in fields(ExtensionRequest)}

    assert {"config_path", "paper_size", "publish_root", "input_paths"} <= names
    assert {"config", "paper", "root_dir", "input", "input_dir"}.isdisjoint(names)


def test_extension_workflow_returns_typed_issues_and_results() -> None:
    request = ExtensionRequest(input_paths=("example.txt",))
    issue = ExtensionIssue(code="EXAMPLE", message="example")
    assessment = ExtensionAssessment(request=request, issues=(issue,))
    result = ExtensionExecutionResult(assessment=assessment, issues=(issue,))

    assert assessment.issues == (issue,)
    assert result.issues == (issue,)
    assert issue.to_dict() == {"code": "EXAMPLE", "message": "example", "details": {}}


def test_extension_execution_plan_keeps_domain_facts_typed() -> None:
    assert [field.name for field in fields(ResolvedExtensionPlan)] == [
        "diff",
        "lineage",
        "authority",
        "issues",
    ]


def test_extension_preparation_does_not_parse_inspection_payload_keys() -> None:
    path = PACKAGE_ROOT / "workflows" / "extension" / "prepare.py"
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


def test_extension_execution_modules_do_not_consume_inspection_objects() -> None:
    executable_paths = (
        PACKAGE_ROOT / "workflows" / "extension" / "prepare.py",
        PACKAGE_ROOT / "workflows" / "extension" / "execution.py",
        PACKAGE_ROOT / "workflows" / "extension" / "runtime.py",
        PACKAGE_ROOT / "workflows" / "extension" / "shard_rendering.py",
        PACKAGE_ROOT / "cli" / "features" / "doctor" / "service.py",
    )

    for path in executable_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Attribute) and node.attr == "inspection" for node in ast.walk(tree)
        ), path


def test_add_files_task_depends_only_on_public_extension_workflow_modules() -> None:
    imports = _imported_modules(PACKAGE_ROOT / "tasks" / "add_files.py")
    workflow_imports = {
        module for module in imports if module.startswith("ethernity.workflows.extension")
    }

    assert workflow_imports == {
        "ethernity.workflows.extension.request",
        "ethernity.workflows.extension.service",
    }


def test_click_adapter_does_not_import_extension_workflow() -> None:
    imports = _imported_modules(PACKAGE_ROOT / "run" / "commands" / "add_files.py")

    assert not any(module.startswith("ethernity.workflows.extension") for module in imports)


def test_cli_no_longer_owns_an_extension_feature_package() -> None:
    legacy_package = PACKAGE_ROOT / "cli" / "features" / "extend"

    assert not legacy_package.exists() or not any(legacy_package.glob("*.py"))
