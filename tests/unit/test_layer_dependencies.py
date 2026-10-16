"""Task and workflow logic must remain usable without either user interface."""

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "ethernity"
ADAPTER_MODULES = ("ethernity.app", "ethernity.run", "ethernity.cli", "click", "rich", "textual")


@pytest.mark.parametrize(
    "layer,forbidden",
    [("tasks", ADAPTER_MODULES), ("workflows", (*ADAPTER_MODULES, "ethernity.tasks"))],
)
def test_domain_layers_do_not_import_ui_or_command_adapters(layer, forbidden) -> None:
    violations = []
    for path in sorted((PACKAGE_ROOT / layer).rglob("*.py")):
        package = ".".join(("ethernity", *path.relative_to(PACKAGE_ROOT).parent.parts))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = resolve_name("." * node.level + module, package)
                modules = [f"{module}.{alias.name}" for alias in node.names]
            else:
                continue
            for module in modules:
                if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden):
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}: {module}")

    assert not violations, "adapter imports in shared logic:\n" + "\n".join(violations)
